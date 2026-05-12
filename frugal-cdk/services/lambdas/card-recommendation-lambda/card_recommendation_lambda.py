from typing import (
    List,
    Dict,
    Any
)
from sentence_transformers import SentenceTransformer
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

# --- PLAID CATEGORY → FRUGAL SPENDING CATEGORY MAPPING ---
PLAID_DETAILED_CATEGORY_MAP = {
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": "Groceries",
    "TRANSPORTATION_GAS": "Gas",
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": "Travel",
    "TRANSPORTATION_PUBLIC_TRANSIT": "Travel",
    "TRANSPORTATION_PARKING": "Travel",
    "TRANSPORTATION_TOLLS": "Travel",
    "TRAVEL_FLIGHTS": "Travel",
    "TRAVEL_LODGING": "Travel",
    "TRAVEL_RENTAL_CARS": "Travel",
    "ENTERTAINMENT_TV_AND_MOVIES": "DigitalEntertainment",
    "ENTERTAINMENT_MUSIC_AND_AUDIO": "DigitalEntertainment",
    "ENTERTAINMENT_VIDEO_GAMES": "DigitalEntertainment",
}

PLAID_PRIMARY_CATEGORY_MAP = {
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Retail",
    "ENTERTAINMENT": "DigitalEntertainment",
    "TRAVEL": "Travel",
    "TRANSPORTATION": "Gas",
    "GENERAL_SERVICES": "Other",
    "PERSONAL_CARE": "Other",
    "MEDICAL": "Other",
    "HOME_IMPROVEMENT": "Retail",
    "RENT_AND_UTILITIES": "Other",
    "LOAN_PAYMENTS": "Other",
    "BANK_FEES": "Other",
    "TRANSFER_IN": "Other",
    "TRANSFER_OUT": "Other",
    "INCOME": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
}

# --- PLAID CATEGORY → CARD spendBonusCategoryName LOOKUP TABLE ---
# Maps Plaid detailed categories to the spendBonusCategoryName values used in the
# reference card database. This enables deterministic matching of a transaction to
# a card's bonus category without relying on embeddings for the "actual reward" calculation.
#
# spendBonusCategoryName values in the card DB:
#   Dining, Gas Station, Online, Restaurants & Cafes, Shopping,
#   Streaming services, Supermarkets,
#   Travel - Flights, Travel - Lodging, Travel - Car Rental

PLAID_TO_BONUS_CATEGORY = {
    # --- FOOD & DRINK ---
    "FOOD_AND_DRINK_GROCERIES": "Supermarkets",
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": "Supermarkets",
    "FOOD_AND_DRINK_COFFEE": "Restaurants & Cafes",
    "FOOD_AND_DRINK_FAST_FOOD": "Restaurants & Cafes",
    "FOOD_AND_DRINK_RESTAURANT": "Restaurants & Cafes",
    "FOOD_AND_DRINK_VENDING_MACHINES": "Restaurants & Cafes",
    "FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK": "Restaurants & Cafes",

    # --- TRANSPORTATION ---
    "TRANSPORTATION_GAS": "Gas Station",
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": "Travel - Flights",
    "TRANSPORTATION_PUBLIC_TRANSIT": None,
    "TRANSPORTATION_PARKING": None,
    "TRANSPORTATION_TOLLS": None,
    "TRANSPORTATION_BIKES_AND_SCOOTERS": None,
    "TRANSPORTATION_OTHER_TRANSPORTATION": None,

    # --- TRAVEL ---
    "TRAVEL_FLIGHTS": "Travel - Flights",
    "TRAVEL_LODGING": "Travel - Lodging",
    "TRAVEL_RENTAL_CARS": "Travel - Car Rental",
    "TRAVEL_OTHER_TRAVEL": "Travel - Flights",

    # --- ENTERTAINMENT ---
    "ENTERTAINMENT_TV_AND_MOVIES": "Streaming services",
    "ENTERTAINMENT_MUSIC_AND_AUDIO": "Streaming services",
    "ENTERTAINMENT_VIDEO_GAMES": "Streaming services",
    "ENTERTAINMENT_CASINOS_AND_GAMBLING": None,
    "ENTERTAINMENT_SPORTING_EVENTS_AMUSEMENT_PARKS_AND_MUSEUMS": None,
    "ENTERTAINMENT_OTHER_ENTERTAINMENT": None,

    # --- GENERAL MERCHANDISE ---
    "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES": "Online",
    "GENERAL_MERCHANDISE_SUPERSTORES": "Supermarkets",
    "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES": "Shopping",
    "GENERAL_MERCHANDISE_DEPARTMENT_STORES": "Shopping",
    "GENERAL_MERCHANDISE_DISCOUNT_STORES": "Shopping",
    "GENERAL_MERCHANDISE_ELECTRONICS": "Shopping",
    "GENERAL_MERCHANDISE_CONVENIENCE_STORES": None,
    "GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS": None,
    "GENERAL_MERCHANDISE_GIFTS_AND_NOVELTIES": "Shopping",
    "GENERAL_MERCHANDISE_OFFICE_SUPPLIES": None,
    "GENERAL_MERCHANDISE_PET_SUPPLIES": None,
    "GENERAL_MERCHANDISE_SPORTING_GOODS": "Shopping",
    "GENERAL_MERCHANDISE_TOBACCO_AND_VAPE": None,
    "GENERAL_MERCHANDISE_OTHER_GENERAL_MERCHANDISE": None,

    # --- HOME IMPROVEMENT ---
    "HOME_IMPROVEMENT_FURNITURE": None,
    "HOME_IMPROVEMENT_HARDWARE": None,
    "HOME_IMPROVEMENT_REPAIR_AND_MAINTENANCE": None,
    "HOME_IMPROVEMENT_SECURITY": None,
    "HOME_IMPROVEMENT_OTHER_HOME_IMPROVEMENT": None,

    # --- RENT & UTILITIES ---
    "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY": None,
    "RENT_AND_UTILITIES_INTERNET_AND_CABLE": "Streaming services",
    "RENT_AND_UTILITIES_RENT": None,
    "RENT_AND_UTILITIES_SEWAGE_AND_WASTE_MANAGEMENT": None,
    "RENT_AND_UTILITIES_TELEPHONE": None,
    "RENT_AND_UTILITIES_WATER": None,
    "RENT_AND_UTILITIES_OTHER_UTILITIES": None,

    # --- GENERAL SERVICES ---
    "GENERAL_SERVICES_AUTOMOTIVE": None,
    "GENERAL_SERVICES_CHILDCARE": None,
    "GENERAL_SERVICES_CONSULTING_AND_LEGAL": None,
    "GENERAL_SERVICES_EDUCATION": None,
    "GENERAL_SERVICES_INSURANCE": None,
    "GENERAL_SERVICES_POSTAGE_AND_SHIPPING": None,
    "GENERAL_SERVICES_STORAGE": None,
    "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING": None,
    "GENERAL_SERVICES_OTHER_GENERAL_SERVICES": None,

    # --- PERSONAL CARE ---
    "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS": None,
    "PERSONAL_CARE_HAIR_AND_BEAUTY": None,
    "PERSONAL_CARE_LAUNDRY_AND_DRY_CLEANING": None,
    "PERSONAL_CARE_OTHER_PERSONAL_CARE": None,

    # --- MEDICAL ---
    "MEDICAL_DENTAL_CARE": None,
    "MEDICAL_EYE_CARE": None,
    "MEDICAL_NURSING_CARE": None,
    "MEDICAL_PHARMACIES_AND_SUPPLEMENTS": None,
    "MEDICAL_PRIMARY_CARE": None,
    "MEDICAL_VETERINARY_SERVICES": None,
    "MEDICAL_OTHER_MEDICAL": None,
}

# Fallback: maps Plaid PRIMARY category to a spendBonusCategoryName when detailed is not found
PLAID_PRIMARY_TO_BONUS_CATEGORY = {
    "FOOD_AND_DRINK": "Restaurants & Cafes",
    "TRANSPORTATION": "Gas Station",
    "TRAVEL": "Travel - Flights",
    "ENTERTAINMENT": "Streaming services",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": None,
    "RENT_AND_UTILITIES": None,
    "GENERAL_SERVICES": None,
    "PERSONAL_CARE": None,
    "MEDICAL": None,
    "LOAN_PAYMENTS": None,
    "BANK_FEES": None,
    "TRANSFER_IN": None,
    "TRANSFER_OUT": None,
    "INCOME": None,
    "GOVERNMENT_AND_NON_PROFIT": None,
}


def resolve_bonus_category(detailed_cat: str, primary_cat: str):
    """Resolves a Plaid transaction category to the card database's spendBonusCategoryName.
    
    Returns the spendBonusCategoryName string if a match exists, or None if the transaction
    doesn't map to any card bonus category (i.e., base rate applies).
    """
    if detailed_cat and detailed_cat in PLAID_TO_BONUS_CATEGORY:
        return PLAID_TO_BONUS_CATEGORY[detailed_cat]
    if primary_cat and primary_cat in PLAID_PRIMARY_TO_BONUS_CATEGORY:
        return PLAID_PRIMARY_TO_BONUS_CATEGORY[primary_cat]
    return None


def map_plaid_category(detailed, primary):
    """Maps Plaid personal_finance_category to a Frugal SpendingCategory.
    Prefers the more granular 'detailed' field, falls back to 'primary'.
    """
    if detailed and detailed in PLAID_DETAILED_CATEGORY_MAP:
        return PLAID_DETAILED_CATEGORY_MAP[detailed]
    if primary and primary in PLAID_PRIMARY_CATEGORY_MAP:
        return PLAID_PRIMARY_CATEGORY_MAP[primary]
    return "Other"


model = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", 
                            trust_remote_code=True,
                            model_kwargs={'default_task': 'retrieval', 
                                        #   "attn_implementation": "flash_attention_2", 
                                        #   "device_map": "auto"
                                        },
                            tokenizer_kwargs={"padding_side": "left"},
                            local_files_only=True)

def als_best_card(user_cards: List[Dict], unknown_category: str, unknown_title: str):
    """Function that returns the best card for a given geo-fenced location.

    Uses a two-pass approach:
      Pass 1 — Exact match on pocCategory (deterministic, fast).
      Pass 2 — Embedding similarity on spendBonusCategoryName (fuzzy fallback).

    The merchant title is intentionally excluded from the embedding string so
    that the category signal is not diluted by the shop name.

    Args:
        user_cards (List[Dict]): List of user cards
        unknown_category (str): ALS category from Categories[].Name
        unknown_title (str): merchant / shop name (used for logging only)
    """

    # ── Pass 1: Exact match on pocCategory ──────────────────────────────
    exact_matches = []
    for card in user_cards:
        bonus_categories = card.get('spendBonusCategory', [])
        if not bonus_categories:
            continue
        for idx, bonus in enumerate(bonus_categories):
            poc = bonus.get('pocCategory', '').strip().lower()
            if poc == unknown_category.strip().lower():
                exact_matches.append({
                    "card": card,
                    "category_idx": idx,
                    "score": 1.0  # perfect match
                })
                break  # one match per card is enough

    if exact_matches:
        print(f"[Pass 1] Exact pocCategory match for '{unknown_category}' — {len(exact_matches)} card(s)")
        # Pick the card with the highest earnMultiplier for the matched category
        best_card = max(
            exact_matches,
            key=lambda m: float(m['card']['spendBonusCategory'][m['category_idx']]['earnMultiplier'])
        )
        print(f"Best card (exact): {best_card['card']['cardMask']}")
        return best_card

    # ── Pass 2: Embedding similarity (fuzzy fallback) ───────────────────
    print(f"[Pass 2] No exact pocCategory match for '{unknown_category}' — falling back to embedding similarity")
    unknown = f'{unknown_category}'
    unknown_embedding = model.encode([unknown])
    best_cards = []

    for card in user_cards:
        bonus_categories = card.get('spendBonusCategory', [])
        if not bonus_categories:
            continue
        card_categories = [cat["spendBonusCategoryName"] for cat in bonus_categories]
        card_embeddings = model.encode(card_categories)
        sims = model.similarity(unknown_embedding, card_embeddings)
        print(f"Card: {card['cardMask']}\nStoring: {sims.max().item()}\nScores:\n{sims}\n{card_categories}")
        print("\x1b[31m*\x1b[0m" * 40)
        best_cards.append({
            "card": card,
            "category_idx": int(np.argmax(sims)),
            "score": float(sims.max().item())
        })

    # Compare cashbacks (take into account limits)
    best_cards = sorted(best_cards, key=lambda x: x['score'], reverse=True)
    best_cashback = 0
    best_card = None
    no_best_card_found = True

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
    POC_CATEGORIES = ["Retail", "Dining", "Travel", "Groceries", "Digital Entertainment"]

    poc_embeddings = model.encode(POC_CATEGORIES)

    if not transactions or not user_cards:
        print("Missing transactions or user cards.")
        return {
            "status": "FAILED",
            "no_txns": 0
        }

    print(f"Starting analytics for {len(transactions)} transactions...")

    # --- STEP 0: Build account_id → cardNickname lookup ---
    account_to_nickname = {}
    for card in user_cards:
        linked_account_id = card.get("linkedAccountId", "")
        nickname = card.get("cardNickname", "")
        if linked_account_id and nickname:
            account_to_nickname[linked_account_id] = nickname

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
        detailed_cat = detailed_cat.replace("_", " ")
        
        signature = f"{detailed_cat}"
        unique_txns_map[signature] = True
            
    unique_txn_strings = list(unique_txns_map.keys())

    # --- STEP 3: Batch Encode ---
    print(f"ML Model: Batch encoding {len(unique_txn_strings)} unique transactions...")
    txn_embeddings = model.encode(unique_txn_strings)

    # --- STEP 4: Similarity & Per-Card Best Category Resolution ---
    # Compute similarity between transactions and the global set of card categories
    sims = model.similarity(txn_embeddings, card_embeddings)

    # POC category assignment (for labeling purposes)
    poc_sims = model.similarity(txn_embeddings, poc_embeddings)

    # For each transaction signature, determine the best-matching category name
    # (used for labeling in the output — assignedCategory field)
    signature_to_best_category = {}
    for i, signature in enumerate(unique_txn_strings):
        best_idx = np.argmax(sims[i]).item()
        signature_to_best_category[signature] = unique_card_categories[best_idx]

    # POC category mapping (for labeling)
    signature_to_poc_category = {}
    for i, signature in enumerate(unique_txn_strings):
        best_idx = np.argmax(poc_sims[i]).item()
        signature_to_poc_category[signature] = POC_CATEGORIES[best_idx]

    # --- STEP 4b: Build per-card category embeddings for optimal card selection ---
    # For each card, store its bonus category names and their embeddings together
    # so we can do per-card similarity matching in Step 5.
    card_bonus_data = []
    for card in user_cards:
        bonus_categories = card.get('spendBonusCategory', [])
        if bonus_categories:
            cat_names = [b['spendBonusCategoryName'] for b in bonus_categories]
            cat_multipliers = [Decimal(str(b['earnMultiplier'])) for b in bonus_categories]
            cat_embeddings_card = model.encode(cat_names)
            card_bonus_data.append({
                "card": card,
                "cat_names": cat_names,
                "cat_multipliers": cat_multipliers,
                "cat_embeddings": cat_embeddings_card
            })
        else:
            # Card has no bonus categories — will only compete on base rate
            card_bonus_data.append({
                "card": card,
                "cat_names": [],
                "cat_multipliers": [],
                "cat_embeddings": None
            })

    # Pre-compute per-card best multiplier for each transaction signature
    # This finds the optimal card by comparing effective reward rates directly
    signature_to_optimal = {}
    for i, signature in enumerate(unique_txn_strings):
        txn_emb = txn_embeddings[i:i+1]  # shape (1, dim)
        
        best_multiplier = Decimal('0.0')
        best_card_id = None
        best_bonus_category = "None"

        for card_data in card_bonus_data:
            card = card_data["card"]
            card_id = card.get('referenceCardId', 'Unknown Card')
            base_rate = Decimal(str(card.get('baseSpendAmount', 1.0)))
            
            # Start with the card's base rate as its effective multiplier
            effective_multiplier = base_rate
            matched_category = "None"

            # If the card has bonus categories, find the best-matching one
            if card_data["cat_embeddings"] is not None:
                card_sims = model.similarity(txn_emb, card_data["cat_embeddings"])
                best_cat_idx = np.argmax(card_sims[0]).item()
                best_cat_multiplier = card_data["cat_multipliers"][best_cat_idx]
                
                # Use the bonus multiplier if it beats the card's own base rate
                # (no hard threshold — trust the relative ranking)
                if best_cat_multiplier > base_rate:
                    effective_multiplier = best_cat_multiplier
                    matched_category = card_data["cat_names"][best_cat_idx]

            # Compare against the current best across all cards
            if effective_multiplier > best_multiplier:
                best_multiplier = effective_multiplier
                best_card_id = card_id
                best_bonus_category = matched_category

        signature_to_optimal[signature] = {
            "optimal_multiplier": best_multiplier,
            "optimal_card_id": best_card_id,
            "matched_category": best_bonus_category
        }

    # --- STEP 5: Calculate Missed Savings ---
    SKIP_PRIMARY_CATEGORIES = {"LOAN_PAYMENTS", "BANK_FEES", "TRANSFER_IN", "TRANSFER_OUT"}
    analyzed_transactions = []
    
    for txn in transactions:
        amount = Decimal(str(txn.get('amount', 0)))
            
        merchant_name = txn.get('merchant_name') or txn.get('name') or "Unknown"
        pfc = txn.get('personal_finance_category', {})
        detailed_cat_raw = pfc.get('detailed', 'UNKNOWN')  # Original with underscores (for lookup)
        detailed_cat = detailed_cat_raw.replace("_", " ")  # Spaces (for embedding signature)
        primary_cat = pfc.get('primary', '')
        card_mask = txn.get("mask", "0000")

        # Determine if this transaction should skip cashback calculation
        skip_cashback = amount <= 0 or primary_cat in SKIP_PRIMARY_CATEGORIES
        
        signature = f"{detailed_cat}"
        best_category_name = signature_to_best_category.get(signature, "None")
        poc_category_name = signature_to_poc_category.get(signature, "None")
        
        # Calculate optimal vs actual (only for eligible transactions)
        if skip_cashback:
            actual_multiplier = Decimal('0.0')
            optimal_multiplier = Decimal('0.0')
            optimal_card_id = None
            card_used = ""
            missed_rewards = Decimal('0.0')
        else:
            # ACTUAL: What the user earned with the card they used.
            # Strategy: Use the PLAID_TO_BONUS_CATEGORY lookup to find the transaction's
            # spendBonusCategoryName, then check if the card used has a bonus for that category.
            # If yes → apply the bonus multiplier. If no → fall back to base rate.
            actual_multiplier = Decimal('1.0')  # Default base rate if card isn't mapped
            card_used = ""
            txn_bonus_category = resolve_bonus_category(detailed_cat_raw, primary_cat)

            for card in user_cards:
                if card_mask == card.get("cardMask"):
                    card_used = card.get("cardId")
                    base_rate = Decimal(str(card.get("baseSpendAmount", 1.0)))
                    actual_multiplier = base_rate  # Start with base rate

                    # Try to find a matching bonus category via spendBonusCategoryName lookup
                    if txn_bonus_category:
                        for bonus in card.get('spendBonusCategory', []):
                            if bonus.get('spendBonusCategoryName', '').strip().lower() == txn_bonus_category.strip().lower():
                                bonus_multiplier = Decimal(str(bonus.get('earnMultiplier', 0)))
                                if bonus_multiplier > actual_multiplier:
                                    actual_multiplier = bonus_multiplier
                                break  # First match wins
                    break

            # OPTIMAL: Best possible card from pre-computed per-card matching
            optimal_info = signature_to_optimal.get(signature, {})
            optimal_multiplier = optimal_info.get("optimal_multiplier", Decimal('0.0'))
            optimal_card_id = optimal_info.get("optimal_card_id", None)
                    
            missed_rewards = abs(amount) * (optimal_multiplier - actual_multiplier) / Decimal('100')
            if missed_rewards < 0: missed_rewards = Decimal('0.0')
            
        # Map Plaid category → Frugal SpendingCategory
        category = map_plaid_category(detailed_cat_raw, primary_cat)

        # Resolve cardNickname from the Plaid account_id
        account_id = txn.get('account_id', '')
        card_nickname = account_to_nickname.get(account_id, None)

        analyzed_transactions.append({
            "userId": user_id,
            "transactionId": f"{txn.get('date')}#{txn.get('transaction_id')}",
            "accountId": account_id,
            "cardId": card_used,
            "bestCardId": optimal_card_id,
            "merchantName": merchant_name,
            "plaidCategory": detailed_cat_raw,
            "assignedCategory": best_category_name,
            "pocCategory": poc_category_name,
            "category": category,
            "cardNickname": card_nickname,
            "amount": amount,
            "currency": txn.get("iso_currency_code", "USD"),
            "date": txn.get('date'),
            "bestPossibleReward": (abs(amount) * optimal_multiplier / Decimal('100')) if not skip_cashback else Decimal('0.0'),
            "actualReward": (abs(amount) * actual_multiplier / Decimal('100')) if not skip_cashback else Decimal('0.0'),
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