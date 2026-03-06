import json
import boto3
import os
import numpy as np
from decimal import Decimal

# Environment variables
TRANSACTIONS_TABLE = os.getenv("TRANSACTIONS_TABLE")

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
# Assuming a single-table design as discussed
table = dynamodb.Table(TRANSACTIONS_TABLE) #type: ignore
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')

# --- 1. THE UNIVERSAL TRANSLATOR DICTIONARIES ---
ALS_TO_POC_CATEGORY = {
    "Coffee Shop": "Dining", 
    "Restaurant": "Dining", 
    "Fast Food": "Dining",
    "Grocery Store": "Groceries", 
    "Supermarket": "Groceries",
    "Airport": "Travel", 
    "Hotel": "Travel",
    "Department Store": "Retail", 
    "Electronics Store": "Retail"
}

PLAID_TO_POC_CATEGORY = {
    "FOOD_AND_DRINK_COFFEE_SHOP": "Dining", 
    "FOOD_AND_DRINK_RESTAURANT": "Dining",
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "TRAVEL_AND_TRANSPORTATION_FLIGHTS": "Travel",
    "ENTERTAINMENT_SUBSCRIPTIONS": "Digital Entertainment",
    "GENERAL_MERCHANDISE_SUPERSTORES": "Retail"
}

# Initialize Bedrock Client
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')

# Pre-computed vectors for your 5 POC Categories
# Note: By storing them as numpy arrays upfront, the math later is much faster.
POC_EMBEDDINGS = {
    "Dining": np.array([0.012, -0.045, 0.112]),       
    "Groceries": np.array([0.104, 0.021, -0.055]),
    "Retail": np.array([0.332, 0.111, 0.001]),
    "Travel": np.array([-0.551, 0.882, 0.102]),
    "Digital Entertainment": np.array([0.002, -0.004, 0.505])
}

def get_bedrock_fallback(unknown_category_string):
    """
    Calls Amazon Bedrock for semantic understanding and uses Numpy for similarity matching.
    """
    print(f"Triggering AWS Bedrock ML Fallback for: {unknown_category_string}")
    
    try:
        # 1. Ask Bedrock to turn the text into a vector
        body = json.dumps({"inputText": unknown_category_string})
        response = bedrock_client.invoke_model(
            body=body,
            modelId='amazon.titan-embed-text-v1',
            accept='application/json',
            contentType='application/json'
        )
        response_body = json.loads(response.get('body').read())
        
        # Convert the returned list into a numpy array
        unknown_vector = np.array(response_body.get('embedding'))
        
        # 2. Compare it against our 5 project buckets using Numpy
        best_match = "Retail"
        highest_score = 0.0
        
        for poc_category, poc_vector in POC_EMBEDDINGS.items():
            # Numpy Cosine Similarity (1-liner)
            score = np.dot(unknown_vector, poc_vector) / (np.linalg.norm(unknown_vector) * np.linalg.norm(poc_vector))
            
            if score > highest_score:
                highest_score = score
                best_match = poc_category
                
        # 3. Confidence Threshold
        if highest_score > 0.70:
            print(f"Bedrock matched '{unknown_category_string}' to '{best_match}' with score {highest_score:.2f}")
            return best_match
            
        return "Retail" # Safety net
        
    except Exception as e:
        print(f"Bedrock API failed: {e}")
        return "Retail"

# --- 2. CORE LOGIC ---
def get_universal_category(raw_category, source):
    """Normalizes the category regardless of where it came from."""
    if source == "ALS":
        return ALS_TO_POC_CATEGORY.get(raw_category, "Retail")
    elif source == "PLAID":
        return PLAID_TO_POC_CATEGORY.get(raw_category, "Retail")
    return "Retail"

def calculate_best_card(universal_category, user_cards):
    """
    Finds the best card for a given category.
    user_cards is a list of card objects retrieved from DynamoDB.
    """
    best_card = None
    best_rate = Decimal('0.0')

    for card in user_cards:
        # Get base rate (default fallback)
        current_rate = Decimal(str(card.get('baseSpendEarnCashValue', 0.01)))
        
        # Check for category-specific bonuses
        for bonus in card.get('spendBonusCategory', []):
            if bonus['spendBonusCategoryName'] == universal_category:
                # Calculate effective rate (Multiplier * Point Value)
                multiplier = Decimal(str(bonus['earnMultiplier']))
                point_value = Decimal(str(card.get('baseSpendEarnCashValue', 0.01)))
                current_rate = multiplier * point_value
                break
                
        if current_rate > best_rate:
            best_rate = current_rate
            best_card = card
            
    return best_card, best_rate

def get_actual_rate(used_account_id, universal_category, user_cards):
    """Finds what rate the user ACTUALLY got based on the card they used."""
    used_card = next((c for c in user_cards if c['account_id'] == used_account_id), None)
    if not used_card:
        return Decimal('0.01') # Default if card not found
    
    _, actual_rate = calculate_best_card(universal_category, [used_card])
    return actual_rate


# --- 3. THE HANDLER ---
def lambda_handler(event, context):
    action = event.get('action')
    user_id = event.get('user_id')
    
    # In reality, you'd fetch the user's linked cards from DynamoDB here
    # user_cards = fetch_user_cards_from_db(user_id)
    user_cards = event.get('user_cards', []) 
    
    # ---------------------------------------------------------
    # ROUTE A: REAL-TIME GEOFENCE TRIGGER (From ALS)
    # ---------------------------------------------------------
    if action == "ALS_RECOMMEND":
        als_data = event.get('als_data', {})
        results = als_data.get("Results", [])
        
        if not results:
            return {"statusCode": 400, "body": "No ALS data provided."}
            
        merchant_name = results[0]["Title"]
        raw_category = results[0]["Categories"][0]["Name"]
        
        univ_category = get_universal_category(raw_category, "ALS")

        is_known_als = raw_category in ALS_TO_POC_CATEGORY

        if is_known_als:
            # FAST PATH: Dictionary Lookup (0.01ms)
            univ_category = get_universal_category(raw_category, "ALS")
        else:
            # SMART PATH: Bedrock Semantic Fallback (150ms)
            univ_category = get_bedrock_fallback(raw_category)

        best_card, rate = calculate_best_card(univ_category, user_cards)
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "merchant": merchant_name,
                "category": univ_category,
                "recommended_card": best_card['cardName'] if best_card else "None",
                "cashback_rate": float(rate)
            })
        }

    # ---------------------------------------------------------
    # ROUTE B: HISTORICAL PLAID SYNC (Analytics & Missed Savings)
    # ---------------------------------------------------------
    elif action == "PLAID_SYNC":
        transactions = event.get('transactions', [])
        processed_txns = []
        
        with table.batch_writer() as batch:
            for txn in transactions:
                # 1. Extract Plaid details
                amount = Decimal(str(txn['amount']))
                raw_category = txn['personal_finance_category']['detailed']
                used_account_id = txn['account_id']
                
                # 2. Normalize
                is_known_plaid = raw_category in PLAID_TO_POC_CATEGORY
                if is_known_plaid:
                    # FAST PATH: Dictionary Lookup (0.01ms)
                    univ_category = get_universal_category(raw_category, "ALS")
                else:
                    # SMART PATH: Bedrock Semantic Fallback (150ms)
                    univ_category = get_bedrock_fallback(raw_category)
                univ_category = get_universal_category(raw_category, "PLAID")
                
                # 3. Calculate Actual vs Optimal
                actual_rate = get_actual_rate(used_account_id, univ_category, user_cards)
                best_card, optimal_rate = calculate_best_card(univ_category, user_cards)
                
                # 4. Calculate Missed Rewards math using formula: Amount * (Optimal - Actual)
                missed_savings = amount * (optimal_rate - actual_rate)
                if missed_savings < 0: 
                    missed_savings = Decimal('0.0') # Prevent negative missed savings
                
                # 5. Build DynamoDB Item
                item = {
                    "PK": f"USER#{user_id}",
                    "SK": f"TXN#{txn['date']}#{txn['transaction_id']}",
                    "Merchant": txn['merchant_name'],
                    "Amount": amount,
                    "Category": univ_category,
                    "UsedAccountId": used_account_id,
                    "ActualCashbackEarned": amount * actual_rate,
                    "OptimalCardName": best_card['cardName'] if best_card else "None",
                    "MissedSavings": missed_savings
                }
                
                # Save to DB
                batch.put_item(Item=item)
                processed_txns.append(item)
                
        return {
            "statusCode": 200,
            "body": json.dumps(f"Successfully processed and stored {len(processed_txns)} transactions.")
        }