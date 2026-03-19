import os
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
load_dotenv(override=True)

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
USER_CARDS_TABLE_NAME = os.getenv("USER_CARDS_TABLE_NAME")

session = boto3.Session(aws_access_key_id=AWS_ACCESS_KEY,
                        aws_secret_access_key=AWS_SECRET_KEY,
                        region_name='us-east-1')

dynamodb = session.resource('dynamodb')
table = dynamodb.Table(USER_CARDS_TABLE_NAME) #type: ignore

response = table.query(KeyConditionExpression=Key('userId').eq('Chirag'))

print(response)

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
