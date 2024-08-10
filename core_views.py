# core_views.py
from flask import Blueprint, jsonify, request, session, current_app
from flask_login import login_required, current_user
from models import db, User, Credential, Account, PlaidTransaction
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from sqlalchemy import and_
import plaid
import json
from io import StringIO
import csv
from config import Config
from views import combined_required
from version import __version__ as VERSION

core = Blueprint('core', __name__)

@core.route('/create_link_token', methods=['POST'])
def create_link_token():
    data = request.json
    user_id = data.get('user_id')
    access_token = data.get('access_token', None)

    link_token_request = {
        'user': {
            'client_user_id': str(user_id),
        },
        'client_name': "ExMint",
        'products': ["transactions"],
        'country_codes': ['CA','US'],
        'language': 'en',
        'redirect_uri': 'https://automatos.ca',
    }

    if access_token:
        link_token_request['access_token'] = access_token

    try:
        response = current_app.plaid_client.link_token_create(link_token_request)
        return jsonify(response.to_dict())
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})

@core.route('/handle_token_and_accounts', methods=['POST'])
@combined_required
def handle_token_and_accounts():
    data = request.json
    credential_id = data.get('credential_id')
    public_token = data.get('public_token', None)
    is_refresh = data.get('is_refresh', False)

    if not current_user.is_authenticated:
        return jsonify({'error': 'User not authenticated'}), 401

    try:
        if is_refresh:
            print(f"Trying to refresh connection...")
            credential = Credential.query.get(credential_id)
            if not credential:
                return jsonify({'error': 'Credential not found'}), 404
            access_token = credential.access_token
        else:
            print(f"Trying to add new connection...")
            public_token = data['public_token']
            institution_name = data.get('institution_name', 'Unknown')
            exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
            exchange_response = current_app.plaid_client.item_public_token_exchange(exchange_request)
            access_token = exchange_response['access_token']

            credential = Credential(
                user_id=current_user.id,
                access_token=access_token,
                institution_name=institution_name,
                requires_update=False
            )
            db.session.add(credential)
            db.session.commit()
            
            credential_id = credential.id

        accounts_request = AccountsGetRequest(access_token=access_token)
        accounts_response = current_app.plaid_client.accounts_get(accounts_request)
        
        accounts_data = accounts_response.to_dict().get('accounts', [])
        for account in accounts_data:
            plaid_account_id = account.get('account_id')
            name = account.get('name')
            type_ = account.get('type')
            subtype = account.get('subtype')
            mask = account.get('mask')
            is_enabled = account.get('is_enabled', True)  # Default to True if not present

            existing_account = Account.query.filter_by(plaid_account_id=plaid_account_id).first()
            if existing_account:
                existing_account.name = name
                existing_account.type = type_
                existing_account.subtype = subtype
                existing_account.mask = mask
                existing_account.is_enabled = is_enabled
            else:
                new_account = Account(
                    status='Active',  # Assuming status is 'Active' since it's not in the account data
                    credential_id=credential_id,
                    plaid_account_id=plaid_account_id,
                    name=name,
                    type=type_,
                    subtype=subtype,
                    mask=mask,
                    is_enabled=is_enabled
                )
                db.session.add(new_account)
        db.session.commit()
        
        filtered_response = {
            'item': accounts_response['item'],
            'request_id': accounts_response['request_id']
        }

        plaid_transaction = PlaidTransaction(
            user_id=current_user.id,
            user_ip=request.remote_addr,
            credential_id=credential.id,
            operation='Institution Refresh' if is_refresh else 'Token Creation',
            response=str(filtered_response)
        )
        db.session.add(plaid_transaction)

        # Check if the requires_update flag is being set correctly
        credential.requires_update = False
        db.session.commit()
        db.session.refresh(credential)  # Refresh the instance to get the latest state from the DB

        return jsonify({'status': 'success', 'message': 'Bank connection added successfully'})
    
    except Exception as e:
        print(f"Error in handle_token_and_accounts: {str(e)}")
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@core.route('/sync', methods=['GET'])
def sync_transactions():
    user_token = request.headers.get('x-user-token')
    if not user_token:
        return jsonify({'error': 'Missing user token'}), 401

    user_id = User.verify_auth_token(user_token)
    if user_id is None:
        return jsonify({'error': 'Invalid or expired user token'}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    banks = []
    cursors_data = request.headers.get('cursors', '')
    cursor_dict = {}

    for pair in cursors_data.split(','):
        try:
            credential_id, cursor = pair.split(':')
            if credential_id.isdigit() and len(cursor) >= 10:
                cursor_dict[int(credential_id)] = cursor
        except ValueError:
            pass

    active_credentials = Credential.query.filter_by(user_id=user.id, status='Active').all()

    for credential in active_credentials:
        accounts = []
        next_cursor = None
        credential_error = None
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
                    cursor = None

                response = current_app.plaid_client.transactions_sync(sync_request_payload)
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
                print(f"Error fetching transactions: {error_response['error_message']}")
                if error_response.get('error_code') == 'DEVELOPMENT_ENVIRONMENT_BROWNOUT':
                    return jsonify({'error': 'Plaid Development environment is undergoing a scheduled brownout. Please try again later.'}), 503
                elif error_response.get('error_code') == 'ITEM_LOGIN_REQUIRED':
                    credential.requires_update = True
                    db.session.commit()
                    credential_error = {
                        'error_code': error_response['error_code'],
                        'error_message': error_response['error_message']
                    }
                    break
                else:
                    print("Error fetching transactions:", str(e))
            except Exception as e:
                print("General error during transaction fetching:", str(e))
                break

        active_accounts = Account.query.filter(
            and_(Account.credential_id == credential.id, Account.status == 'Active', Account.is_enabled == True)
        ).all()

        for account in active_accounts:
            # Replace balance_request with accounts_request
            accounts_request = AccountsGetRequest(
                access_token=credential.access_token,
                options={"account_ids": [account.plaid_account_id]}
            )

            try:
                accounts_response = current_app.plaid_client.accounts_get(accounts_request)
                balance = accounts_response.to_dict()['accounts'][0]['balances']['current']
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
                'transaction_count': len(account_transactions),
                'transactions': account_transactions
            })

        if not credential_error:
            credential_data = {
                'credential_id': credential.id,
                'institution_name': credential.institution_name,
                'operation': 'Update sync' if cursors_data else 'Full sync',
                'next_cursor': next_cursor,
                'accounts': accounts
            }
        else:
            credential_data = {
                'credential_id': credential.id,
                'institution_name': credential.institution_name,
                'operation': 'Update sync' if cursors_data else 'Full sync',
                'error': credential_error
            }
        banks.append(credential_data)

    transaction = PlaidTransaction(
        user_id=user.id,
        user_ip=request.remote_addr,
        credential_id=credential.id,
        operation='Update sync' if cursors_data else 'Full sync',
        response=json.dumps({'banks': [
            {
                'credential_id': bank['credential_id'],
                'institution_name': bank['institution_name'],
                'operation': bank['operation'],
                'next_cursor': bank.get('next_cursor'),
                'error': bank.get('error'),
                'accounts': [
                    {
                        'plaid_account_id': account['plaid_account_id'],
                        'name': account['name'],
                        'type': account['type'],
                        'subtype': account['subtype'],
                        'mask': account['mask'],
                        'transaction_count': account['transaction_count']
                    }
                    for account in bank.get('accounts', [])
                ]
            }
            for bank in banks
        ]})
    )
    db.session.add(transaction)
    db.session.commit()

    return jsonify({'banks': banks, 'version': VERSION})

@core.route('/api/accounts', methods=['GET'])
@combined_required
def get_accounts():
    user_id = current_user.id
    bank_id = request.args.get('bank_id')

    query = Account.query.join(Credential).filter(Credential.user_id == user_id, Credential.status == 'Active')

    if bank_id:
        query = query.filter(Credential.id == bank_id)

    accounts = query.filter(Account.status == 'Active').all()

    accounts_data = [{'id': account.id, 'name': account.name, 'mask': account.mask, 
                    'type': account.type, 'subtype': account.subtype, 'is_enabled': account.is_enabled} for account in accounts]

    return jsonify(accounts=accounts_data)

@core.route('/api/banks', methods=['GET'])
@combined_required
def get_banks():
    token = request.args.get('token')
    if token:
        user = User.verify_auth_token(token)
        if not user or user != current_user:
            return jsonify({'message': 'Invalid or missing token'}), 401
    else:
        user = current_user

    banks = Credential.query.filter_by(user_id=user.id, status='Active').all()
    banks_data = [
        {
            'id': bank.id,
            'institution_name': bank.institution_name,
            'requires_update': bank.requires_update
        } for bank in banks
    ]
    return jsonify(banks=banks_data)

@core.route('/api/balance', methods=['POST'])
@combined_required
def fetch_balances():
    data = request.json
    access_token = data.get('access_token')
    account_ids = data.get('account_ids', [])

    # Use AccountsGetRequest instead of AccountsBalanceGetRequest
    accounts_request = AccountsGetRequest(
        access_token=access_token,
        options={"account_ids": account_ids} if account_ids else None
    )

    try:
        accounts_response = current_app.plaid_client.accounts_get(accounts_request)
        accounts = accounts_response.to_dict().get('accounts', [])

        # Extract the necessary balance information from the accounts data
        balances = []
        for account in accounts:
            balance_info = {
                "account_id": account.get('account_id'),
                "balances": account.get('balances')
            }
            balances.append(balance_info)

        return jsonify({"balances": balances})
    except plaid.ApiException as e:
        return jsonify(json.loads(e.body)), e.status

@core.route('/api/remove_bank/<int:bank_id>', methods=['DELETE'])
@combined_required
def remove_bank(bank_id):
    credential = Credential.query.filter_by(id=bank_id, user_id=current_user.id).first()
    
    if credential:
        success, plaid_response = deactivate_plaid_token(credential.access_token)
        
        if success:
            credential.status = 'Revoked'

            for account in credential.accounts:
                account.status = 'Revoked'
            
            transaction = PlaidTransaction(
                user_id=current_user.id,
                user_ip=request.remote_addr,
                credential_id=credential.id,
                operation='Access token and associated accounts revoked',
                response=str(plaid_response)
            )
            db.session.add(transaction)
            db.session.commit()
            session['connections_modal_open'] = True
            return jsonify({'success': True, 'message': 'Bank connection removed'}), 200
        else:
            print(f"Failed to deactivate token: {plaid_response}")
            session['modal_open'] = True
            return jsonify({'success': False, 'message': 'Failed to remove bank connection', 'error': plaid_response}), 400
    else:
        return jsonify({'success': False, 'message': 'Credential not found'}), 404

@core.route('/api/get_access_token/<int:credential_id>', methods=['GET'])
@combined_required
def get_access_token_for_bank(credential_id):
    credential = Credential.query.filter_by(id=credential_id, user_id=current_user.id).first()

    if not credential:
        return jsonify({'error': 'Credential not found or does not belong to the current user'}), 404

    try:
        access_token = credential.access_token
        return jsonify({'access_token': access_token})
    except Exception as e:
        return jsonify({'error': 'Failed to retrieve access token', 'message': str(e)}), 500

# Helper functions

def refresh_accounts(credential_id, accounts_data):
    existing_accounts = Account.query.filter_by(credential_id=credential_id).all()
    existing_account_ids = {account.plaid_account_id for account in existing_accounts}

    for account in accounts_data['accounts']:
        if account['account_id'] in existing_account_ids:
            existing_account = next((acc for acc in existing_accounts if acc.plaid_account_id == account['account_id']), None)
            if existing_account:
                existing_account.name = account['name']
                existing_account.type = account['type']
                existing_account.subtype = account['subtype']
                existing_account.mask = account.get('mask', '')
    else:
                new_account = Account(
                    credential_id=credential_id,
                    plaid_account_id=account['account_id'],
                    name=account['name'],
                    type=account['type'],
                    subtype=account['subtype'],
                    mask=account.get('mask', ''),
                    status='Active'
                )
                db.session.add(new_account)

    current_account_ids = {account['account_id'] for account in accounts_data['accounts']}
    for existing_account in existing_accounts:
        if existing_account.plaid_account_id not in current_account_ids:
            existing_account.status = 'Inactive'

    db.session.commit()

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
    return [transaction for transaction in transactions if transaction['account_id'] == account_plaid_id]

def deactivate_plaid_token(access_token):
    try:
        print('Access Token to Remove: ', access_token)
        request = ItemRemoveRequest(access_token=access_token)
        response = current_app.plaid_client.item_remove(request)
        
        print("Plaid response:", response)
        return True, response.to_dict()
    except plaid.ApiException as e:
        print("An error occurred while removing the item from Plaid:", e)
        return False, e.body
    
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