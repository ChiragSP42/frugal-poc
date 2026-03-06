import json
import boto3
import datetime
import plaid
import os
from plaid.api import plaid_api
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

# --- 1. CONFIGURATION ---
# In a production environment, store these in AWS Systems Manager or Environment Variables
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
RECOMMENDATION_ENGINE_LAMBDA_NAME = os.getenv("RECOMMENDATION_ENGINE_LAMBDA_NAME") # Update to your actual Lambda name

# Initialize AWS Lambda Client
lambda_client = boto3.client('lambda', region_name='us-east-1')

# Initialize Plaid Client
configuration = plaid.Configuration(
    host="https://sandbox.plaid.com",
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

def lambda_handler(event, context):
    """
    Expected Event Payload:
    {
        "user_id": "12345",
        "access_token": "access-sandbox-xxxx-xxxx",
        "start_date": "2025-01-01",  # Optional: defaults to 30 days ago
        "end_date": "2025-02-01",    # Optional: defaults to today
        "user_cards": [...]          # The user's active cards from DB
    }
    """
    try:
        user_id = event.get('user_id')
        access_token = event.get('access_token')
        user_cards = event.get('user_cards', [])
        
        if not user_id or not access_token:
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
            "user_id": user_id,
            "user_cards": user_cards,
            "transactions": transactions_data
        }

        # Call the second Lambda synchronously (RequestResponse) so we can see the result
        invoke_response = lambda_client.invoke(
            FunctionName=RECOMMENDATION_ENGINE_LAMBDA_NAME,
            InvocationType='RequestResponse', 
            Payload=json.dumps(payload, default=str) # default=str safely handles nested datetime objects
        )

        # Read the response from the engine
        engine_response = json.loads(invoke_response['Payload'].read().decode('utf-8'))

        return {
            "statusCode": 200,
            "body": {
                "message": "Plaid Sync and ML Processing Complete",
                "plaid_transactions_pulled": len(transactions_data),
                "engine_response": engine_response
            }
        }

    except plaid.ApiException as e:
        error_msg = json.loads(e.body)['error_message'] if e.body else str(e)
        print(f"Plaid API ERROR: {error_msg}")
        return {"statusCode": 500, "body": f"Plaid Error: {error_msg}"}
        
    except Exception as e:
        print(f"System ERROR: {str(e)}")
        return {"statusCode": 500, "body": str(e)}