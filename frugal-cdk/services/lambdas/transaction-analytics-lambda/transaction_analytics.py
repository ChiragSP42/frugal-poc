from typing import List, Dict
import json
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
import datetime
import plaid
import base64
import os
from plaid.api import plaid_api
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
load_dotenv(override=True)

# --- 1. CONFIGURATION ---
# In a production environment, store these in AWS Systems Manager or Environment Variables
MAIN_TABLE_NAME = os.getenv("MAIN_TABLE_NAME")
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
# ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
RECOMMENDATION_ENGINE_LAMBDA_NAME = os.getenv("RECOMMENDATION_ENGINE_LAMBDA_NAME") # Update to your actual Lambda name

# Initialize AWS Lambda Client
lambda_client = boto3.client('lambda', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb')
main_table = dynamodb.Table(MAIN_TABLE_NAME) #type: ignore

# Initialize Plaid Client
configuration = plaid.Configuration(
    host="https://production.plaid.com",
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

def lambda_handler(event, context):
    """
    Expected Event Payload:
    {
        "userId": "Chirag",
        "start_date": "2025-01-01",  # Optional: defaults to 30 days ago
        "end_date": "2025-02-01",    # Optional: defaults to today
    }
    """
    try:
        user_id = event.get('userId')
        access_tokens = gather_access_tokens(user_id=user_id)
        
        if not user_id or not access_tokens:
            return {"statusCode": 400, "body": "Missing user_id or access_token"}

        # --- 2. PARSE DATES (K.I.S.S.) ---
        # If dates are passed in the event, use them. Otherwise, default to the last 30 days.
        if 'start_date' in event and 'end_date' in event:
            start_date = datetime.datetime.strptime(event['start_date'], "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(event['end_date'], "%Y-%m-%d").date()
        else:
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=30)

        print(f"Fetching transactions for User {user_id} from {start_date} to {end_date}...")

        try:
            for access_token in access_tokens:
                # --- 3. FETCH FROM PLAID ---
                request = TransactionsGetRequest(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                    options=TransactionsGetRequestOptions(
                        include_personal_finance_category=True 
                    )
                )
                response = plaid_client.transactions_get(request)
                
                # Convert the Plaid response objects to standard Python dictionaries for JSON serialization
                transactions_data = response.to_dict()['transactions']
                
                print(f"Successfully pulled {len(transactions_data)} transactions from Plaid.")

                # --- 4. INVOKE THE RECOMMENDATION ENGINE LAMBDA ---
                # We package the exact payload your engine expects for the "PLAID_SYNC" route
                payload = {
                    "action": "PLAID_SYNC",
                    "userId": user_id,
                    "transactions": transactions_data
                }

                # Call the second Lambda synchronously (RequestResponse) so we can see the result
                invoke_response = lambda_client.invoke(
                    FunctionName=RECOMMENDATION_ENGINE_LAMBDA_NAME,
                    InvocationType='RequestResponse', 
                    Payload=json.dumps(payload, default=str) # default=str safely handles nested datetime objects
                )
        except Exception as e:
            return {
                "statusCode": 400,
                "body": {
                    "message": f"{e}"
                }
            }
        finally:
            return {
                "statusCode": 200,
                "body": {
                    "message": "Plaid Sync and ML Processing Complete"
                }
            }

    except plaid.ApiException as e:
        error_msg = json.loads(e.body)['error_message'] if e.body else str(e)
        print(f"Plaid API ERROR: {error_msg}")
        return {"statusCode": 500, "body": f"Plaid Error: {error_msg}"}
        
    except Exception as e:
        print(f"System ERROR: {str(e)}")
        return {"statusCode": 500, "body": str(e)}

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

if __name__ == "__main__":
    event = {
        "userId": "Chirag",
        "start_date": "2024-01-01",  # Optional: defaults to 30 days ago
        "end_date": "2026-01-01",    # Optional: defaults to today
    }
    print("Running transaction analytics script")
    print(lambda_handler(event=event, context=None))