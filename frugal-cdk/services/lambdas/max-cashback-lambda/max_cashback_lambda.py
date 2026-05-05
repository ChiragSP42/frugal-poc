from typing import List, Dict
from sentence_transformers import SentenceTransformer
import json
import boto3
from boto3.dynamodb.conditions import Key, Attr
import os
import numpy as np
from decimal import Decimal
import datetime
import warnings
warnings.filterwarnings("ignore")

# Environment variables
USER_CARDS_TABLE_NAME = os.getenv("USER_CARDS_TABLE_NAME")
TXN_TABLE_NAME = os.getenv("TXN_TABLE_NAME")
REFERENCE_TABLE_NAME = os.getenv("REFERENCE_TABLE_NAME")

# BOTO3 clients and resources
dynamodb = boto3.resource('dynamodb')
user_cards_table = dynamodb.Table(USER_CARDS_TABLE_NAME)  # type: ignore
txn_table = dynamodb.Table(TXN_TABLE_NAME)  # type: ignore
ref_table = dynamodb.Table(REFERENCE_TABLE_NAME)  # type: ignore

# Load the embedding model (same as card-recommendation-lambda)
model = SentenceTransformer(
    "jinaai/jina-embeddings-v5-text-nano",
    trust_remote_code=True,
    model_kwargs={"default_task": "retrieval"},
    tokenizer_kwargs={"padding_side": "left"},
    local_files_only=True,
)


def fetch_user_cards(user_id: str) -> List[Dict]:
    """Fetch user cards merged with reference card details from DynamoDB."""
    response = user_cards_table.query(
        KeyConditionExpression=Key("userId").eq(user_id)
    )
    user_card_info = response.get("Items", [])

    cards = []
    for user_card in user_card_info:
        ref_card_id = user_card.get("referenceCardId")
        if not ref_card_id:
            continue
        ref_response = ref_table.query(
            KeyConditionExpression=Key("PK").eq(ref_card_id) & Key("SK").eq("DETAILS")
        )
        ref_items = ref_response.get("Items", [])
        if ref_items:
            cards.append(user_card | ref_items[0])

    print(f"Fetched {len(cards)} cards for user {user_id}")
    return cards


def fetch_all_reference_cards() -> List[Dict]:
    """Fetch all reference cards from the Reference table."""
    cards = []
    scan_kwargs = {
        "FilterExpression": Attr("entityType").eq("ReferenceCard"),
    }

    while True:
        response = ref_table.scan(**scan_kwargs)
        cards.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    print(f"Fetched {len(cards)} reference cards from the database")
    return cards


def fetch_transactions_last_year(user_id: str) -> List[Dict]:
    """Fetch all analyzed transactions for a user from the last 12 months.

    The Txn table uses userId as PK and transactionId (date#txn_id) as SK,
    so we can range-query by date prefix to get the last year's worth.
    """
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    start_key = one_year_ago.isoformat()

    transactions = []
    query_kwargs = {
        "KeyConditionExpression": Key("userId").eq(user_id)
        & Key("transactionId").gte(start_key),
    }

    # Paginate through all results
    while True:
        response = txn_table.query(**query_kwargs)
        transactions.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        query_kwargs["ExclusiveStartKey"] = last_key

    print(f"Fetched {len(transactions)} transactions for user {user_id} since {start_key}")
    return transactions


def compute_cashback_for_card(
    card: Dict,
    transactions: List[Dict],
    txn_signatures: List[str],
    txn_embeddings,
) -> Decimal:
    """Compute total hypothetical cashback if ALL transactions were on this card.

    Uses semantic similarity (same approach as card-recommendation-lambda) to
    match each transaction's merchant+category signature against this card's
    bonus categories, then applies the best matching multiplier (or base rate).
    """
    bonus_categories = card.get("spendBonusCategory", [])
    base_rate = Decimal(str(card.get("baseSpendAmount", 1.0)))

    if not bonus_categories:
        # Card has no bonus categories — everything earns the base rate
        total = sum(
            Decimal(str(txn.get("amount", 0))) for txn in transactions
            if Decimal(str(txn.get("amount", 0))) > 0
        )
        return total * base_rate / Decimal("100")

    # Encode this card's bonus category names
    cat_names = [b["spendBonusCategoryName"] for b in bonus_categories]
    card_embeddings = model.encode(cat_names)

    # Similarity: each txn signature vs this card's categories
    sims = model.similarity(txn_embeddings, card_embeddings)

    # Build a lookup: txn_signature -> best multiplier for this card
    sig_to_multiplier = {}
    for i, sig in enumerate(txn_signatures):
        best_idx = int(np.argmax(sims[i]).item())
        best_score = float(sims[i][best_idx].item())

        if best_score > 0.5:
            sig_to_multiplier[sig] = Decimal(
                str(bonus_categories[best_idx]["earnMultiplier"])
            )
        else:
            sig_to_multiplier[sig] = base_rate

    # Sum up cashback across all transactions
    total_cashback = Decimal("0.0")
    for txn in transactions:
        amount = Decimal(str(txn.get("amount", 0)))
        if amount <= 0:
            continue

        merchant = txn.get("merchantName", "Unknown")
        plaid_cat = txn.get("plaidCategory", "UNKNOWN")
        sig = f"Shop name: {merchant}, Category: {plaid_cat}"

        multiplier = sig_to_multiplier.get(sig, base_rate)
        total_cashback += amount * multiplier / Decimal("100")

    return total_cashback


def calculate_max_annual_cashback(user_id: str) -> Dict:
    """Main logic: for each reference card in the database, simulate annual cashback and pick the best."""
    all_cards = fetch_all_reference_cards()
    if not all_cards:
        return {"status": "FAILED", "message": "No reference cards found in the database."}

    transactions = fetch_transactions_last_year(user_id)
    if not transactions:
        return {"status": "FAILED", "message": "No transactions found for the last year."}

    # Build unique transaction signatures and batch-encode once
    unique_sigs = {}
    for txn in transactions:
        amount = Decimal(str(txn.get("amount", 0)))
        if amount <= 0:
            continue
        merchant = txn.get("merchantName", "Unknown")
        plaid_cat = txn.get("plaidCategory", "UNKNOWN")
        sig = f"Shop name: {merchant}, Category: {plaid_cat}"
        unique_sigs[sig] = True

    sig_list = list(unique_sigs.keys())
    print(f"Batch encoding {len(sig_list)} unique transaction signatures...")
    txn_embeddings = model.encode(sig_list)

    # Evaluate each card
    best_card = None
    best_cashback = Decimal("0.0")
    card_results = []

    for card in all_cards:
        cashback = compute_cashback_for_card(
            card=card,
            transactions=transactions,
            txn_signatures=sig_list,
            txn_embeddings=txn_embeddings,
        )
        card_id = card.get("PK", card.get("cardKey", "Unknown"))
        card_name = card.get("cardName", "Unknown")
        card_issuer = card.get("cardIssuer", "")

        card_results.append({
            "cardId": card_id,
            "cardName": card_name,
            "cardIssuer": card_issuer,
            "annualCashback": str(cashback),
        })

        print(f"Card '{card_name}' ({card_issuer}): ${cashback:.2f}")

        if cashback > best_cashback:
            best_cashback = cashback
            best_card = card

    if not best_card:
        return {"status": "FAILED", "message": "Could not determine best card."}

    return {
        "status": "SUCCEEDED",
        "bestCard": {
            "cardId": best_card.get("PK", best_card.get("cardKey")),
            "cardName": best_card.get("cardName", "Unknown"),
            "cardIssuer": best_card.get("cardIssuer", ""),
            "cardImageUrl": best_card.get("cardImageUrl", ""),
        },
        "maxAnnualCashback": str(best_cashback),
        "allCards": card_results,
        "transactionCount": len(transactions),
    }


def lambda_handler(event, context):
    """
    Expected payload:
    {
        "userId": "84085468-f091-7071-ff5a-c60fcf8c6ba9"
    }

    Returns:
    {
        "statusCode": 200,
        "body": {
            "status": "SUCCEEDED",
            "bestCard": { "cardId": ..., "cardName": ..., ... },
            "maxAnnualCashback": "523.47",
            "allCards": [ { "cardId": ..., "annualCashback": ... }, ... ],
            "transactionCount": 312
        }
    }
    """
    try:
        if "body" in event and event["body"] is not None:
            payload = json.loads(event["body"])
        else:
            payload = event
    except Exception as e:
        print(f"Failed to parse event: {e}")
        return return_response(400, {"status": "FAILED", "message": f"Bad request: {e}"})

    user_id = payload.get("userId")
    if not user_id:
        return return_response(400, {"status": "FAILED", "message": "Missing userId"})

    result = calculate_max_annual_cashback(user_id)

    if result["status"] == "SUCCEEDED":
        return return_response(200, result)
    else:
        return return_response(400, result)


def return_response(status_code: int, message: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(message),
    }


if __name__ == "__main__":
    event = {"userId": "84085468-f091-7071-ff5a-c60fcf8c6ba9"}
    print(json.dumps(lambda_handler(event=event, context=None), indent=2))
