#app.py
from flask import Flask, jsonify, request, session, redirect, url_for
from extensions import mail
import plaid
import json
import csv
#import requests
#import time
import re
import os

from datetime import datetime
#from datetime import date

from plaid.api import plaid_api
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

from config import Config
from models import db, User, Credential, Account, PlaidTransaction
#from forms import RegistrationForm, LoginForm
#from views import index, register, views
#from flask import Response
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from io import StringIO
from sqlalchemy import and_

# Initialize Extensions
migrate = Migrate()
flask_bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'login'

# Initialize Flask app
def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')
    mail.init_app(app)
    flask_bcrypt.init_app(app)
    login_manager.init_app(app)

    from views import views as views_blueprint
    app.register_blueprint(views_blueprint)

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

    # Initialize Flask Applications with the app context
    app.config.from_object(Config)
    db.init_app(app)
    migrate.init_app(app, db)

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
            
    @app.route('/handle_token_and_accounts', methods=['POST'])
    def handle_token_and_accounts():
        print('Backend code started correctly')
        data = request.json
        credential_id = data.get('credential_id')  # Assuming this is passed for refreshes
        public_token = data.get('public_token', None)  # For new connections
        is_refresh = data.get('is_refresh', False)

        if not current_user.is_authenticated:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            if is_refresh:
                print('Correctly receiver refresh flag')
                credential = Credential.query.get(credential_id)
                if not credential:
                    return jsonify({'error': 'Credential not found'}), 404
                access_token = credential.access_token
            else:
                # New connection: Exchange public token for access token
                public_token = data['public_token']
                institution_name = data.get('institution_name', 'Unknown')
                exchange_response = client.item_public_token_exchange(public_token=public_token)
                access_token = exchange_response['access_token']

                # Store new credential
                credential = Credential(
                    user_id=current_user.id,
                    access_token=access_token,
                    institution_name=institution_name,
                    requires_update=False
                )
                db.session.add(credential)
                db.session.commit()
                credential_id = credential.id  # Use this ID for new credentials

            # Fetch and update accounts
            accounts_request = AccountsGetRequest(access_token=access_token)
            accounts_response = client.accounts_get(accounts_request)
            
            # Assuming implementation of refresh_accounts updates or adds accounts as needed
            refresh_accounts(credential.id if is_refresh else credential_id, accounts_response.to_dict())

            # Log PlaidTransaction
            plaid_transaction = PlaidTransaction(
                user_id=current_user.id,
                user_ip=request.remote_addr,
                credential_id=credential.id,
                operation='Institution Refresh' if is_refresh else 'Token Creation',
                response=str(accounts_response)
            )
            db.session.add(plaid_transaction)

            credential.requires_update = False
            db.session.commit()

            return jsonify({'status': 'success', 'message': 'Operation successful'})
        
        except plaid.ApiException as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    def refresh_accounts(credential_id, accounts_data):
        # Assuming the rest of your function setup remains the same
        existing_accounts = Account.query.filter_by(credential_id=credential_id).all()
        existing_account_ids = {account.plaid_account_id for account in existing_accounts}

        # Adjusted loop to iterate over the list of accounts
        for account in accounts_data['accounts']:
            if account['account_id'] in existing_account_ids:
                # Update existing account details here if needed
                existing_account = next((acc for acc in existing_accounts if acc.plaid_account_id == account['account_id']), None)
                if existing_account:
                    existing_account.name = account['name']
                    existing_account.type = account['type']
                    existing_account.subtype = account['subtype']
                    existing_account.mask = account.get('mask', '')
                    # Ensure other necessary fields are updated similarly
            else:
                # Add new account
                new_account = Account(
                    credential_id=credential_id,
                    plaid_account_id=account['account_id'],
                    name=account['name'],
                    type=account['type'],
                    subtype=account['subtype'],
                    mask=account.get('mask', ''),
                    status='Active'
                    # Ensure other necessary fields are added similarly
                )
                db.session.add(new_account)
        # Optionally, deactivate accounts not in the latest fetch
        current_account_ids = {account['account_id'] for account in accounts_data['accounts']}
        for existing_account in existing_accounts:
            if existing_account.plaid_account_id not in current_account_ids:
                existing_account.status = 'Inactive'

        # Continue with the rest of your function as before
        db.session.commit()

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

        banks = []

        # Get the cursor data from the request headers and create a cursor dictionary
        cursors_data = request.headers.get('cursors', '')
        cursor_dict = {}

        # Process the cursors header data and create a valid cursor dictionary
        for pair in cursors_data.split(','):
            try:
                credential_id, cursor = pair.split(':')
                if credential_id.isdigit() and len(cursor) >= 10:
                    cursor_dict[int(credential_id)] = cursor
            except ValueError:
                pass  # Skip invalid pairs

        # Fetch banks and accounts
        active_credentials = Credential.query.filter_by(user_id=user.id, status='Active').all()

        for credential in active_credentials:
            print(f"Processing credential: {credential.id} - {credential.status}")
            accounts = []
            next_cursor = None
            credential_error = None

            # Get the cursor for the current credential
            cursor = cursor_dict.get(credential.id, None)

            transactions_by_account = {}
            has_more = True
            while has_more:
                try:
                    sync_request_payload = {
                        'access_token': credential.access_token, 
                        "count": 500
                    }

                    if cursor:
                        sync_request_payload['cursor'] = cursor
                        cursor = None  # Reset cursor after using it once

                    response = client.transactions_sync(sync_request_payload)
                    log_request_response(sync_request_payload, response)  

                    data = response.to_dict()

                    for action in ['added', 'modified', 'removed']:
                        for transaction in data.get(action, []):
                            account_id = transaction.get('account_id')
                            if account_id not in transactions_by_account:
                                transactions_by_account[account_id] = []

                            transactions_by_account[account_id].append({
                                'date': transaction.get('date'),
                                'name': transaction.get('name'),
                                'amount': transaction.get('amount'),
                                'iso_currency_code': transaction.get('iso_currency_code'),
                                'category': transaction.get('category', []),
                                'merchant_name': transaction.get('merchant_name'),
                                'account_id': account_id,
                                'transaction_id': transaction.get('transaction_id'),
                                'payment_channel': transaction.get('payment_channel'),
                                'action': action,
                                'pending': transaction.get('pending')
                            })

                    cursor = data.get('next_cursor')
                    has_more = data.get('has_more', False)
                    next_cursor = cursor

                except plaid.ApiException as e:
                    error_response = json.loads(e.body)
                    if error_response.get('error_code') == 'ITEM_LOGIN_REQUIRED':
                        credential.requires_update = True
                        db.session.commit()
                        credential_error = {
                            'error_code': error_response['error_code'],
                            'error_message': error_response['error_message']
                        }
                        break  # Move to the next credential
                    else:
                        print("Error fetching transactions:", str(e))


                except Exception as e:
                    print("General error during transaction fetching:", str(e))
                    break

            active_accounts = Account.query.filter(
                and_(Account.credential_id == credential.id, Account.status == 'Active', Account.is_enabled == True)
            ).all()

            for account in active_accounts:
                # Get account balance
                balance_request = AccountsBalanceGetRequest(
                    access_token=credential.access_token,
                    options={"account_ids": [account.plaid_account_id]}
                )
                try:
                    balance_response = client.accounts_balance_get(balance_request)
                    balance = balance_response.to_dict()['accounts'][0]['balances']['current']
                except plaid.ApiException as e:
                    balance = None

                account_transactions = transactions_by_account.get(account.plaid_account_id, [])

                accounts.append({
                    'plaid_account_id': account.plaid_account_id,
                    'name': account.name,
                    'type': account.type,
                    'subtype': account.subtype,
                    'mask': account.mask,
                    'balance': balance,
                    'transactions': account_transactions
                })

            if not credential_error:
                credential_data = {
                    'institution_name': credential.institution_name,
                    'next_cursor': next_cursor,
                    'accounts': accounts
                }
                banks.append(credential_data)
            else:
                credential_data = {
                    'institution_name': credential.institution_name,
                    'error': credential_error
                }
                banks.append(credential_data)

        return jsonify(banks=banks)

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

    @app.route('/api/balance', methods=['POST'])
    @login_required
    def fetch_balances():
        data = request.json
        access_token = data.get('access_token')
        account_ids = data.get('account_ids', [])

        balance_request = AccountsBalanceGetRequest(
            access_token=access_token,
            options={"account_ids": account_ids}
        )
        try:
            balance_response = client.accounts_balance_get(balance_request)
            return jsonify(balance_response.to_dict())
        except plaid.ApiException as e:
            return jsonify(json.loads(e.body)), e.status

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

    def log_request_response(request, response):
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_file = os.path.join(log_dir, f'api_log_{now}.txt')

        with open(log_file, 'a') as f:
            f.write('Request:\n')
            f.write(str(request) + '\n\n')
            f.write('Response:\n')
            f.write(str(response) + '\n\n')


    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
