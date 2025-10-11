# core_views.py
from flask import Blueprint, jsonify, request, session, current_app
from flask_login import login_required, current_user
from models import db, Credential, Account, PlaidTransaction, Transaction
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_webhook_update_request import ItemWebhookUpdateRequest
#from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
import plaid
import json
from datetime import datetime, date
from io import StringIO
import csv
from config import Config
from version import __version__ as VERSION
from decimal import Decimal

core = Blueprint('core', __name__)

@core.route('/create_link_token', methods=['POST'])
@login_required
def create_link_token():
    data = request.json or {}
    access_token = data.get('access_token')
    is_refresh = data.get('is_refresh', False)
    
    link_token_request = {
        'user': {
            'client_user_id': str(current_user.id),
        },
        'client_name': "ExMint",
        'products': ["transactions"],
        'country_codes': ['CA','US'],
        'language': 'en',
        'redirect_uri': 'https://automatos.ca',
        'webhook': current_app.config['PLAID_WEBHOOK_URL'],
        "update": {
        "account_selection_enabled": True
        },
    }

    link_token_request["update"] = {"account_selection_enabled": True}
        
    if access_token:
        link_token_request['access_token'] = access_token

    try:
        response = current_app.plaid_client.link_token_create(link_token_request)
        return jsonify(response.to_dict())
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})

@core.route('/handle_token_and_accounts', methods=['POST'])
@login_required
def handle_token_and_accounts():
    data = request.json
    credential_id = data.get('credential_id')
    public_token = data.get('public_token', None)
    is_refresh = data.get('is_refresh', False)

    try:
        # Fetch the webhook URL from the environment (via Config)
        webhook_url = current_app.config['PLAID_WEBHOOK_URL']
        if not webhook_url:
            return jsonify({'error': 'Webhook URL is not configured in the environment.'}), 500

        if is_refresh:
            print(f"Trying to refresh connection...")
            credential = Credential.query.get(credential_id)
            if not credential:
                return jsonify({'error': 'Credential not found'}), 404
            
            access_token = credential.access_token
            print(f"** Debug: Refreshing with access_token: {access_token}")

            # Update the webhook for the existing item
            webhook_update_request = {
                'client_id': current_app.config['PLAID_CLIENT_ID'],
                'secret': current_app.config['PLAID_SECRET'],
                'access_token': access_token,
                'webhook': webhook_url
            }
            webhook_update_response = current_app.plaid_client.item_webhook_update(webhook_update_request)
            webhook_update_data = webhook_update_response.to_dict()
            print(f"** Debug: Webhook updated for refresh. Response: {webhook_update_data}")

            # Extract and update the item_id in the Credential table
            item_id = webhook_update_data['item']['item_id']
            print(f"Item ID during refresh: {item_id}")
            credential.item_id = item_id
            db.session.commit()
            print(f"Connection refreshed...")

        else:
            print(f"Trying to add new connection...")
            public_token = data['public_token']
            institution_name = data.get('institution_name', 'Unknown')
            exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
            exchange_response = current_app.plaid_client.item_public_token_exchange(exchange_request)
            access_token = exchange_response['access_token']
            item_id = exchange_response['item_id']  # Extract item_id
            print(f"Item ID during creation: {item_id}")

            credential = Credential(
                user_id=current_user.id,
                access_token=access_token,
                institution_name=institution_name,
                item_id=item_id,  # Store the item_id
                requires_update=False
            )
            db.session.add(credential)
            db.session.commit()

            credential_id = credential.id

        # Fetch accounts using the access token
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
                    status='Active', 
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

def _persist_transactions_from_payload(user, credential, data):
    counts = {'added': 0, 'modified': 0, 'removed': 0}

    for action in ['added', 'modified', 'removed']:
        for payload in data.get(action, []):
            plaid_transaction_id = payload.get('transaction_id')
            if not plaid_transaction_id:
                continue

            transaction = Transaction.query.filter_by(plaid_transaction_id=plaid_transaction_id).first()

            if action == 'removed':
                if transaction and not transaction.is_removed:
                    transaction.is_removed = True
                    transaction.last_action = 'removed'
                    transaction.updated_at = datetime.utcnow()
                    counts['removed'] += 1
                elif transaction:
                    transaction.last_action = 'removed'
                continue

            account = Account.query.filter_by(plaid_account_id=payload.get('account_id')).first()
            if not account:
                current_app.logger.warning(
                    "Skipping transaction %s because account %s was not found",
                    plaid_transaction_id,
                    payload.get('account_id')
                )
                continue

            amount_value = payload.get('amount')
            if amount_value is None:
                amount_value = 0

            if transaction is None:
                transaction = Transaction(
                    plaid_transaction_id=plaid_transaction_id,
                    user_id=user.id,
                    credential_id=credential.id,
                    account_id=account.id,
                    created_at=datetime.utcnow()
                )
                db.session.add(transaction)
            else:
                transaction.credential_id = credential.id
                transaction.account_id = account.id

            transaction.name = payload.get('name') or ''
            transaction.amount = Decimal(str(amount_value))
            transaction.iso_currency_code = payload.get('iso_currency_code')
            transaction.category = json.dumps(payload.get('category', []))
            transaction.merchant_name = payload.get('merchant_name')
            transaction.payment_channel = payload.get('payment_channel')

            date_value = payload.get('date')
            if isinstance(date_value, datetime):
                transaction.date = date_value.date()
            elif isinstance(date_value, date):
                transaction.date = date_value
            elif isinstance(date_value, str) and date_value:
                try:
                    transaction.date = datetime.strptime(date_value, '%Y-%m-%d').date()
                except ValueError:
                    current_app.logger.warning(
                        "Invalid transaction date %s for %s",
                        date_value,
                        plaid_transaction_id
                    )
            elif date_value:
                current_app.logger.warning(
                    "Unexpected transaction date type %s for %s",
                    type(date_value),
                    plaid_transaction_id
                )
            if transaction.date is None:
                transaction.date = datetime.utcnow().date()

            transaction.pending = bool(payload.get('pending', False))
            transaction.is_removed = False
            transaction.last_action = action
            transaction.updated_at = datetime.utcnow()

            if action in counts:
                counts[action] += 1

    return counts


def _sync_credential_transactions(user, credential):
    counts = {'added': 0, 'modified': 0, 'removed': 0}
    cursor = credential.transactions_cursor
    has_more = True
    latest_cursor = cursor
    credential_error = None

    while has_more:
        payload = {
            'access_token': credential.access_token,
            'count': 500
        }

        if cursor:
            payload['cursor'] = cursor

        try:
            response = current_app.plaid_client.transactions_sync(payload)
        except plaid.ApiException as e:
            error_response = json.loads(e.body)
            log_method = current_app.logger.error
            if error_response.get('error_code') == 'ITEM_LOGIN_REQUIRED':
                log_method = current_app.logger.warning

            log_method(
                "Error fetching transactions for credential %s: %s -> %s",
                credential.id,
                error_response.get('error_code'),
                error_response.get('error_message')
            )

            if error_response.get('error_code') == 'DEVELOPMENT_ENVIRONMENT_BROWNOUT':
                raise

            if error_response.get('error_code') == 'ITEM_LOGIN_REQUIRED':
                credential.requires_update = True
                credential_error = {
                    'error_code': error_response['error_code'],
                    'error_message': error_response['error_message']
                }
            else:
                credential_error = {
                    'error_code': error_response.get('error_code'),
                    'error_message': error_response.get('error_message', str(e))
                }
            break
        except Exception as exc:
            current_app.logger.exception("Unexpected error fetching transactions: %s", exc)
            credential_error = {'error_message': str(exc)}
            break

        data = response.to_dict()
        cursor = data.get('next_cursor')
        has_more = data.get('has_more', False)
        latest_cursor = cursor or latest_cursor

        payload_counts = _persist_transactions_from_payload(user, credential, data)
        for key in counts:
            counts[key] += payload_counts.get(key, 0)

    if credential_error is None:
        credential.transactions_cursor = cursor or latest_cursor or credential.transactions_cursor

    return counts, credential_error


@core.route('/api/transactions/sync', methods=['POST'])
@login_required
def sync_transactions():
    user = current_user
    active_credentials = Credential.query.filter_by(user_id=user.id, status='Active').all()

    summary = []
    errors = []

    for credential in active_credentials:
        try:
            counts, credential_error = _sync_credential_transactions(user, credential)
            db.session.commit()

            summary.append({
                'credential_id': credential.id,
                'institution_name': credential.institution_name,
                'added': counts['added'],
                'modified': counts['modified'],
                'removed': counts['removed'],
                'requires_update': credential.requires_update
            })

            audit_payload = {
                'counts': counts,
                'cursor': credential.transactions_cursor,
                'requires_update': credential.requires_update
            }
            plaid_transaction = PlaidTransaction(
                user_id=user.id,
                user_ip=request.remote_addr,
                credential_id=credential.id,
                operation='Transactions sync',
                response=json.dumps(audit_payload)
            )
            db.session.add(plaid_transaction)

            if credential_error:
                errors.append({
                    'credential_id': credential.id,
                    'institution_name': credential.institution_name,
                    **credential_error
                })
        except plaid.ApiException as e:
            errors.append({
                'credential_id': credential.id,
                'institution_name': credential.institution_name,
                'error_code': 'DEVELOPMENT_ENVIRONMENT_BROWNOUT',
                'error_message': 'Plaid Development environment is undergoing a scheduled brownout. Please try again later.'
            })
            db.session.rollback()
        except Exception as exc:
            current_app.logger.exception("Failed to sync transactions for credential %s", credential.id)
            errors.append({
                'credential_id': credential.id,
                'institution_name': credential.institution_name,
                'error_message': str(exc)
            })
            db.session.rollback()

    db.session.commit()

    status_code = 200 if not errors else 207
    return jsonify({'summary': summary, 'errors': errors, 'version': VERSION}), status_code

@core.route('/api/accounts', methods=['GET'])
@login_required
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
@login_required
def get_banks():
    banks = Credential.query.filter_by(user_id=current_user.id, status='Active').all()
    banks_data = []

    for bank in banks:
        accounts_data = []
        for account in bank.accounts:
            if account.status != 'Active':
                continue

            accounts_data.append({
                'id': account.id,
                'name': account.name,
                'mask': account.mask,
                'type': account.type,
                'subtype': account.subtype,
                'plaid_account_id': account.plaid_account_id,
                'is_enabled': account.is_enabled
            })

        banks_data.append({
            'id': bank.id,
            'institution_name': bank.institution_name,
            'requires_update': bank.requires_update,
            'accounts': accounts_data
        })

    return jsonify(banks=banks_data)

@core.route('/api/transactions', methods=['GET'])
@login_required
def get_transactions():
    account_ids_param = request.args.get('account_ids', '')
    account_ids = []

    for part in account_ids_param.split(','):
        value = part.strip()
        if value.isdigit():
            account_ids.append(int(value))

    try:
        page = int(request.args.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    try:
        page_size = int(request.args.get('page_size', 200))
    except (TypeError, ValueError):
        page_size = 200
    page_size = max(1, min(page_size, 500))

    query = Transaction.query.options(
        joinedload(Transaction.account),
        joinedload(Transaction.credential)
    ).filter(
        Transaction.user_id == current_user.id,
        Transaction.is_removed.is_(False)
    )

    if account_ids:
        query = query.filter(Transaction.account_id.in_(account_ids))

    total_count = query.count()
    ordered_query = query.order_by(Transaction.date.desc(), Transaction.id.desc())
    offset = (page - 1) * page_size
    transactions = ordered_query.offset(offset).limit(page_size).all()

    response = []
    for txn in transactions:
        account = txn.account
        credential = txn.credential
        try:
            category = json.loads(txn.category) if txn.category else []
        except (TypeError, ValueError):
            category = [txn.category] if txn.category else []

        amount_value = float(txn.amount) if txn.amount is not None else 0.0

        response.append({
            'id': txn.id,
            'plaid_transaction_id': txn.plaid_transaction_id,
            'date': txn.date.isoformat() if txn.date else None,
            'name': txn.name,
            'amount': amount_value,
            'iso_currency_code': txn.iso_currency_code,
            'category': category,
            'merchant_name': txn.merchant_name,
            'payment_channel': txn.payment_channel,
            'pending': bool(txn.pending),
            'account_id': txn.account_id,
            'account_name': account.name if account else None,
            'account_mask': account.mask if account else None,
            'account_type': account.type if account else None,
            'account_subtype': account.subtype if account else None,
            'institution_name': credential.institution_name if credential else None
        })

    has_more = (page * page_size) < total_count

    return jsonify(
        transactions=response,
        page=page,
        page_size=page_size,
        total_count=total_count,
        has_more=has_more
    )

@core.route('/api/balance', methods=['POST'])
@login_required
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
@login_required
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
            session['connections_modal_open'] = True
            return jsonify({'success': False, 'message': 'Failed to remove bank connection', 'error': plaid_response}), 400
    else:
        return jsonify({'success': False, 'message': 'Credential not found'}), 404

@core.route('/api/get_access_token/<int:credential_id>', methods=['GET'])
@login_required
def get_access_token_for_bank(credential_id):
    credential = Credential.query.filter_by(id=credential_id, user_id=current_user.id).first()

    if not credential:
        return jsonify({'error': 'Credential not found or does not belong to the current user'}), 404

    try:
        access_token = credential.access_token
        return jsonify({'access_token': access_token})
    except Exception as e:
        return jsonify({'error': 'Failed to retrieve access token', 'message': str(e)}), 500

# CANDIDATE FOR DELETION, THIS FUNCTION DOES NOT SEEM TO BE USED ANYWHERE:
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

@core.route('/plaid_webhook', methods=['POST'])
def plaid_webhook():
    data = request.get_json()

    # Extract relevant fields from the payload
    timestamp = datetime.now()
    environment = data.get('environment', 'Unknown')
    error = data.get('error', {}) or {}  # Handle None by defaulting to an empty dictionary
    error_code = error.get('error_code', 'None')
    item_id = data.get('item_id', 'Unknown')
    webhook_code = data.get('webhook_code', 'Unknown')
    webhook_type = data.get('webhook_type', 'Unknown')
    request_id = data.get('request_id', 'Unknown')
    status = error.get('status', 'Unknown')

    # Log the incoming webhook
    print("***** INCOMING WEBHOOK *****")
    print(f"Data: {data}")

    # Handle ITEM_LOGIN_REQUIRED
    if webhook_type == "ITEM" and webhook_code in ["ERROR", "NEW_ACCOUNTS_AVAILABLE"]:
        try:
            # Find the related Credential in the database
            credential = Credential.query.filter_by(item_id=item_id).first()

            if credential:
                # Extract the user_id from the Credential
                user_id = credential.user_id
                if not user_id:
                    print(f"Warning: No user_id found for Credential ID: {credential.id}")
                    return jsonify({"status": "ok"}), 200

                credential.requires_update = True
                db.session.commit()
                print(f"Updated Credential (ID: {credential.id}) with requires_update=True")

                # Add a record to the PlaidTransaction table
                plaid_transaction = PlaidTransaction(
                    timestamp=timestamp,
                    user_id=user_id,
                    user_ip='3.171.22.34', 
                    credential_id=credential.id,
                    account_id=None,  # Not relevant for ITEM_LOGIN_REQUIRED or NEW_ACCOUNTS_AVAILABLE
                    operation=error_code if webhook_code == "ERROR" else webhook_code,
                    response=str(data),  # Store the entire webhook payload
                    posted_transactions=None,
                    pending_transactions=None
                )
                db.session.add(plaid_transaction)
                db.session.commit()

                print(f"Updated Credential (ID: {credential.id}) with requires_update=True")
                print(f"Added PlaidTransaction record for Credential ID: {credential.id}")
            else:
                print(f"No Credential found for Item ID: {item_id}")
        except Exception as e:
            print(f"Error handling ITEM_LOGIN_REQUIRED: {str(e)}")
            db.session.rollback()

    return jsonify({"status": "ok"}), 200


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
