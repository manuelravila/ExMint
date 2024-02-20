#app.py
from flask import Flask, jsonify, request, session, redirect, url_for
import plaid
import json
import csv
import requests

from datetime import datetime
from plaid.api import plaid_api
from plaid.model.item_remove_request import ItemRemoveRequest
from datetime import date
from config import Config
from models import db, User, Credential, Account, PlaidTransaction
from forms import RegistrationForm, LoginForm
from views import index, register, views
from flask import Response
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from io import StringIO

# Initialize Flask app
app = Flask(__name__)
app.register_blueprint(views)

# Initialize Plaid client with environment from config
plaid_environment = Config.get_plaid_environment()
configuration = plaid.Configuration(
    host=plaid_environment,
    api_key={
        'clientId': Config.PLAID_CLIENT_ID,
        'secret': Config.PLAID_SECRET,
    }
)

api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

# Initialize Flask Applications
app.config.from_object(Config)
db.init_app(app)
migrate = Migrate(app, db)
flask_bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.route('/create_link_token', methods=['POST'])
def create_link_token():
    data = request.json
    user_id = data.get('user_id')  # Assuming you pass the user_id
    access_token = data.get('access_token', None)  # This could be None for new connections

    # Ensure the user is authenticated and authorized
    # This part depends on your application's authentication logic

    link_token_request = {
        'user': {
            'client_user_id': str(user_id),  # Use the authenticated user's ID
        },
        'client_name': "ExMint",
        'products': ["transactions"],
        'country_codes': ['CA'],
        'language': 'en',
    }

    if access_token:
        # If an access_token is provided, we're updating an existing connection
        link_token_request['access_token'] = access_token

    try:
        response = client.link_token_create(link_token_request)
        return jsonify(response.to_dict())
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})

@app.route('/get_access_token', methods=['POST'])
def handle_token_and_accounts():
    data = request.json
    public_token = data.get('public_token')
    institution_name = data.get('institution_name', 'Unknown')
    is_refresh = data.get('is_refresh', False)
    credential_id = data.get('credential_id', None)

    # Check if a user is logged in
    if not current_user.is_authenticated:
        return jsonify({'error': 'User not authenticated'}), 401

    try:
        if not is_refresh:
            # Exchange public token for access token (initial connection)
            exchange_response = client.item_public_token_exchange({
                'public_token': public_token
            })
            access_token = exchange_response['access_token']
            print('New Access Token: ', access_token)

            # Encrypt and store access token in Credential
            credential = Credential(
                user_id=current_user.id, 
                access_token=access_token,
                institution_name=institution_name,
                requires_update=False  # Assuming initial connection does not require update
            )
            db.session.add(credential)
            db.session.flush()
            credential_id = credential.id

            operation = 'token creation'
        else:
            # For refresh, assume access_token is provided and decrypted
            access_token = data['access_token']
            credential = Credential.query.get(credential_id)
            operation = 'Institution Refresh'
            credential.requires_update = False  # Reset requires_update flag

        # Fetch and update accounts
        accounts_response = client.accounts_get({'access_token': access_token})
        refresh_accounts(credential_id, accounts_response['accounts'])

        # Log PlaidTransaction
        plaid_transaction = PlaidTransaction(
            user_id=current_user.id,
            user_ip=request.remote_addr,
            credential_id=credential_id,
            operation=operation,
            response=str(accounts_response)
        )
        db.session.add(plaid_transaction)
        db.session.commit()

        return jsonify({'status': 'success', 'message': f'{operation} successful'})

    except plaid.ApiException as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

def refresh_accounts(credential_id, accounts_data):
    existing_accounts = Account.query.filter_by(credential_id=credential_id).all()
    existing_account_ids = {account.plaid_account_id for account in existing_accounts}

    for account in accounts_data:
        if account['account_id'] in existing_account_ids:
            # Update existing account details here if needed
            pass
        else:
            # Add new account
            new_account = Account(
                credential_id=credential_id,
                plaid_account_id=account['account_id'],
                name=account['name'],
                type=account['type'],
                subtype=account['subtype'],
                mask=account.get('mask', '')
            )
            db.session.add(new_account)

    # Optionally, deactivate accounts not in the latest fetch
    for existing_account in existing_accounts:
        if existing_account.plaid_account_id not in {account['account_id'] for account in accounts_data}:
            # Deactivate account
            existing_account.status = 'Inactive'  # Assuming there's a status field to update

@app.route('/transactions', methods=['POST'])
def get_transactions():
    print("Request received at /transactions")
    #print(request.headers)  # see all incoming headers


    # Retrieve user_token from headers
    user_token = request.headers.get('x-user-token')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Validate user_token and date parameters
    if not user_token:
        return jsonify({'error': 'Missing user token'}), 401
    if not start_date or not end_date:
        return jsonify({'error': 'Missing start date or end date'}), 400

    # Assuming the payload returned from verify_auth_token contains the user's ID
    user_id = User.verify_auth_token(user_token)
    print(f"Token Verification Result: User ID = {user_id}")
    
    if user_id is None:
        return jsonify({'error': 'Invalid or expired user token'}), 401

    # Retrieve the user from the database using the user ID
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Convert dates from string to date objects
    try:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

    # Aggregate transactions from all credentials
    all_transactions = []
    for credential in user.credentials:
        try:
            # Fetch transactions using each Plaid access token
            response = client.transactions_get({
                'access_token': credential.access_token,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            })

            transactions = response.to_dict()['transactions']
            all_transactions.extend(transactions)
        
        except plaid.ApiException as e:
            print("Error fetching transactions:", str(e))
        except Exception as e:
            print("General error during transaction fetching:", str(e))

    # Convert JSON to CSV
    csv_data = json_csv(all_transactions)

    # Create a response with the CSV data
    return Response(csv_data, mimetype='text/csv', headers={"Content-disposition": "attachment; filename=transactions.csv"})

@app.route('/sync', methods=['GET'])
def sync_transactions():
    print("Request received at /sync")

    # Retrieve user_token from headers
    user_token = request.headers.get('x-user-token')

    # Validate user_token
    if not user_token:
        return jsonify({'error': 'Missing user token'}), 401

    # Verify user token
    user_id = User.verify_auth_token(user_token)
    if user_id is None:
        return jsonify({'error': 'Invalid or expired user token'}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Initialize an empty list to store all transactions
    all_transactions_csv = []
    api_call_count = 0  # Initialize API call counter

    added_transactions = []
    modified_transactions = []
    removed_transactions = []

    # Fetch transactions from all credentials
    for credential in user.credentials:
            for account in credential.accounts:
                if account.status == 'Active' and account.is_enabled:
                    cursor = None
                    has_more = True
                    while has_more:
                        try:
                            sync_request_payload = {'access_token': credential.access_token}
                            if cursor:
                                sync_request_payload['cursor'] = cursor

                            response = client.transactions_sync(sync_request_payload)
                            api_call_count += 1
                            print(f"API call {api_call_count} made.")

                            data = response.to_dict()

                            for action in ['added', 'modified', 'removed']:
                                transactions = data.get(action, [])
                                if action == 'added':
                                    added_transactions.extend(filter_transactions(transactions, account.plaid_account_id))
                                elif action == 'modified':
                                    modified_transactions.extend(filter_transactions(transactions, account.plaid_account_id))
                                elif action == 'removed':
                                    removed_transactions.extend(filter_transactions(transactions, account.plaid_account_id))

                            cursor = data.get('next_cursor')
                            has_more = data.get('has_more', False)
                            
                        except plaid.ApiException as e:
                            error_response = json.loads(e.body)
                            if error_response.get('error_code') == 'ITEM_LOGIN_REQUIRED':
                                credential.requires_update = True
                                db.session.commit()
                            print("Error fetching transactions:", str(e))
                            error_csv = "error_code,error_message,error_type,request_id,suggested_action\n"
                            error_csv += f"{error_response['error_code']},{error_response['error_message']},{error_response['error_type']},{error_response['request_id']},'null'"
                            return Response(error_csv, mimetype='text/csv', headers={"Content-disposition": "attachment; filename=error.csv"})

                        except Exception as e:
                            print("General error during transaction fetching:", str(e))
                            break

    # Combine all transactions and convert to CSV
    csv_header = ['Date', 'Name', 'Amount', 'Currency', 'Category', 'Merchant Name', 'Account ID', 'Transaction ID', 'Payment Channel', 'Action', 'Pending']
    all_transactions_csv = [",".join(csv_header)]
    all_transactions_csv.append(json_csv(added_transactions, 'added'))
    all_transactions_csv.append(json_csv(modified_transactions, 'modified'))
    all_transactions_csv.append(json_csv(removed_transactions, 'removed'))

    # Create a response with the CSV data
    return Response("\n".join(all_transactions_csv), mimetype='text/csv', headers={"Content-disposition": "attachment; filename=transactions.csv"})

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    user_id = current_user.id
    bank_id = request.args.get('bank_id')

    query = Account.query.join(Credential).filter(Credential.user_id == user_id, Credential.status == 'Active')

    if bank_id:
        query = query.filter(Credential.id == bank_id)

    accounts = query.filter(Account.status == 'Active').all()  # Assuming 'Account' has a 'status' field

    accounts_data = [{'id': account.id, 'name': account.name, 'mask': account.mask, 
                      'type': account.type, 'subtype': account.subtype, 'is_enabled': account.is_enabled} for account in accounts]

    return jsonify(accounts=accounts_data)

@app.route('/api/banks', methods=['GET'])
@login_required
def get_banks():
    token = request.args.get('token')
    if token:
        user = User.verify_auth_token(token)
        if not user or user != current_user:
            return jsonify({'message': 'Invalid or missing token'}), 401
    else:
        user = current_user

    # Filter to get only active banks
    banks = Credential.query.filter_by(user_id=user.id, status='Active').all()
    banks_data = [
        {
            'id': bank.id,
            'institution_name': bank.institution_name,
            'requires_update': bank.requires_update  # Include requires_update field
        } for bank in banks
    ]
    return jsonify(banks=banks_data)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def json_csv(transactions, action):
    si = StringIO()
    cw = csv.writer(si)

    for item in transactions:
        row = [
            item.get("date", ""),
            item.get("name", ""),
            item.get("amount", ""),
            item.get("iso_currency_code", ""),
            ", ".join(item.get("category", [])),
            item.get("merchant_name", ""),
            item.get("account_id", ""),
            item.get("transaction_id", ""),
            item.get("payment_channel", ""),
            action,
            item.get("pending", "")
        ]
        cw.writerow(row)

    return si.getvalue()

def filter_transactions(transactions, account_plaid_id):
    # Filter transactions to only include those for the specific account_plaid_id
    return [transaction for transaction in transactions if transaction['account_id'] == account_plaid_id]

def deactivate_plaid_token(access_token):
    try:
        # Create the request object for item removal
        print('Access Token to Remove: ', access_token)
        request = ItemRemoveRequest(access_token=access_token)
        # Use the Plaid client to remove the item
        response = client.item_remove(request)
        
        print("Plaid response:", response)
        return True, response.to_dict()
    except plaid.ApiException as e:
        print("An error occurred while removing the item from Plaid:", e)
        return False, e.body


# Endpoint to remove a bank
@app.route('/api/remove_bank/<int:bank_id>', methods=['DELETE'])
@login_required
def remove_bank(bank_id):
    # Find the credential by ID
    credential = Credential.query.filter_by(id=bank_id, user_id=current_user.id).first()
    
    if credential:
        # Deactivate the token with Plaid
        success, plaid_response = deactivate_plaid_token(credential.access_token)
        
        if success:
            # Update the status of the credential
            credential.status = 'Revoked'

            # Optionally remove or update associated accounts
            for account in credential.accounts:
                account.status = 'Revoked'
            
            # Record the transaction
            transaction = PlaidTransaction(
                user_id=current_user.id,
                user_ip=request.remote_addr,
                credential_id=credential.id,
                operation='Access token and associated accounts revoked',
                response=str(plaid_response)  # Save the response from Plaid as a string
            )
            db.session.add(transaction)
            db.session.commit()
            session['connections_modal_open'] = True  # Set the flag in the session
            return jsonify({'success': True, 'message': 'Bank connection removed'}), 200
        else:
            # Handle the failure case
            app.logger.error(f"Failed to deactivate token: {plaid_response}")
            #return jsonify({'message': 'Failed to remove bank connection', 'error': plaid_response}), 400
            session['modal_open'] = True  # Set session variable
            return jsonify({'success': False, 'message': 'Failed to remove bank connection', 'error': plaid_response}), 400
    else:
        return jsonify({'success': False, 'message': 'Credential not found'}), 404

@app.route('/api/get_access_token/<int:credential_id>', methods=['GET'])
@login_required
def get_access_token_for_bank(credential_id):
    credential = Credential.query.filter_by(id=credential_id, user_id=current_user.id).first()

    if not credential:
        return jsonify({'error': 'Credential not found or does not belong to the current user'}), 404

    # Assuming the access_token is stored encrypted and needs to be decrypted
    try:
        access_token = credential.access_token  # Access the decrypted token

        return jsonify({'access_token': access_token})
    except Exception as e:
        return jsonify({'error': 'Failed to retrieve access token', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
    
