from sentence_transformers import SentenceTransformer
from typing import (
    List,
    Dict,
    Any
)
import json
import boto3
import os
import numpy as np
from decimal import Decimal

model = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", 
                            trust_remote_code=True,
                            model_kwargs={'default_task': 'retrieval', 
                                          "attn_implementation": "flash_attention_2", 
                                          "device_map": "auto"},
                            tokenizer_kwargs={"padding_side": "left"})

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

    unknown_embedding = model.encode([unknown])
    best_cards = []
    # Find cards with same category and store their category and score
    for card in user_cards:
        if 'spendBonusCategory' in card and len(card.get('spendBonusCategory', [])):
            card_categories = [category["spendBonusCategoryName"] for category in card.get('spendBonusCategory', [])]
            card_embeddings = model.encode(card_categories)
            sims = model.similarity(unknown_embedding, card_embeddings)
            print(f"Card: {card['cardMask']}\nStoring: {sims.max().item()}\nScores:\n{sims}\n{card_categories}")
            print("\x1b[31m*\x1b[0m" * 40)
            best_cards.append({
                "card": card,
                "category_idx": np.argmax(sims),
                "score": sims.max().item()
                })

    # print(json.dumps(card_scores, indent=2))
    # Compare cashbacks (take into account limits)
    best_cashback = 0
    best_card = {}
    for best in best_cards:
        cashback = best['card']['spendBonusCategory'][best['category_idx']]['earnMultiplier']
        # TODO: Implement consideration of spending limits to determine best card
        if cashback > best_cashback:
            best_card = {
                "card": best['card'],
                "category_idx": best['category_idx'],
                "score": best['score']
                }
            best_cashback = cashback

    print(f"Best card: {best_card['card']['cardMask']}")   
    return best_card


def fetch_user_cards(user_id):
    """Function to fetch user cards from DynamoDB for particulare userID

    Args:
        user_id (_type_): user ID to retrieve card information
    """
    card_list = []
    for i in range(1, 6):
        with open(f'user_cards/card_{i}.json', 'r') as f:
            card_list.append(json.load(f))

    return card_list

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
    
    # In reality, you'd fetch the user's linked cards from DynamoDB here
    print("\x1b[31mFetching user cards\x1b[0m")
    user_cards = fetch_user_cards(user_id)
    print("\x1b[32mFetched\x1b[0m")
    
    # ---------------------------------------------------------
    # ROUTE A: REAL-TIME GEOFENCE TRIGGER (From ALS)
    # ---------------------------------------------------------
    if action == "ALS_RECOMMEND":
        als_data = event.get('als_data', {})
        results = als_data.get("Results", [])
        
        if not results:
            return {"statusCode": 400, "body": "No ALS data provided."}
            
        title = results[0]["Title"]
        raw_category = results[0]["Categories"][0]["Name"]
        als_best_card(user_cards=user_cards, unknown_category=raw_category, unknown_title=title)


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
        "userId": "af23ef3",
        "transactions": [],
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
    lambda_handler(event=event, context=None)