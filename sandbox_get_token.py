import os
import webbrowser
import threading
import time
from flask import Flask, render_template_string, request, jsonify
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

# --- HARDCODED SANDBOX CREDENTIALS ---
# (These are standard public sandbox keys if they don't have their own, 
# but ideally, ask them to paste their SANDBOX secret below)
PLAID_CLIENT_ID = "698b5a682896dd0021e1f4fe"
# PLAID_SECRET = "fe85d21e91c9be18c32048c148b1c7" # SANDBOX SECRET
PLAID_SECRET = "3b35fe064ccc3108200fc8fe15ecfe" # PRODUCTION SECRET
# ^^^ REMIND THEM TO USE THE SANDBOX SECRET, NOT PRODUCTION

# Configuration
configuration = plaid.Configuration(
    host="https://production.plaid.com",
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Frugal Data Connector (SANDBOX)</title>
    <style>body { font-family: sans-serif; text-align: center; padding: 50px; background-color: #f0f8ff; }</style>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
</head>
<body>
    <h1>Step 2: Connect Test Account</h1>
    <p><strong>MODE: SANDBOX</strong><br>Use Username: <code>user_good</code> | Password: <code>pass_good</code></p>
    <button id="link-button" style="padding: 15px 30px; font-size: 16px; cursor: pointer; background-color: #007bff; color: white; border: none; border-radius: 5px;">Connect Test Bank</button>
    <h3 id="status" style="color: blue; display: none;">Processing... Please wait.</h3>
    <h3 id="success" style="color: green; display: none;">SUCCESS! Token saved. You can close this window.</h3>

    <script>
    document.getElementById('link-button').onclick = async function() {
        const response = await fetch('/create_link_token', { method: 'POST' });
        const data = await response.json();
        
        if (data.error) {
            alert("Error: " + data.error);
            return;
        }

        const linkToken = data.link_token;

        const handler = Plaid.create({
            token: linkToken,
            onSuccess: async (public_token, metadata) => {
                document.getElementById('status').style.display = 'block';
                document.getElementById('link-button').style.display = 'none';
                
                await fetch('/save_access_token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ public_token: public_token })
                });
                
                document.getElementById('status').style.display = 'none';
                document.getElementById('success').style.display = 'block';
            },
        });
        handler.open();
    };
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/create_link_token', methods=['POST'])
def create_link_token():
    try:
        request = LinkTokenCreateRequest(
            products=[Products('transactions')],
            client_name="Frugal Sandbox Tool",
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(client_user_id='sandbox_user_id')
        )
        response = client.link_token_create(request)
        return jsonify(response.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/save_access_token', methods=['POST'])
def save_access_token():
    public_token = request.json['public_token']
    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    exchange_response = client.item_public_token_exchange(exchange_request)
    access_token = exchange_response['access_token']

    with open("FRUGAL_ACCESS_TOKEN.txt", "w") as f:
        f.write(access_token)
    
    return jsonify({'status': 'saved'})

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(port=5000)