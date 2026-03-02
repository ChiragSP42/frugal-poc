import json
import datetime
from plaid.api import plaid_api
import plaid
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

# --- CONFIGURATION (SANDBOX) ---
PLAID_CLIENT_ID = "698b5a682896dd0021e1f4fe"
PLAID_SECRET = "fe85d21e91c9be18c32048c148b1c7" 

# Setup Plaid Client
configuration = plaid.Configuration(
    host="https://sandbox.plaid.com",
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

def get_transactions():
    # 1. Read the Access Token you just generated
    try:
        with open("FRUGAL_ACCESS_TOKEN.txt", "r") as f:
            access_token = f.read().strip()
    except FileNotFoundError:
        print("ERROR: Could not find 'FRUGAL_ACCESS_TOKEN.txt'. Did you run the previous script?")
        return

    # 2. Define Date Range (Last 30 Days)
    start_date = (datetime.date.today() - datetime.timedelta(days=30))
    end_date = datetime.date.today()

    # 3. Request Transactions
    print(f"Fetching transactions from {start_date} to {end_date}...")
    
    try:
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(
                include_personal_finance_category=True # CRITICAL for your ML Engine
            )
        )
        response = client.transactions_get(request)
        
        # 4. Display the Data
        transactions = response['transactions']
        print(f"\nSuccessfully fetched {len(transactions)} transactions!\n")
        
        print(f"{'DATE':<12} | {'MERCHANT':<20} | {'CATEGORY':<30} | {'AMOUNT'}")
        print("-" * 85)
        
        for t in transactions:
            # Extract the detailed category for your ML engine
            category = "N/A"
            if t['personal_finance_category']:
                category = t['personal_finance_category']['primary'] + " -> " + t['personal_finance_category']['detailed'].split('_')[-1]
            
            print(f"{str(t['date']):<12} | {t['merchant_name'][:20]:<20} | {category[:30]:<30} | ${t['amount']}")

        # 5. Save Raw JSON for your analysis
        with open("plaid_transactions_dump.json", "w") as f:
            json.dump(response.to_dict(), f, default=str, indent=2)
        print("\n[INFO] Full raw data saved to 'plaid_transactions_dump.json'")

    except plaid.ApiException as e:
        print(f"\nAPI ERROR: {e}")

if __name__ == "__main__":
    get_transactions()