#%%
import os
import base64
from typing import List, Dict
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

# Testing fetching cards functionality
# cards = fetch_user_cards(user_id='84085468-f091-7071-ff5a-c60fcf8c6ba9')
# print(json.dumps(cards[0], default=str, indent=2))

# Testing fetching ACCESS TOKENS functionality
access_tokens = gather_access_tokens(user_id='84085468-f091-7071-ff5a-c60fcf8c6ba9')
print(access_tokens)

#%%
# Script to retrieve card information from Plaid (not that useful)
"""
Sample output:

{'account_id': 'a92of283gvq08H08Hha245ng1u944fh0g',
 'balances': {'available': 2089.32,
              'current': 91.68,
              'iso_currency_code': 'USD',
              'limit': 2100.0,
              'unofficial_currency_code': None},
 'mask': '1234',
 'name': 'Costco Anywhere Visa® Card by Citi',
 'official_name': 'Costco Anywhere Visa® Card by Citi',
 'subtype': 'credit card',
 'type': 'credit'}
"""
import plaid
import os
import json
from dotenv import load_dotenv
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
load_dotenv(override=True)

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")


configuration = plaid.Configuration(
    host="https://production.plaid.com",
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

response = plaid_client.accounts_get(AccountsGetRequest(access_token=ACCESS_TOKEN))
accounts = response['accounts']

for a in accounts:
    print(a)

# Filter only credit cards
# credit_cards = [a for a in accounts if a['type'] == 'credit' and a['subtype'] == 'credit card']

# for card in credit_cards:
#     print(card['account_id'], card['name'], card['mask'])

# %%
