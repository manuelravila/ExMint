# core_views.py
from flask import Blueprint, jsonify, request, session, current_app
from flask_login import login_required, current_user
from models import db, Credential, Account, PlaidTransaction, Transaction, Category, TransactionCategoryOverride
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_webhook_update_request import ItemWebhookUpdateRequest
#from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from sqlalchemy import and_, or_, func, asc, desc, inspect, text
from sqlalchemy.orm import joinedload
import plaid
import json
import re
from datetime import datetime, date
from io import StringIO
import csv
from config import Config
from version import __version__ as VERSION
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import OperationalError

core = Blueprint('core', __name__)

_CATEGORY_SCHEMA_CHECKED = False
FALLBACK_CATEGORY_COLOR = '#E2E8F0'
DEFAULT_MANUAL_COLOR = '#2C6B4F'
UNCATEGORIZED_LABEL = 'Uncategorized'


def ensure_category_schema(force=False):
    global _CATEGORY_SCHEMA_CHECKED
    if _CATEGORY_SCHEMA_CHECKED and not force:
        return
    try:
        bind = db.engine
        inspector = inspect(bind)
        tables = inspector.get_table_names()
        if 'categories' not in tables:
            _CATEGORY_SCHEMA_CHECKED = True
            return

        columns = {column['name'] for column in inspector.get_columns('categories')}
        if 'color' not in columns:
            with bind.connect() as conn:
                conn.execute(text("ALTER TABLE categories ADD COLUMN color VARCHAR(7) NOT NULL DEFAULT '#2C6B4F'"))
                conn.execute(text("UPDATE categories SET color = '#2C6B4F' WHERE color IS NULL OR color = ''"))

        if 'transaction_category_override' not in tables:
            op = text(
                """
                CREATE TABLE transaction_category_override (
                    transaction_id INT NOT NULL PRIMARY KEY,
                    label VARCHAR(255) NOT NULL,
                    color VARCHAR(7),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT fk_transaction_override_transaction
                        FOREIGN KEY (transaction_id) REFERENCES transactions (id)
                        ON DELETE CASCADE
                )
                """
            )
            with bind.connect() as conn:
                conn.execute(op)

        _CATEGORY_SCHEMA_CHECKED = True
    except Exception as exc:
        current_app.logger.warning('Unable to ensure categories schema: %s', exc)
        _CATEGORY_SCHEMA_CHECKED = False


def _with_schema_retry(handler):
    try:
        return handler()
    except OperationalError as exc:
        error_args = getattr(exc.orig, 'args', None)
        error_code = error_args[0] if error_args else None
        if error_code in (1054, 1412, 1146):
            current_app.logger.warning('Detected schema mismatch (%s). Retrying after ensuring schema.', error_code)
            db.session.rollback()
            ensure_category_schema(force=True)
            return handler()
        raise

_FIELD_MAP = {
    'description': 'description',
    'merchant': 'merchant',
    'category': 'category'
}

_TYPE_ALIASES = {
    'credit': 'credit',
    'deposit': 'credit',
    'income': 'credit',
    'incoming': 'credit',
    'debit': 'debit',
    'withdrawal': 'debit',
    'expense': 'debit',
    'outgoing': 'debit'
}


def _extract_category_list(raw_value):
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if item]
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except (TypeError, ValueError):
            return [raw_value] if raw_value else []
        return [raw_value] if raw_value else []
    return [str(raw_value)]


def _derive_fallback_label_from_category(raw_value):
    categories = _extract_category_list(raw_value)
    if categories:
        return ' / '.join(categories)
    return UNCATEGORIZED_LABEL


def _load_overrides(transaction_ids):
    if not transaction_ids:
        return {}
    try:
        overrides = TransactionCategoryOverride.query.filter(
            TransactionCategoryOverride.transaction_id.in_(transaction_ids)
        ).all()
    except Exception:
        ensure_category_schema(force=True)
        overrides = TransactionCategoryOverride.query.filter(
            TransactionCategoryOverride.transaction_id.in_(transaction_ids)
        ).all()
    return {override.transaction_id: override for override in overrides}


def _serialize_transaction(txn, override_map):
    category_list = _extract_category_list(txn.category)
    fallback_label = ' / '.join(category_list) if category_list else UNCATEGORIZED_LABEL

    override = override_map.get(txn.id)
    if override:
        label = override.label
        color = override.color or DEFAULT_MANUAL_COLOR
        source = 'manual'
    elif txn.custom_category is not None:
        label = txn.custom_category.label or fallback_label
        color = txn.custom_category.color or DEFAULT_MANUAL_COLOR
        source = 'rule'
    else:
        label = fallback_label
        color = FALLBACK_CATEGORY_COLOR
        source = 'fallback'

    return {
        'id': txn.id,
        'plaid_transaction_id': txn.plaid_transaction_id,
        'date': txn.date.isoformat() if txn.date else None,
        'name': txn.name,
        'amount': float(txn.amount) if txn.amount is not None else 0.0,
        'iso_currency_code': txn.iso_currency_code,
        'category': category_list,
        'merchant_name': txn.merchant_name,
        'payment_channel': txn.payment_channel,
        'pending': bool(txn.pending),
        'account_id': txn.account_id,
        'account_name': txn.account.name if txn.account else None,
        'account_mask': txn.account.mask if txn.account else None,
        'account_type': txn.account.type if txn.account else None,
        'account_subtype': txn.account.subtype if txn.account else None,
        'institution_name': txn.credential.institution_name if txn.credential else None,
        'custom_category_id': txn.custom_category_id,
        'custom_category': label,
        'custom_category_color': color,
        'custom_category_source': source,
        'custom_category_is_fallback': source == 'fallback'
    }

_COLOR_RE = re.compile(r'^#([0-9a-fA-F]{6})$')


def _wildcard_to_regex(pattern):
    escaped = re.escape(pattern)
    escaped = escaped.replace(r'\*', '.*')
    escaped = escaped.replace(r'\?', '.')
    escaped = escaped.replace(r'\#', r'\d')
    return re.compile(escaped, re.IGNORECASE)


def _resolve_rule_field(field_value):
    if not field_value:
        return 'description'
    field_value = field_value.lower()
    return _FIELD_MAP.get(field_value, 'description')


def _resolve_rule_type(type_value):
    if not type_value:
        return None
    normalized = _TYPE_ALIASES.get(type_value.lower(), type_value.lower())
    return normalized if normalized in {'credit', 'debit'} else None


def _extract_field_value(transaction, field_name):
    if field_name == 'merchant':
        return transaction.merchant_name or ''
    if field_name == 'category':
        raw = transaction.category or ''
        if isinstance(raw, list):
            return ' '.join([str(item) for item in raw if item])
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return ' '.join([str(item) for item in parsed if item])
            if parsed:
                return str(parsed)
        except (TypeError, ValueError):
            pass
        return str(raw) if raw else ''
    return transaction.name or ''


def _determine_transaction_flow(amount):
    if amount is None:
        return None
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if value < 0:
        return 'debit'
    if value > 0:
        return 'credit'
    return 'neutral'


def _normalize_color(value):
    if not value:
        return '#2C6B4F'
    candidate = value.strip()
    if not candidate.startswith('#'):
        candidate = f'#{candidate}'
    candidate = candidate.upper()
    if not _COLOR_RE.match(candidate):
        raise ValueError('Invalid color value')
    return candidate


def _compile_category_rules(user_id):
    ensure_category_schema()
    rules = Category.query.filter_by(user_id=user_id).order_by(Category.created_at.asc(), Category.id.asc()).all()
    compiled = []
    for rule in rules:
        pattern = (rule.text_to_match or '').strip()
        label = (rule.label or '').strip()
        if not pattern or not label:
            continue
        try:
            regex = _wildcard_to_regex(pattern)
        except re.error:
            continue
        compiled.append({
            'id': rule.id,
            'regex': regex,
            'field': _resolve_rule_field(rule.field_to_match),
            'type': _resolve_rule_type(rule.transaction_type),
            'amount_min': Decimal(str(rule.amount_min)) if rule.amount_min is not None else None,
            'amount_max': Decimal(str(rule.amount_max)) if rule.amount_max is not None else None,
            'label': label,
            'color': rule.color or DEFAULT_MANUAL_COLOR
        })
    return compiled


def apply_rules_to_transactions(user_id, transaction_ids=None, include_removed=False):
    """
    Apply category rules to the user's transactions. If transaction_ids is provided,
    only those transactions are evaluated.
    """
    valid_rules = _compile_category_rules(user_id)
    rule_count = len(valid_rules)

    transactions_query = Transaction.query.filter(Transaction.user_id == user_id)
    if transaction_ids:
        transactions_query = transactions_query.filter(Transaction.id.in_(transaction_ids))
    if not include_removed:
        transactions_query = transactions_query.filter(Transaction.is_removed.is_(False))
    transactions = transactions_query.all()
    override_map = _load_overrides([txn.id for txn in transactions])

    updated = 0
    matched = 0

    for txn in transactions:
        if txn.id in override_map:
            continue

        txn_amount = Decimal(str(txn.amount)) if txn.amount is not None else None
        abs_amount = txn_amount.copy_abs() if txn_amount is not None else None
        txn_flow = _determine_transaction_flow(txn_amount)
        chosen_rule = None

        for compiled in valid_rules:
            if compiled['type'] and compiled['type'] != txn_flow:
                continue

            if compiled['amount_min'] is not None and (abs_amount is None or abs_amount < compiled['amount_min']):
                continue
            if compiled['amount_max'] is not None and (abs_amount is None or abs_amount > compiled['amount_max']):
                continue

            field_value = _extract_field_value(txn, compiled['field'])
            if not field_value:
                continue

            if compiled['regex'].search(field_value):
                chosen_rule = compiled

        if chosen_rule is not None:
            if txn.custom_category_id != chosen_rule['id']:
                txn.custom_category_id = chosen_rule['id']
                updated += 1
            matched += 1
        else:
            if txn.custom_category_id is not None:
                txn.custom_category_id = None
                updated += 1

    return {
        'rules_processed': rule_count,
        'matched_transactions': matched,
        'transactions_updated': updated
    }


def apply_category_rules(user_id, include_removed=False):
    """
    Apply category rules to all of the user's transactions.
    """
    return apply_rules_to_transactions(user_id, transaction_ids=None, include_removed=include_removed)


def _serialize_category(rule):
    return {
        'id': rule.id,
        'text_to_match': rule.text_to_match,
        'field_to_match': rule.field_to_match,
        'transaction_type': rule.transaction_type,
        'amount_min': str(rule.amount_min) if rule.amount_min is not None else None,
        'amount_max': str(rule.amount_max) if rule.amount_max is not None else None,
        'label': rule.label,
        'color': rule.color,
        'created_at': rule.created_at.isoformat() if rule.created_at else None,
        'updated_at': rule.updated_at.isoformat() if rule.updated_at else None
    }


def _parse_decimal_value(value):
    if value is None or value == '':
        return None
    try:
        decimal_value = Decimal(str(value))
        return decimal_value.copy_abs()
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid decimal value')


def _extract_label(payload):
    label = payload.get('label')
    if label:
        return label
    return payload.get('custom_category')


def _collect_category_labels(user_id):
    ensure_category_schema()
    labels = (
        db.session.query(Category.label)
        .filter(Category.user_id == user_id, Category.label.isnot(None))
        .distinct()
        .all()
    )
    return sorted(
        label for (label,) in labels if label
    )

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
    payload_by_action = {
        action: list(data.get(action, []) or [])
        for action in ['added', 'modified', 'removed']
    }

    transaction_ids = {
        payload.get('transaction_id')
        for payload_list in payload_by_action.values()
        for payload in payload_list
        if payload.get('transaction_id')
    }
    transaction_ids.discard(None)

    existing_transactions = {}
    if transaction_ids:
        existing_transactions = {
            txn.plaid_transaction_id: txn
            for txn in Transaction.query.filter(
                Transaction.plaid_transaction_id.in_(transaction_ids)
            ).all()
        }

    account_map = {account.plaid_account_id: account for account in credential.accounts}
    incoming_account_ids = {
        payload.get('account_id')
        for payload_list in (payload_by_action['added'], payload_by_action['modified'])
        for payload in payload_list
        if payload.get('account_id')
    }
    incoming_account_ids.discard(None)

    missing_account_ids = incoming_account_ids.difference(account_map.keys())
    if missing_account_ids:
        fetched_accounts = Account.query.filter(
            Account.plaid_account_id.in_(missing_account_ids)
        ).all()
        account_map.update({account.plaid_account_id: account for account in fetched_accounts})

    for payload in payload_by_action['removed']:
        plaid_transaction_id = payload.get('transaction_id')
        if not plaid_transaction_id:
            continue

        transaction = existing_transactions.get(plaid_transaction_id)
        if transaction and not transaction.is_removed:
            transaction.is_removed = True
            transaction.last_action = 'removed'
            transaction.updated_at = datetime.utcnow()
            counts['removed'] += 1
        elif transaction:
            transaction.last_action = 'removed'

    for action in ['added', 'modified']:
        for payload in payload_by_action[action]:
            plaid_transaction_id = payload.get('transaction_id')
            if not plaid_transaction_id:
                continue

            account = account_map.get(payload.get('account_id'))
            if not account:
                current_app.logger.warning(
                    "Skipping transaction %s because account %s was not found",
                    plaid_transaction_id,
                    payload.get('account_id')
                )
                continue

            transaction = existing_transactions.get(plaid_transaction_id)
            if transaction is None:
                transaction = Transaction(
                    plaid_transaction_id=plaid_transaction_id,
                    user_id=user.id,
                    credential_id=credential.id,
                    account_id=account.id,
                    created_at=datetime.utcnow()
                )
                db.session.add(transaction)
                existing_transactions[plaid_transaction_id] = transaction
            else:
                transaction.credential_id = credential.id
                transaction.account_id = account.id

            raw_amount = payload.get('amount', 0)
            if raw_amount is None:
                raw_amount = 0

            transaction.name = payload.get('name') or ''
            try:
                amount_decimal = Decimal(str(raw_amount))
            except (InvalidOperation, TypeError, ValueError):
                amount_decimal = Decimal('0')
            transaction.amount = -amount_decimal
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
    ensure_category_schema()
    def handler():
        user = current_user
        active_credentials = Credential.query.filter_by(user_id=user.id, status='Active').all()

        summary = []
        errors = []
        category_summary = None

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

        has_category_rules = Category.query.filter_by(user_id=user.id).first() is not None
        if has_category_rules:
            category_summary = apply_category_rules(user.id)

        db.session.commit()

        status_code = 200 if not errors else 207
        return jsonify({
            'summary': summary,
            'errors': errors,
            'version': VERSION,
            'categories': category_summary
        }), status_code

    return _with_schema_retry(handler)

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
    ensure_category_schema()

    def handler():
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

        sort_key = request.args.get('sort_key', 'date')
        sort_desc_value = request.args.get('sort_desc', 'true')
        sort_desc = str(sort_desc_value).lower() in ('true', '1', 'yes', 'y', 'desc')
        search_term = (request.args.get('search') or '').strip()

        query = Transaction.query.options(
            joinedload(Transaction.account),
            joinedload(Transaction.credential),
            joinedload(Transaction.custom_category)
        ).join(Account).join(Credential).filter(
            Transaction.user_id == current_user.id,
            Transaction.is_removed.is_(False)
        )

        if account_ids:
            query = query.filter(Transaction.account_id.in_(account_ids))

        if search_term:
            token = f"%{search_term}%"
            query = query.filter(or_(
                Transaction.name.ilike(token),
                Transaction.merchant_name.ilike(token),
                Transaction.category.ilike(token),
                func.coalesce(Transaction.payment_channel, '').ilike(token),
                Account.name.ilike(token),
                func.coalesce(Account.mask, '').ilike(token),
                Credential.institution_name.ilike(token),
                Transaction.custom_category.has(Category.label.ilike(token))
            ))

        total_count = query.count()

        sort_mapping = {
            'date': Transaction.date,
            'name': Transaction.name,
            'amount': Transaction.amount
        }
        sort_column = sort_mapping.get(sort_key, Transaction.date)
        primary_order = desc(sort_column) if sort_desc else asc(sort_column)

        secondary_order = desc(Transaction.id)
        if sort_column is Transaction.date and not sort_desc:
            secondary_order = asc(Transaction.id)

        ordered_query = query.order_by(primary_order, secondary_order)
        offset = (page - 1) * page_size
        transactions = ordered_query.offset(offset).limit(page_size).all()

        override_map = _load_overrides([txn.id for txn in transactions])
        response = [_serialize_transaction(txn, override_map) for txn in transactions]

        has_more = (page * page_size) < total_count

        return jsonify(
            transactions=response,
            page=page,
            page_size=page_size,
            total_count=total_count,
            has_more=has_more,
            sort_key=sort_key,
            sort_desc=sort_desc,
            search=search_term
        )

    return _with_schema_retry(handler)


@core.route('/api/transactions/<int:transaction_id>/category', methods=['PATCH'])
@login_required
def update_transaction_category(transaction_id):
    ensure_category_schema()

    def handler():
        txn = Transaction.query.options(
            joinedload(Transaction.account),
            joinedload(Transaction.credential),
            joinedload(Transaction.custom_category)
        ).filter_by(id=transaction_id, user_id=current_user.id).first()

        if not txn:
            return jsonify({'error': 'Transaction not found.'}), 404

        payload = request.get_json() or {}
        label = (payload.get('label') or '').strip()
        explicit_color = payload.get('color')

        override = TransactionCategoryOverride.query.filter_by(transaction_id=txn.id).first()

        if not label:
            if override:
                db.session.delete(override)
            txn.custom_category_id = None
            db.session.flush()
            apply_rules_to_transactions(current_user.id, transaction_ids=[txn.id])
            db.session.commit()
            override_map = _load_overrides([txn.id])
            return jsonify({'transaction': _serialize_transaction(txn, override_map)})

        color = None
        if explicit_color:
            try:
                color = _normalize_color(explicit_color)
            except ValueError:
                color = None

        if color is None:
            matching_rule = Category.query.filter_by(user_id=current_user.id, label=label).order_by(Category.created_at.desc(), Category.id.desc()).first()
            if matching_rule:
                color = matching_rule.color or DEFAULT_MANUAL_COLOR
            else:
                color = DEFAULT_MANUAL_COLOR

        if override is None:
            override = TransactionCategoryOverride(transaction_id=txn.id, label=label, color=color)
            db.session.add(override)
        else:
            override.label = label
            override.color = color

        txn.custom_category_id = None

        db.session.flush()
        db.session.commit()

        override_map = {txn.id: override}
        return jsonify({'transaction': _serialize_transaction(txn, override_map)})

    return _with_schema_retry(handler)


@core.route('/api/categories', methods=['GET'])
@login_required
def list_categories():
    ensure_category_schema()

    def handler():
        rules = Category.query.filter_by(user_id=current_user.id).order_by(Category.created_at.desc(), Category.id.desc()).all()
        return jsonify({
            'categories': [_serialize_category(rule) for rule in rules],
            'labels': _collect_category_labels(current_user.id)
        })

    return _with_schema_retry(handler)


@core.route('/api/categories', methods=['POST'])
@login_required
def create_category_rule():
    ensure_category_schema()
    def handler():
        payload = request.get_json() or {}
        text_to_match = (payload.get('text_to_match') or '').strip()
        label = (_extract_label(payload) or '').strip()

        if not text_to_match or not label:
            return jsonify({'error': 'Both text_to_match and label are required.'}), 400

        if len(text_to_match) > 512:
            text_to_match = text_to_match[:512]
        if len(label) > 255:
            label = label[:255]

        field_to_match = _resolve_rule_field(payload.get('field_to_match'))
        transaction_type = _resolve_rule_type(payload.get('transaction_type'))

        try:
            amount_min = _parse_decimal_value(payload.get('amount_min'))
            amount_max = _parse_decimal_value(payload.get('amount_max'))
            color = _normalize_color(payload.get('color'))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            return jsonify({'error': 'Amount >= cannot be greater than Amount <='}), 400

        rule = Category(
            user_id=current_user.id,
            text_to_match=text_to_match,
            label=label,
            field_to_match=field_to_match,
            transaction_type=transaction_type,
            amount_min=amount_min,
            amount_max=amount_max,
            color=color
        )
        db.session.add(rule)
        db.session.flush()

        summary = apply_category_rules(current_user.id)
        db.session.commit()

        return jsonify({
            'category': _serialize_category(rule),
            'summary': summary,
            'labels': _collect_category_labels(current_user.id)
        }), 201

    return _with_schema_retry(handler)


@core.route('/api/categories/<int:category_id>', methods=['PUT'])
@login_required
def update_category_rule(category_id):
    ensure_category_schema()
    def handler():
        rule = Category.query.filter_by(id=category_id, user_id=current_user.id).first()
        if not rule:
            return jsonify({'error': 'Category rule not found.'}), 404

        payload = request.get_json() or {}
        text_to_match = (payload.get('text_to_match') or '').strip()
        label = (_extract_label(payload) or '').strip()

        if not text_to_match or not label:
            return jsonify({'error': 'Both text_to_match and label are required.'}), 400

        if len(text_to_match) > 512:
            text_to_match = text_to_match[:512]
        if len(label) > 255:
            label = label[:255]

        field_to_match = _resolve_rule_field(payload.get('field_to_match'))
        transaction_type = _resolve_rule_type(payload.get('transaction_type'))

        try:
            amount_min = _parse_decimal_value(payload.get('amount_min'))
            amount_max = _parse_decimal_value(payload.get('amount_max'))
            color = _normalize_color(payload.get('color'))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            return jsonify({'error': 'Amount >= cannot be greater than Amount <='}), 400

        rule.text_to_match = text_to_match
        rule.label = label
        rule.field_to_match = field_to_match
        rule.transaction_type = transaction_type
        rule.amount_min = amount_min
        rule.amount_max = amount_max
        rule.color = color

        db.session.flush()

        summary = apply_category_rules(current_user.id)
        db.session.commit()

        return jsonify({
            'category': _serialize_category(rule),
            'summary': summary,
            'labels': _collect_category_labels(current_user.id)
        })

    return _with_schema_retry(handler)


@core.route('/api/categories/<int:category_id>', methods=['DELETE'])
@login_required
def delete_category_rule(category_id):
    ensure_category_schema()
    def handler():
        rule = Category.query.filter_by(id=category_id, user_id=current_user.id).first()
        if not rule:
            return jsonify({'error': 'Category rule not found.'}), 404

        db.session.delete(rule)
        db.session.flush()

        summary = apply_category_rules(current_user.id)
        db.session.commit()

        return jsonify({
            'deleted': category_id,
            'summary': summary,
            'labels': _collect_category_labels(current_user.id)
        })

    return _with_schema_retry(handler)

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
