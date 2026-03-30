from sentence_transformers import SentenceTransformer
from typing import (
    List,
    Dict,
    Any
)
import json
import boto3
from boto3.dynamodb.conditions import Key
import os
import numpy as np
from decimal import Decimal
import warnings
warnings.filterwarnings("ignore")

# Environment variables
USER_CARDS_TABLE_NAME = os.getenv("USER_CARDS_TABLE_NAME")
TXN_TABLE_NAME = os.getenv("TXN_TABLE_NAME")
REFERENCE_TABLE_NAME = os.getenv("REFERENCE_TABLE_NAME")

# BOTO3 clients and resources
dynamodb = boto3.resource('dynamodb')
user_cards_table = dynamodb.Table(USER_CARDS_TABLE_NAME) #type: ignore
txn_table = dynamodb.Table(TXN_TABLE_NAME) #type: ignore
ref_table = dynamodb.Table(REFERENCE_TABLE_NAME) #type: ignore

model = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", 
                            trust_remote_code=True,
                            model_kwargs={'default_task': 'retrieval', 
                                        #   "attn_implementation": "flash_attention_2", 
                                        #   "device_map": "auto"
                                        },
                            tokenizer_kwargs={"padding_side": "left"},
                            local_files_only=True)

def als_best_card(user_cards: List[Dict], unknown_category: str, unknown_title: str):
    """Function that returns the best card for a given geo-fenced location

    Args:
        user_cards (List[Dict]): List of user cards
        unknown_category (str): unknown cateogry
        unknown_title (str): unknown shop name
    """

    """ So the model only takes str or list[str], so we'll pass each card,
        get the scores for each category, keep the best one. Do this for all 
        cards and finally pick the highest score among the cards
    """
    unknown = f'Shop name: {unknown_title}, Category: {unknown_category}'
    # print(f"Uknown category: {unknown}")
    unknown_embedding = model.encode([unknown])
    # print(f"Embedding dimension of unknown category: {unknown_embedding.shape}")
    best_cards = []
    # Find cards with same category and store their category and score
    for card in user_cards:
        # print(card)
        # print("*" * 50)
        if 'spendBonusCategory' in card and len(card.get('spendBonusCategory', [])):
            card_categories = [category["spendBonusCategoryName"] for category in card.get('spendBonusCategory', [])]
            card_embeddings = model.encode(card_categories)
            sims = model.similarity(unknown_embedding, card_embeddings)
            print(f"Card: {card['cardMask']}\nStoring: {sims.max().item()}\nScores:\n{sims}\n{card_categories}")
            print("\x1b[31m*\x1b[0m" * 40)
            best_cards.append({
                "card": card,
                "category_idx": int(np.argmax(sims)),
                "score": float(sims.max().item())
                })

    # print(json.dumps(card_scores, indent=2))
    # Compare cashbacks (take into account limits)
    best_cards = sorted(best_cards, key=lambda x: x['score'], reverse=True)
    best_cashback = 0
    best_card = {}
    no_best_card_found = True
    # print(f"Best cards:\n\n {best_cards}")
    for best in best_cards:
        cashback = best['card']['spendBonusCategory'][best['category_idx']]['earnMultiplier']
        score = best["score"]
        # TODO: Implement consideration of spending limits to determine best card
        if score > 0.5:
            no_best_card_found = False
            if cashback > best_cashback:
                best_card = best
                best_cashback = cashback
    
    if no_best_card_found:
        print("No best category found in cards")
        best_rate = 0
        for best in best_cards:
            base_rate = best['card']['baseSpendAmount']
            if base_rate > best_rate:
                best_card = best
                best_rate = base_rate

    if best_card is None:
        return {"card": None, "category_idx": -1, "score": 0}

    print(f"Best card: {best_card}")
    print(f"Best card: {best_card['card']['cardMask']}")   
    return best_card


def fetch_user_cards(user_id):
    """Function to fetch user cards from DynamoDB for particulare userID

    Args:
        user_id (str): user ID to retrieve card information
    """
    response = user_cards_table.query(KeyConditionExpression=Key('userId').eq(user_id))
    user_card_info = response.get("Items", [])

    cards = []

    for user_card in user_card_info:
        ref_card_id = user_card.get("referenceCardId")
        if ref_card_id:
            response = ref_table.query(KeyConditionExpression=
                                    Key('PK').eq(ref_card_id)&
                                    Key('SK').eq("DETAILS"))
            if response.get("Items", []):
                ref_info = response.get("Items", [])[0]
                cards.append(user_card | ref_info)
        else:
            continue

    print(f"Number of cards: {len(cards)}")
    return cards

def transaction_analytics(transactions: List[Dict], user_cards: List[Dict], user_id: str) -> Dict:
    """
    Analyzes historical transactions to calculate missed rewards.
    Uses vectorization and batching to process hundreds of transactions in milliseconds.
    """
    if not transactions or not user_cards:
        print("Missing transactions or user cards.")
        return {
            "status": "FAILED",
            "no_txns": 0
        }

    print(f"Starting analytics for {len(transactions)} transactions...")

    # --- STEP 1: Flatten Card Categories ---
    # Get a unique list of every bonus category across all the user's cards
    unique_card_categories = set()
    for card in user_cards:
        for bonus in card.get('spendBonusCategory', []):
            unique_card_categories.add(bonus['spendBonusCategoryName'])
            
    unique_card_categories = list(unique_card_categories)
    
    if not unique_card_categories:
        print("No bonus categories found in user cards. Exiting analytics.")
        return {
            "status": "FAILED",
            "no_txns": 0
        }

    # Encode all card categories at once
    card_embeddings = model.encode(unique_card_categories)

    # --- STEP 2: Deduplicate Transactions ---
    # Create a unique signature for the ML model to prevent analyzing 'Starbucks' 20 times
    unique_txns_map = {} 
    
    for txn in transactions:
        # Ignore deposits/refunds (negative amounts or 0)
        amount = Decimal(str(txn.get('amount', 0)))
        if amount <= 0: continue
            
        merchant_name = txn.get('merchant_name') or txn.get('name') or "Unknown"
        pfc = txn.get('personal_finance_category', {})
        detailed_cat = pfc.get('detailed', 'UNKNOWN')
        
        signature = f"Shop name: {merchant_name}, Category: {detailed_cat}"
        unique_txns_map[signature] = True
            
    unique_txn_strings = list(unique_txns_map.keys())

    # --- STEP 3: Batch Encode ---
    print(f"ML Model: Batch encoding {len(unique_txn_strings)} unique transactions...")
    txn_embeddings = model.encode(unique_txn_strings)

    # --- STEP 4: Matrix Similarity (The fast part) ---
    sims = model.similarity(txn_embeddings, card_embeddings)
    
    # Map the unique signature back to the best winning category
    signature_to_best_category = {}
    for i, signature in enumerate(unique_txn_strings):
        best_idx = np.argmax(sims[i]).item()
        best_score = sims[i][best_idx].item()
        
        # Confidence Threshold: Prevent random assignments for things like "Car Payment"
        if best_score > 0.5: 
            signature_to_best_category[signature] = unique_card_categories[best_idx]
        else:
            signature_to_best_category[signature] = "None"

    # --- STEP 5: Calculate Missed Savings ---
    analyzed_transactions = []
    
    for txn in transactions:
        amount = Decimal(str(txn.get('amount', 0)))
            
        merchant_name = txn.get('merchant_name') or txn.get('name') or "Unknown"
        pfc = txn.get('personal_finance_category', {})
        detailed_cat = pfc.get('detailed', 'UNKNOWN')
        card_mask = txn.get("mask", "0000")
        
        signature = f"Shop name: {merchant_name}, Category: {detailed_cat}"
        best_category_name = signature_to_best_category.get(signature, "None")
        
        # Calculate optimal vs actual

        # ACTUAL
        actual_multiplier = Decimal('1.0') # Default base rate if card isn't mapped
        card_used = ""
        for card in user_cards:
            if card_mask == card.get("cardMask"):
                actual_multiplier = Decimal(str(card.get("baseSpendAmount", 1.0)))
                card_used = card.get("cardId")
                break

        # OPTIMAL
        optimal_multiplier = Decimal('0.0')
        optimal_card_id = None
        
        # Find the card with best value for category of transaction
        for card in user_cards:
            card_id = card.get('referenceCardId', 'Unknown Card')
            # Look for the base rate from the card schema (default to 1.0 if missing)
            base_rate = Decimal(str(card.get('baseSpendAmount', 1.0)))
            current_card_multiplier = base_rate
            
            if best_category_name != "None":
                for bonus in card.get('spendBonusCategory', []):
                    if bonus['spendBonusCategoryName'] == best_category_name:
                        current_card_multiplier = Decimal(str(bonus['earnMultiplier']))
                        break
            
            # Check optimal
            if current_card_multiplier > optimal_multiplier:
                optimal_multiplier = current_card_multiplier
                optimal_card_id = card_id
                
        missed_rewards = amount * (optimal_multiplier - actual_multiplier)
        if missed_rewards < 0: missed_rewards = Decimal('0.0')
            
        analyzed_transactions.append({
            "userId": user_id,
            "transactionId": f"{txn.get("date")}#{txn.get('transaction_id')}",
            "cardId": card_used,
            "bestCardId": optimal_card_id,
            "merchantName": merchant_name,
            "plaidCategory": detailed_cat,
            "assignedCategory": best_category_name,
            "amount": amount,
            "currency": txn.get("iso_currency_code", "USD"),
            "date": txn.get('date'),
            "bestPossibleReward": (amount * optimal_multiplier),
            "actualReward": (amount * actual_multiplier),
            "missedReward": missed_rewards
        })
        
    print(f"Analytics complete. Analyzed {len(analyzed_transactions)} transactions.")
    
    try:
        with txn_table.batch_writer() as batch:
            for txn in analyzed_transactions:
                batch.put_item(Item=txn)
        
        print(f"Upload complete. Uploaded {len(analyzed_transactions)} transactions.")
        return {
            "status": "SUCCEEDED",
            "no_txns": len(analyzed_transactions)
        }
    except Exception as e:
        print(f"Error when uploading transactions to DDB: {e}")
        return {
            "status": "FAILED",
            "no_txns": 0
        }

def lambda_handler(event, context):
    """The payload is of the following format:
    {
        "action": "ALS_RECOMMEND" | "PLAID_SYNC",
        "userId": "af23ef3"
        "transactions": list(dict) | None
        "als_data": {
            "Results": [
            {
                "PlaceId": "store-123",
                "Title": "Starbucks Coffee",
                "Categories": [{"Name": "Coffee Shop"}],
                "Address": {
                "Street": "123 Main St",
                "Locality": "Seattle"
                },
                "Contacts": {
                "Phone": "+1-206-555-0123"
                },
                "Distance": 25 
            }
            ]
        }
    }

    Returns:

    For ALS functionality:
    ----------------------
    {
        "card": Complete card information that was retrieved from DDB,
        "category_idx": Index of the category under spendBonusCategory,
        "score": Cosine similarity score of spendBonusCategory with ALS category
    }

    For PLAID_SYNC functionality:
    -----------------------------

    [
        {
            "transactionId": string,
            "bestCardId": string,
            "merchantName": string,
            "plaidCategory": string,
            "assignedCategory": string,
            "amount": float,
            "currency": string,
            "date": string,
            "bestPossibleReward": float,
            "missedReward": float
        }
    ]

    This can be standalone or wrapped in the body parameter.
    """
    # print(f"Received payload: {json.dumps(event, indent=2)}")
    try:
        if 'body' in event and event['body'] is not None:
            payload = json.loads(event.get('body'))
        else:
            # Direct invocation (AWS Console test)
            payload = event
    except Exception as e:
        print(f"Failed to parse event: {e}")
        message = {
            "status": "FAILED",
            "message": f"Failed to parse event: {e}"
        }
        return return_response(status_code=400, message=message)
    action = payload.get('action')
    user_id = payload.get('userId')
    
    # Fetch the user's linked cards from DynamoDB here
    # print("\x1b[31mFetching user cards\x1b[0m")
    user_cards = fetch_user_cards(user_id)
    # print("\x1b[32mFetched\x1b[0m")
    
    # ---------------------------------------------------------
    # ROUTE A: REAL-TIME GEOFENCE TRIGGER (From ALS)
    # ---------------------------------------------------------
    if action == "ALS_RECOMMEND":
        print("Performing ALS categorization")
        als_data = event.get('als_data', {})
        results = als_data.get("Results", [])
        
        if not results:
            print("No ALS data provided")
            message = {
                "status": "FAILED",
                "message": f"No ALS data provided."
            }
            return return_response(status_code=400, message=message)
        else: 
            title = results[0]["Title"]
            raw_category = results[0]["Categories"][0]["Name"]
            return als_best_card(user_cards=user_cards, unknown_category=raw_category, unknown_title=title)
    
    elif action == "PLAID_SYNC":
        transactions = event.get("transactions", [{}])

        if not transactions:
            print("No transaction data provided")
            message = {
                "status": "FAILED",
                "message": f"No ALS data provided."
            }
            return return_response(status_code=400, message=message)
        else:
            print("Found transactions\n")
            analyzed_transactions = transaction_analytics(transactions=transactions, user_id=user_id, user_cards=user_cards)
            if analyzed_transactions["status"] == "SUCCEEDED":
                message = {
                    "status": "SUCCEDDED",
                    "message": f"{len(analyzed_transactions)} Transactions categorized"
                }
                return return_response(status_code=200, message=message)
            else:
                message = {
                    "status": "FAILED",
                    "message": f"Transaction analytics failed, check logs"
                }
                return return_response(status_code=400, message=message)
        


def return_response(status_code: int, message: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(message)
    }

if __name__ == "__main__":
    event = {
        "action": "ALS_RECOMMEND",
        "userId": "84085468-f091-7071-ff5a-c60fcf8c6ba9",
        "transactions": [],
        "als_data": {
            "Results": [
                {
                    "PlaceId": "store-123",
                    "Title": "Delta Airlines",
                    "Categories": [{"Name": "Airfare"}],
                    "Address": {
                        "Street": "123 Main St",
                        "Locality": "Seattle"
                    },
                    "Contacts": {
                        "Phone": "+1-206-555-0123"
                    },
                    "Distance": 25
                }
            ]
        }
    }
    lambda_handler(event=event, context=None)