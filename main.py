#%%
import os
import base64
from typing import List
import json
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
load_dotenv(override=True)

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")

session = boto3.Session(aws_access_key_id=AWS_ACCESS_KEY,
                        aws_secret_access_key=AWS_SECRET_KEY,
                        region_name='us-east-1')

# Table Environment variables
USER_CARDS_TABLE_NAME = os.getenv("USER_CARDS_TABLE_NAME")
TXN_TABLE_NAME = os.getenv("TXN_TABLE_NAME")
REFERENCE_TABLE_NAME = os.getenv("REFERENCE_TABLE_NAME")
MAIN_TABLE_NAME = os.getenv("MAIN_TABLE_NAME")

# BOTO3 clients and resources
dynamodb = session.resource('dynamodb')
user_cards_table = dynamodb.Table(USER_CARDS_TABLE_NAME) #type: ignore
txn_table = dynamodb.Table(TXN_TABLE_NAME) #type: ignore
ref_table = dynamodb.Table(REFERENCE_TABLE_NAME) #type: ignore
main_table = dynamodb.Table(MAIN_TABLE_NAME) #type: ignore


# Testing fetching cards functionality
def fetch_user_cards(user_id):
    """Function to fetch user cards from DynamoDB for particular userID

    Args:
        user_id (str): user ID to retrieve card information
    """
    response = user_cards_table.query(KeyConditionExpression=Key('userId').eq(user_id))
    user_card_info = response.get("Items", [])

    cards = []

    print(len(user_card_info))
    for user_card in user_card_info:
        ref_card_id = str(user_card.get("referenceCardId"))
        if ref_card_id:
            response = ref_table.query(KeyConditionExpression=
                                    Key('PK').eq(ref_card_id)&
                                    Key('SK').eq("DETAILS"))
            ref_info = response.get("Items", [])[0]
            cards.append(user_card | ref_info)
        else:
            continue

    print(f"Number of cards: {len(cards)}")
    return cards

# Testing fetching ACCESS TOKENS functionality
def gather_access_tokens(user_id: str) -> List[str]:
    response = main_table.query(
    KeyConditionExpression=
        Key('PK').eq(f"USER#{user_id}") &
        Key('SK').begins_with("ACCOUNT#")
    )

    # 2. For each account, decrypt the access token
    access_tokens = []
    kms = boto3.client('kms')
    for account in response['Items']:
        decrypted = kms.decrypt(
            CiphertextBlob=base64.b64decode(account['encryptedAccessToken']),
            KeyId=account['kmsKeyId']
        )
        access_tokens.append(decrypted['Plaintext'].decode('utf-8'))
    
    return access_tokens


# --- Aggregate Rewards from Transaction Table ---
def aggregate_rewards(user_id: str):
    """Queries the Txn table for a specific userId and aggregates
    bestPossibleReward, actualReward, and missedReward.
    """
    total_amount = 0
    total_best = 0
    total_actual = 0
    total_missed = 0
    total_txns = 0

    # Query by userId partition key with pagination
    response = txn_table.query(KeyConditionExpression=Key('userId').eq(user_id))
    while True:
        items = response.get("Items", [])
        for item in items:
            total_amount += float(abs(item.get("amount", 0)))
            total_best += float(item.get("bestPossibleReward", 0))
            total_actual += float(item.get("actualReward", 0))
            total_missed += float(item.get("missedReward", 0))
            total_txns += 1

        # Check for pagination
        if "LastEvaluatedKey" in response:
            response = txn_table.query(
                KeyConditionExpression=Key('userId').eq(user_id),
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
        else:
            break

    print(f"User: {user_id}")
    print(f"Total Transactions: {total_txns}")
    print(f"Total Amount:               ${total_amount:.2f}")
    print(f"Total Best Possible Reward: ${total_best:.2f}")
    print(f"Total Actual Reward:        ${total_actual:.2f}")
    print(f"Total Missed Reward:        ${total_missed:.2f}")

    return {
        "userId": user_id,
        "totalTransactions": total_txns,
        "totalBestPossibleReward": total_best,
        "totalActualReward": total_actual,
        "totalMissedReward": total_missed,
    }


if __name__ == "__main__":
    results = aggregate_rewards(user_id="14b8b4e8-5031-707f-20c4-de554278c542")
    print(json.dumps(results, indent=2))
