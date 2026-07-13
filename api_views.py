"""api_views.py — ExMint API v1 blueprint

A machine-oriented API layer that mirrors the UI's core actions.
Designed for programmatic access: sync, query, categorize.
"""

from flask import Blueprint, jsonify, request, current_app, g
from flask_login import login_required, current_user
from models import (
    db,
    Credential,
    Account,
    Transaction,
    CustomCategory,
    CategoryRule,
    TransactionCategoryOverride,
    ApiKey,
)
from sqlalchemy import and_, or_, func, asc, desc
from sqlalchemy.orm import joinedload, aliased
from decimal import Decimal
from datetime import datetime, date
import json
import hashlib
import secrets
from uuid import uuid4
import plaid
from werkzeug.security import check_password_hash

from config import Config
from version import __version__ as VERSION

# Reuse internal helpers from core_views to stay in sync with UI behaviour.
from core_views import (
    _sync_credential_transactions,
    _parse_transaction_filters,
    _build_transactions_query,
    _serialize_transaction,
    _load_overrides,
    _serialize_custom_category,
    _serialize_category,
    _collect_category_labels,
    _collect_custom_category_stats,
    _find_custom_category,
    _get_or_create_custom_category,
    _normalize_category_name,
    _normalize_color,
    _validate_category_name,
    _resolve_rule_field,
    _resolve_rule_type,
    _parse_decimal_value,
    _extract_label,
    apply_category_rules,
    apply_rules_to_transactions,
    ensure_category_schema,
    _with_schema_retry,
    DEFAULT_MANUAL_COLOR,
    UNCATEGORIZED_LABEL,
    FALLBACK_CATEGORY_COLOR,
    _collect_spending_summary,
)

api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# ---------------------------------------------------------------------------
#  API Key authentication
# ---------------------------------------------------------------------------

def _hash_api_key(raw_key):
    """Hash a raw API key for storage using SHA-256."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_api_key():
    """Generate a secure random API key with a readable prefix."""
    raw = secrets.token_hex(32)  # 64 hex chars = 256 bits
    prefix = raw[:8]  # first 8 chars for identification
    return f"exm_{prefix}_{raw[8:]}", raw, prefix


def _lookup_api_user(raw_key):
    """Look up a user by API key. Returns the User or None."""
    if not raw_key:
        return None
    key_hash = _hash_api_key(raw_key)
    record = ApiKey.query.filter_by(key_hash=key_hash, is_active=True).first()
    if record:
        record.last_used_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        from models import User
        return db.session.get(User, record.user_id)
    return None


def require_api_auth(f):
    """Decorator that authenticates via X-API-Key header or Flask-Login session.

    The resolved user is available as ``g.api_user`` for endpoint use.
    Returns 401 JSON if neither method provides a valid user.
    """
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key:
            user = _lookup_api_user(api_key)
            if user is None:
                return jsonify({'error': 'Invalid or inactive API key.'}), 401
            g.api_user = user
            return f(*args, **kwargs)

        # Fall back to Flask-Login session auth
        if current_user.is_authenticated:
            g.api_user = current_user._get_current_object()
            return f(*args, **kwargs)

        return jsonify({'error': 'Authentication required. Provide X-API-Key header or log in.'}), 401
    return decorated


# ---------------------------------------------------------------------------
#  Sync
# ---------------------------------------------------------------------------

@api_v1.route('/sync', methods=['POST'])
@require_api_auth
def sync_all():
    """Sync transactions for all active institutions.

    Returns the same per-institution summary the UI shows:
    added/modified/removed counts and requires_update flag.

    Response:
    {
      "summary": [
        {
          "credential_id": 1,
          "institution_name": "Chase",
          "added": 12,
          "modified": 0,
          "removed": 0,
          "requires_update": false
        }
      ],
      "errors": [],
      "categories": {"rules_processed": 5, ...},
      "version": "1.4.4"
    }
    """
    ensure_category_schema()

    def handler():
        user = g.api_user
        active_creds = Credential.query.filter_by(
            user_id=user.id, status='Active'
        ).all()

        summary = []
        errors = []
        category_summary = None

        for cred in active_creds:
            try:
                counts, cred_error = _sync_credential_transactions(
                    user, cred, from_webhook=False
                )
                db.session.commit()
                summary.append({
                    'credential_id': cred.id,
                    'institution_name': cred.institution_name,
                    'added': counts['added'],
                    'modified': counts['modified'],
                    'removed': counts['removed'],
                    'requires_update': cred.requires_update,
                })
                if cred_error:
                    errors.append({
                        'credential_id': cred.id,
                        'institution_name': cred.institution_name,
                        **cred_error,
                    })
            except plaid.ApiException as e:
                errors.append({
                    'credential_id': cred.id,
                    'institution_name': cred.institution_name,
                    'error_code': 'DEVELOPMENT_ENVIRONMENT_BROWNOUT',
                    'error_message': (
                        'Plaid Dev environment is undergoing a scheduled '
                        'brownout. Please try again later.'
                    ),
                })
                db.session.rollback()
            except Exception as exc:
                current_app.logger.exception(
                    "API sync failed for credential %s", cred.id
                )
                errors.append({
                    'credential_id': cred.id,
                    'institution_name': cred.institution_name,
                    'error_message': str(exc),
                })
                db.session.rollback()

        has_rules = (
            CategoryRule.query.filter_by(user_id=user.id).first() is not None
        )
        if has_rules:
            category_summary = apply_category_rules(user.id)

        db.session.commit()
        status_code = 200 if not errors else 207
        return jsonify({
            'summary': summary,
            'errors': errors,
            'version': VERSION,
            'categories': category_summary,
        }), status_code

    return _with_schema_retry(handler)


# ---------------------------------------------------------------------------
#  Transactions — query with all filters
# ---------------------------------------------------------------------------

@api_v1.route('/transactions', methods=['GET'])
@require_api_auth
def get_transactions():
    """Query transactions with the same filters as the UI.

    Query params (all optional):
      page              int    Page number (default 1)
      page_size         int    Items per page (default 200, max 500)
      sort_key          str    One of: date, name, amount (default date)
      sort_desc         bool   Sort descending (default true)
      search            str    Free-text search across name/merchant/description
      start_date        str    ISO date (YYYY-MM-DD) — inclusive
      end_date          str    ISO date (YYYY-MM-DD) — inclusive
      account_ids       str    Comma-separated account IDs
      institution_ids   str    Comma-separated institution/credential IDs
      min_amount        str|num Minimum amount (absolute)
      max_amount        str|num Maximum amount (absolute)
      type              str    Filter: 'credit' or 'debit'
      custom_category_id str   Category ID, 'uncategorized', or omit
      is_new            bool   Only new transactions (not yet seen)
      pending           bool   Only pending transactions

    Returns same shape as /api/transactions in the UI.
    """
    ensure_category_schema()

    def handler():
        user_id = g.api_user.id
        args = request.args

        # Parse base filters using the same parser core_views uses.
        base = _parse_transaction_filters(args)

        # Additional filters not covered by the core parser.
        institution_ids = _parse_int_list(args.get('institution_ids', ''))
        transaction_type = (args.get('type') or '').strip().lower()
        transaction_type = (
            transaction_type if transaction_type in ('credit', 'debit') else None
        )
        is_new = (args.get('is_new') or '').strip().lower() in ('true', '1', 'yes')
        pending_flag = (args.get('pending') or '').strip().lower() in ('true', '1', 'yes')

        # Build the base query via core_views logic.
        query = _build_transactions_query(user_id, base)

        # Apply extra filters.
        if institution_ids:
            query = query.filter(Transaction.credential_id.in_(institution_ids))

        if transaction_type == 'debit':
            query = query.filter(Transaction.amount > 0)
        elif transaction_type == 'credit':
            query = query.filter(Transaction.amount < 0)

        if is_new:
            query = query.filter(Transaction.is_new.is_(True))

        if pending_flag:
            query = query.filter(Transaction.pending.is_(True))

        total_count = query.count()

        # Sorting (must match core_views logic)
        sort_mapping = {
            'date': Transaction.date,
            'name': Transaction.name,
            'amount': Transaction.amount,
        }
        sort_key = base['sort_key']
        sort_desc = base['sort_desc']
        sort_col = sort_mapping.get(sort_key, Transaction.date)
        primary_order = desc(sort_col) if sort_desc else asc(sort_col)
        secondary_order = desc(Transaction.id)
        if sort_col is Transaction.date and not sort_desc:
            secondary_order = asc(Transaction.id)

        page = base['page']
        page_size = base['page_size']
        ordered = query.order_by(primary_order, secondary_order)
        offset = (page - 1) * page_size
        txn_rows = ordered.offset(offset).limit(page_size).all()

        override_map = _load_overrides([t.id for t in txn_rows])
        serialized = [
            _serialize_transaction(t, override_map) for t in txn_rows
        ]

        has_more = (page * page_size) < total_count

        return jsonify({
            'transactions': serialized,
            'page': page,
            'page_size': page_size,
            'total_count': total_count,
            'has_more': has_more,
            'sort_key': sort_key,
            'sort_desc': sort_desc,
            'filters': {
                'start_date': base['start_date'].isoformat() if base['start_date'] else None,
                'end_date': base['end_date'].isoformat() if base['end_date'] else None,
                'min_amount': str(base['min_amount']) if base['min_amount'] is not None else None,
                'max_amount': str(base['max_amount']) if base['max_amount'] is not None else None,
                'custom_category_id': base['custom_category_param'] or None,
                'transaction_type': transaction_type,
            },
        })

    return _with_schema_retry(handler)


@api_v1.route('/transactions/uncategorized', methods=['GET'])
@require_api_auth
def get_uncategorized():
    """Shortcut: get uncategorized transactions in a date range.

    Query params:
      start_date   str    ISO date (defaults to 30 days ago)
      end_date     str    ISO date (defaults to today)
      page         int    (default 1)
      page_size    int    (default 200)

    Returns the same shape as GET /transactions.
    """
    ensure_category_schema()

    def handler():
        user_id = g.api_user.id
        args = request.args
        end = _parse_date(args.get('end_date')) or date.today()
        start = _parse_date(args.get('start_date')) or (
            end - __import__('datetime').timedelta(days=30)
        )
        try:
            page = max(1, int(args.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = max(1, min(500, int(args.get('page_size', 200))))
        except (TypeError, ValueError):
            page_size = 200

        # Uncategorized = no custom_category_id, no override.
        override_alias = aliased(TransactionCategoryOverride)
        query = (
            Transaction.query.options(
                joinedload(Transaction.account),
                joinedload(Transaction.credential),
                joinedload(Transaction.custom_category),
            )
            .outerjoin(
                override_alias,
                override_alias.transaction_id == Transaction.id,
            )
            .filter(
                Transaction.user_id == user_id,
                Transaction.is_removed.is_(False),
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.custom_category_id.is_(None),
                override_alias.custom_category_id.is_(None),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
        )
        total_count = query.count()
        offset = (page - 1) * page_size
        txn_rows = query.offset(offset).limit(page_size).all()
        override_map = _load_overrides([t.id for t in txn_rows])
        serialized = [
            _serialize_transaction(t, override_map) for t in txn_rows
        ]
        has_more = (page * page_size) < total_count

        return jsonify({
            'transactions': serialized,
            'page': page,
            'page_size': page_size,
            'total_count': total_count,
            'has_more': has_more,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
        })

    return _with_schema_retry(handler)


# ---------------------------------------------------------------------------
#  Transaction category assignment (single)
# ---------------------------------------------------------------------------

@api_v1.route('/transactions/<int:transaction_id>/category', methods=['PATCH'])
@require_api_auth
def set_transaction_category(transaction_id):
    """Assign a custom category to a single transaction.

    Body (JSON):
      {
        "label": "Category Name",           # required — sets or creates category
        "color": "#FF5733",                 # optional hex colour
        "force_create": true                # optional — bypass Plaid-name conflict check
      }

    Pass label=null or label="" to clear the manual override.

    Returns the updated transaction object.
    """
    ensure_category_schema()

    def handler():
        txn = Transaction.query.options(
            joinedload(Transaction.account),
            joinedload(Transaction.credential),
            joinedload(Transaction.custom_category),
        ).filter_by(id=transaction_id, user_id=g.api_user.id).first()

        if not txn:
            return jsonify({'error': 'Transaction not found.'}), 404

        payload = request.get_json() or {}
        raw_label = payload.get('label')
        label = _normalize_category_name(raw_label)
        explicit_color = payload.get('color')
        force_create = payload.get('force_create', False)

        override = TransactionCategoryOverride.query.filter_by(
            transaction_id=txn.id
        ).first()

        if not label:
            if override:
                db.session.delete(override)
            txn.custom_category_id = None
            db.session.flush()
            apply_rules_to_transactions(
                g.api_user.id, transaction_ids=[txn.id]
            )
            db.session.commit()
            override_map = _load_overrides([txn.id])
            return jsonify({
                'transaction': _serialize_transaction(txn, override_map)
            })

        plaid_cats = _extract_category_list(txn.category)
        fallback_label = ' / '.join(plaid_cats) if plaid_cats else None
        plaid_candidates = [fallback_label] if fallback_label else []

        existing = _find_custom_category(g.api_user.id, label)
        normalized_color = None
        if explicit_color:
            try:
                normalized_color = _normalize_color(explicit_color)
            except ValueError:
                normalized_color = None

        if existing:
            category = existing
            if normalized_color and category.color != normalized_color:
                category.color = normalized_color
        else:
            trimmed = _normalize_category_name(label)
            if len(trimmed) < 3:
                return jsonify({
                    'error': 'Category name must be at least 3 characters.'
                }), 400
            if not force_create:
                lowered = trimmed.lower()
                for candidate in plaid_candidates:
                    if not candidate:
                        continue
                    c_trimmed = _normalize_category_name(candidate)
                    if c_trimmed and lowered == c_trimmed.lower():
                        return jsonify({
                            'confirmation_required': True,
                            'message': (
                                'An Automatic category with this name already '
                                'exists. Set force_create=true to override.'
                            ),
                        }), 409

            category = CustomCategory(
                user_id=g.api_user.id,
                name=trimmed,
                color=normalized_color or DEFAULT_MANUAL_COLOR,
            )
            db.session.add(category)
            db.session.flush()

        if override is None:
            override = TransactionCategoryOverride(
                transaction_id=txn.id, custom_category_id=category.id
            )
            db.session.add(override)
        else:
            override.custom_category_id = category.id

        txn.custom_category_id = None
        db.session.commit()

        override_map = _load_overrides([txn.id])
        return jsonify({
            'transaction': _serialize_transaction(txn, override_map)
        })

    return _with_schema_retry(handler)


@api_v1.route('/transactions/bulk-category', methods=['PATCH'])
@require_api_auth
def bulk_set_transaction_category():
    """Assign a custom category to multiple transactions at once.

    Body (JSON):
      {
        "transaction_ids": [1, 2, 3],       # required — max 500
        "label": "Category Name",            # required — sets or creates category
        "color": "#FF5733",                  # optional
        "force_create": false                # optional
      }

    Pass label=null to clear manual overrides on the given transactions.

    Returns the updated transactions array.
    """
    ensure_category_schema()

    def handler():
        payload = request.get_json() or {}
        txn_ids = payload.get('transaction_ids', [])
        raw_label = payload.get('label')
        label = _normalize_category_name(raw_label)
        explicit_color = payload.get('color')
        force_create = payload.get('force_create', False)

        if not txn_ids or not isinstance(txn_ids, list):
            return jsonify({
                'error': 'transaction_ids must be a non-empty list.'
            }), 400
        if len(txn_ids) > 500:
            return jsonify({
                'error': 'Cannot update more than 500 transactions at once.'
            }), 400

        transactions = (
            Transaction.query.options(
                joinedload(Transaction.account),
                joinedload(Transaction.credential),
                joinedload(Transaction.custom_category),
            )
            .filter(
                Transaction.id.in_(txn_ids),
                Transaction.user_id == g.api_user.id,
            )
            .all()
        )

        if len(transactions) != len(set(txn_ids)):
            return jsonify({'error': 'One or more transactions not found.'}), 404

        real_ids = [t.id for t in transactions]

        if not label:
            overrides = TransactionCategoryOverride.query.filter(
                TransactionCategoryOverride.transaction_id.in_(real_ids)
            ).all()
            for o in overrides:
                db.session.delete(o)
            for t in transactions:
                t.custom_category_id = None
            db.session.flush()
            apply_rules_to_transactions(
                g.api_user.id, transaction_ids=real_ids
            )
            db.session.commit()
            override_map = _load_overrides(real_ids)
            return jsonify({
                'transactions': [
                    _serialize_transaction(t, override_map) for t in transactions
                ]
            })

        normalized_color = None
        if explicit_color:
            try:
                normalized_color = _normalize_color(explicit_color)
            except ValueError:
                normalized_color = None

        existing = _find_custom_category(g.api_user.id, label)
        if existing:
            category = existing
            if normalized_color and category.color != normalized_color:
                category.color = normalized_color
        else:
            trimmed = _normalize_category_name(label)
            if len(trimmed) < 3:
                return jsonify({
                    'error': 'Category name must be at least 3 characters.'
                }), 400
            if not force_create:
                for txn in transactions:
                    plaid_cats = _extract_category_list(txn.category)
                    fb = ' / '.join(plaid_cats) if plaid_cats else None
                    if fb:
                        ct = _normalize_category_name(fb)
                        if ct and trimmed.lower() == ct.lower():
                            return jsonify({
                                'confirmation_required': True,
                                'message': (
                                    'An Automatic category with this name '
                                    'already exists. Set force_create=true.'
                                ),
                            }), 409

            category = CustomCategory(
                user_id=g.api_user.id,
                name=trimmed,
                color=normalized_color or DEFAULT_MANUAL_COLOR,
            )
            db.session.add(category)
            db.session.flush()

        existing_overrides = {
            o.transaction_id: o
            for o in TransactionCategoryOverride.query.filter(
                TransactionCategoryOverride.transaction_id.in_(real_ids)
            ).all()
        }

        for t in transactions:
            t.custom_category_id = None
            o = existing_overrides.get(t.id)
            if o is None:
                o = TransactionCategoryOverride(
                    transaction_id=t.id, custom_category_id=category.id
                )
                db.session.add(o)
            else:
                o.custom_category_id = category.id

        db.session.commit()
        override_map = _load_overrides(real_ids)
        return jsonify({
            'transactions': [
                _serialize_transaction(t, override_map) for t in transactions
            ]
        })

    return _with_schema_retry(handler)


# ---------------------------------------------------------------------------
#  Custom categories (CRUD)
# ---------------------------------------------------------------------------

@api_v1.route('/categories', methods=['GET'])
@require_api_auth
def list_categories():
    """List all custom categories for the current user.

    Returns categories with rule_count, transaction_count, and override_count.
    """
    ensure_category_schema()

    def handler():
        cats = (
            CustomCategory.query.filter_by(user_id=g.api_user.id)
            .order_by(func.lower(CustomCategory.name).asc(), CustomCategory.id.asc())
            .all()
        )
        cat_ids = [c.id for c in cats]
        r_counts, t_counts, o_counts = _collect_custom_category_stats(
            g.api_user.id, cat_ids
        )
        serialized = [
            _serialize_custom_category(c, {
                'rule_count': int(r_counts.get(c.id, 0)),
                'transaction_count': int(t_counts.get(c.id, 0)),
                'override_count': int(o_counts.get(c.id, 0)),
            })
            for c in cats
        ]
        return jsonify({
            'categories': serialized,
            'labels': _collect_category_labels(g.api_user.id),
        })

    return _with_schema_retry(handler)


@api_v1.route('/categories', methods=['POST'])
@require_api_auth
def create_category():
    """Create a new custom category.

    Body (JSON):
      {
        "name": "Groceries",       # required, min 3 chars
        "color": "#FF5733"         # optional hex colour
      }

    Returns the created category.
    """
    ensure_category_schema()

    def handler():
        payload = request.get_json() or {}
        raw_name = payload.get('name') or payload.get('label')
        try:
            name = _validate_category_name(raw_name, plaid_candidates=None)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if len(name) > 255:
            name = name[:255]
        if not name:
            return jsonify({'error': 'Name is required.'}), 400

        color_value = payload.get('color') or DEFAULT_MANUAL_COLOR
        try:
            color = _normalize_color(color_value)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        existing = _find_custom_category(g.api_user.id, name)
        if existing:
            return jsonify({'error': 'A category with this name already exists.'}), 400

        cat = CustomCategory(
            user_id=g.api_user.id, name=name, color=color
        )
        db.session.add(cat)
        db.session.commit()

        return jsonify({
            'category': _serialize_custom_category(cat, {
                'rule_count': 0, 'transaction_count': 0, 'override_count': 0,
            }),
            'labels': _collect_category_labels(g.api_user.id),
        }), 201

    return _with_schema_retry(handler)


@api_v1.route('/categories/<int:category_id>', methods=['PUT'])
@require_api_auth
def update_category(category_id):
    """Update a custom category's name and/or colour."""
    ensure_category_schema()

    def handler():
        cat = CustomCategory.query.filter_by(
            id=category_id, user_id=g.api_user.id
        ).first()
        if not cat:
            return jsonify({'error': 'Custom category not found.'}), 404

        payload = request.get_json() or {}
        name = payload.get('name')
        color_value = payload.get('color')
        updated = False

        if name is not None:
            try:
                trimmed = _validate_category_name(name, plaid_candidates=None)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400
            if len(trimmed) > 255:
                trimmed = trimmed[:255]
            if trimmed.lower() != (cat.name or '').lower():
                dup = CustomCategory.query.filter(
                    CustomCategory.user_id == g.api_user.id,
                    func.lower(CustomCategory.name) == trimmed.lower(),
                    CustomCategory.id != cat.id,
                ).first()
                if dup:
                    return jsonify({
                        'error': 'Another category with this name already exists.'
                    }), 400
                cat.name = trimmed
                updated = True

        if color_value is not None:
            try:
                nc = _normalize_color(color_value)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400
            if cat.color != nc:
                cat.color = nc
                updated = True

        if updated:
            db.session.flush()
        db.session.commit()

        r_counts, t_counts, o_counts = _collect_custom_category_stats(
            g.api_user.id, [cat.id]
        )
        return jsonify({
            'category': _serialize_custom_category(cat, {
                'rule_count': int(r_counts.get(cat.id, 0)),
                'transaction_count': int(t_counts.get(cat.id, 0)),
                'override_count': int(o_counts.get(cat.id, 0)),
            }),
            'labels': _collect_category_labels(g.api_user.id),
        })

    return _with_schema_retry(handler)


@api_v1.route('/categories/<int:category_id>', methods=['DELETE'])
@require_api_auth
def delete_category(category_id):
    """Delete a custom category.  Unlinks it from all transactions."""
    ensure_category_schema()

    def handler():
        cat = CustomCategory.query.filter_by(
            id=category_id, user_id=g.api_user.id
        ).first()
        if not cat:
            return jsonify({'error': 'Custom category not found.'}), 404

        db.session.delete(cat)
        db.session.commit()
        return jsonify({'deleted': category_id})

    return _with_schema_retry(handler)


# ---------------------------------------------------------------------------
#  Category rules (automatic matching rules)
# ---------------------------------------------------------------------------

@api_v1.route('/categories/rules', methods=['GET'])
@require_api_auth
def list_category_rules():
    """List all automatic categorisation rules.

    Each rule defines text/amount/type conditions that auto-assign
    a custom category when matched.
    """
    ensure_category_schema()

    def handler():
        rules = (
            CategoryRule.query.options(joinedload(CategoryRule.category))
            .filter_by(user_id=g.api_user.id)
            .order_by(CategoryRule.created_at.desc(), CategoryRule.id.desc())
            .all()
        )
        return jsonify({
            'rules': [_serialize_category(r) for r in rules],
            'labels': _collect_category_labels(g.api_user.id),
        })

    return _with_schema_retry(handler)


@api_v1.route('/categories/rules', methods=['POST'])
@require_api_auth
def create_category_rule():
    """Create an automatic categorisation rule.

    Body (JSON):
      {
        "text_to_match": "WALMART",        # required — string to search for
        "field_to_match": "description",    # optional — "description" (default), "merchant", "category"
        "category_id": 5,                   # optional — existing category id
        "label": "Groceries",               # optional — category name (used if category_id absent)
        "transaction_type": "debit",        # optional — "credit", "debit", or null/omit for both
        "amount_min": 10.00,                # optional — minimum absolute amount
        "amount_max": 200.00,               # optional — maximum absolute amount
        "color": "#FF5733"                  # optional — colour when creating a new category
      }

    After creation, all existing transactions are re-evaluated against rules.
    Returns the created rule + a summary of transactions matched/updated.
    """
    ensure_category_schema()

    def handler():
        payload = request.get_json() or {}
        text = (payload.get('text_to_match') or '').strip()
        cat_id = payload.get('category_id')
        cat_name = (_extract_label(payload) or '').strip()

        if not text:
            return jsonify({'error': 'text_to_match is required.'}), 400
        if not cat_id and not cat_name:
            return jsonify({
                'error': 'category_id or label is required.'
            }), 400

        if len(text) > 512:
            text = text[:512]
        if cat_name and len(cat_name) > 255:
            cat_name = cat_name[:255]

        field = _resolve_rule_field(payload.get('field_to_match'))
        txn_type = _resolve_rule_type(payload.get('transaction_type'))

        try:
            amt_min = _parse_decimal_value(payload.get('amount_min'))
            amt_max = _parse_decimal_value(payload.get('amount_max'))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        if amt_min is not None and amt_max is not None and amt_min > amt_max:
            return jsonify({
                'error': 'amount_min cannot be greater than amount_max.'
            }), 400

        if cat_id:
            try:
                cat_id = int(cat_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid category_id.'}), 400
            category = CustomCategory.query.filter_by(
                id=cat_id, user_id=g.api_user.id
            ).first()
            if not category:
                return jsonify({'error': 'Category not found.'}), 404
        else:
            try:
                category = _get_or_create_custom_category(
                    g.api_user.id,
                    cat_name,
                    color=payload.get('color'),
                )
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

        rule = CategoryRule(
            user_id=g.api_user.id,
            category_id=category.id,
            text_to_match=text,
            field_to_match=field,
            transaction_type=txn_type,
            amount_min=amt_min,
            amount_max=amt_max,
        )
        rule.category = category
        db.session.add(rule)
        db.session.flush()

        summary = apply_category_rules(g.api_user.id)
        db.session.commit()

        return jsonify({
            'rule': _serialize_category(rule),
            'summary': summary,
            'labels': _collect_category_labels(g.api_user.id),
        }), 201

    return _with_schema_retry(handler)


@api_v1.route('/categories/rules/<int:rule_id>', methods=['PUT'])
@require_api_auth
def update_category_rule(rule_id):
    """Update an automatic categorisation rule."""
    ensure_category_schema()

    def handler():
        rule = CategoryRule.query.options(
            joinedload(CategoryRule.category)
        ).filter_by(id=rule_id, user_id=g.api_user.id).first()
        if not rule:
            return jsonify({'error': 'Category rule not found.'}), 404

        payload = request.get_json() or {}
        text = (payload.get('text_to_match') or '').strip()
        cat_id = payload.get('category_id')
        cat_name = (_extract_label(payload) or '').strip()

        if not text:
            return jsonify({'error': 'text_to_match is required.'}), 400
        if not cat_id and not cat_name:
            return jsonify({
                'error': 'category_id or label is required.'
            }), 400

        if len(text) > 512:
            text = text[:512]
        if cat_name and len(cat_name) > 255:
            cat_name = cat_name[:255]

        field = _resolve_rule_field(payload.get('field_to_match'))
        txn_type = _resolve_rule_type(payload.get('transaction_type'))

        try:
            amt_min = _parse_decimal_value(payload.get('amount_min'))
            amt_max = _parse_decimal_value(payload.get('amount_max'))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        if amt_min is not None and amt_max is not None and amt_min > amt_max:
            return jsonify({
                'error': 'amount_min cannot be greater than amount_max.'
            }), 400

        if cat_id:
            try:
                cat_id = int(cat_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid category_id.'}), 400
            category = CustomCategory.query.filter_by(
                id=cat_id, user_id=g.api_user.id
            ).first()
            if not category:
                return jsonify({'error': 'Category not found.'}), 404
        else:
            try:
                category = _get_or_create_custom_category(
                    g.api_user.id,
                    cat_name,
                    color=payload.get('color'),
                )
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

        rule.text_to_match = text
        rule.field_to_match = field
        rule.transaction_type = txn_type
        rule.amount_min = amt_min
        rule.amount_max = amt_max
        rule.category_id = category.id
        rule.category = category

        db.session.flush()
        summary = apply_category_rules(g.api_user.id)
        db.session.commit()

        return jsonify({
            'rule': _serialize_category(rule),
            'summary': summary,
            'labels': _collect_category_labels(g.api_user.id),
        })

    return _with_schema_retry(handler)


@api_v1.route('/categories/rules/<int:rule_id>', methods=['DELETE'])
@require_api_auth
def delete_category_rule(rule_id):
    """Delete an automatic categorisation rule (re-evaluates transactions)."""
    ensure_category_schema()

    def handler():
        rule = CategoryRule.query.filter_by(
            id=rule_id, user_id=g.api_user.id
        ).first()
        if not rule:
            return jsonify({'error': 'Category rule not found.'}), 404

        db.session.delete(rule)
        db.session.flush()
        summary = apply_category_rules(g.api_user.id)
        db.session.commit()

        return jsonify({
            'deleted': rule_id,
            'summary': summary,
            'labels': _collect_category_labels(g.api_user.id),
        })

    return _with_schema_retry(handler)


# ---------------------------------------------------------------------------
#  Accounts & Institutions
# ---------------------------------------------------------------------------

@api_v1.route('/accounts', methods=['GET'])
@require_api_auth
def list_accounts():
    """List active accounts, optionally filtered by institution.

    Query params:
      institution_id   int   Filter accounts belonging to this credential
    """
    user_id = g.api_user.id
    inst_id = request.args.get('institution_id')

    query = Account.query.join(Credential).filter(
        Credential.user_id == user_id,
        Credential.status.in_(['Active', 'Revoked']),
    )
    if inst_id:
        try:
            query = query.filter(Credential.id == int(inst_id))
        except (TypeError, ValueError):
            pass
    query = query.filter(Account.status.in_(['Active', 'Revoked']))

    accounts = [
        {
            'id': a.id,
            'name': a.name,
            'mask': a.mask,
            'type': a.type,
            'subtype': a.subtype,
            'is_enabled': a.is_enabled,
            'credential_id': a.credential_id,
            'institution_name': a.credential.institution_name if a.credential else None,
            'status': a.status,
        }
        for a in query.all()
    ]
    return jsonify({'accounts': accounts})


@api_v1.route('/institutions', methods=['GET'])
@require_api_auth
def list_institutions():
    """List all active institutions (credentials) for the current user."""
    banks = Credential.query.filter_by(
        user_id=g.api_user.id
    ).filter(
        Credential.status.in_(['Active', 'Revoked'])
    ).all()
    result = []
    for b in banks:
        accounts = [
            {
                'id': a.id,
                'name': a.name,
                'mask': a.mask,
                'type': a.type,
                'subtype': a.subtype,
                'is_enabled': a.is_enabled,
                'status': a.status,
            }
            for a in b.accounts
            if a.status in ('Active', 'Revoked')
        ]
        result.append({
            'id': b.id,
            'institution_name': b.institution_name,
            'requires_update': b.requires_update,
            'soft_disconnected': b.soft_disconnected,
            'revoked': b.status == 'Revoked',
            'accounts': accounts,
        })
    return jsonify({'institutions': result})


# ---------------------------------------------------------------------------
#  Budget & Spending Summary
# ---------------------------------------------------------------------------

@api_v1.route('/budgets/summary', methods=['GET'])
@require_api_auth
def budget_summary():
    """Return current month's budget/spending summary with per-category detail.

    Query params:
      year    int   (default: current year)
      month   int   (default: current month)

    Returns the same structure as _collect_spending_summary but
    filtered to the requested year/month for compactness.
    """
    from datetime import date as dt_date
    today = dt_date.today()
    target_year = request.args.get('year', type=int) or today.year
    target_month = request.args.get('month', type=int) or today.month

    spending = _collect_spending_summary(g.api_user.id)
    for y in spending.get('years', []):
        if y['year'] == target_year:
            for m in y.get('months', []):
                if m['month'] == target_month:
                    # Keep only what the agent needs
                    compact = {
                        'year': target_year,
                        'month': target_month,
                        'budget_total': m['budget_total'],
                        'spending_subtotal': m['spending_subtotal'],
                        'remainder_total': m['remainder_total'],
                        'spending_categories': [],
                        'income_categories': m.get('income_categories', []),
                    }
                    for cat in m['spending_categories']:
                        if cat.get('_budget_excluded'):
                            continue  # skip excluded for agent summary
                        compact['spending_categories'].append({
                            'label': cat['label'],
                            'value': cat['value'],
                            'budget': cat.get('budget'),
                            'remainder': cat.get('remainder'),
                            'rollover_amount': cat.get('_rollover_amount'),
                            'is_everything_else': cat.get('_is_everything_else', False),
                        })
                    return jsonify({'budget_summary': compact})

    return jsonify({'budget_summary': None})


# ---------------------------------------------------------------------------
#  API Key management
# ---------------------------------------------------------------------------

@api_v1.route('/admin/api-keys', methods=['GET'])
@login_required
def list_api_keys():
    """List API keys for the currently logged-in user (session only)."""
    keys = ApiKey.query.filter_by(user_id=current_user.id).order_by(
        ApiKey.created_at.desc()
    ).all()
    return jsonify({
        'api_keys': [
            {
                'id': k.id,
                'key_prefix': k.key_prefix + '...',
                'name': k.name,
                'is_active': k.is_active,
                'created_at': k.created_at.isoformat() if k.created_at else None,
                'last_used_at': k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]
    })


@api_v1.route('/admin/api-keys', methods=['POST'])
@login_required
def create_api_key():
    """Generate a new API key. Returns the full key **once** — store it securely.

    Body (JSON):
      {"name": "Agent API Key"}   # optional human-friendly label

    Response includes the raw key (shown only on creation).
    """
    payload = request.get_json() or {}
    name = (payload.get('name') or '').strip() or f'key_{secrets.token_hex(4)}'

    full_key, raw_key, prefix = _generate_api_key()
    key_hash = _hash_api_key(full_key)

    record = ApiKey(
        key_hash=key_hash,
        key_prefix=prefix,
        user_id=current_user.id,
        name=name,
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({
        'api_key': {
            'id': record.id,
            'name': record.name,
            'key_prefix': prefix + '...',
            'key': full_key,  # only returned once
            'created_at': record.created_at.isoformat(),
        }
    }), 201


@api_v1.route('/admin/api-keys/<int:key_id>', methods=['DELETE'])
@login_required
def revoke_api_key(key_id):
    """Revoke (deactivate) an API key. It can no longer authenticate."""
    record = ApiKey.query.filter_by(id=key_id, user_id=current_user.id).first()
    if not record:
        return jsonify({'error': 'API key not found.'}), 404
    record.is_active = False
    db.session.commit()
    return jsonify({'revoked': key_id})


# ---------------------------------------------------------------------------
#  CSV Import via API (API key auth)
# ---------------------------------------------------------------------------

import csv as _csv
from io import StringIO as _StringIO
from functools import wraps


@api_v1.route('/transactions/import-csv/analyze', methods=['POST'])
@require_api_auth
def api_csv_import_analyze():
    """Analyze CSV text or file — returns headers, auto-mapping, preview.

    Accepts:
      - JSON: {\"csv_content\": \"date,amount,...\\n2024-01-01,...\"}
      - multipart/form-data with a `file` field (same as UI)
    """
    if 'file' in request.files:
        return csv_import_analyze()

    data = request.get_json(silent=True) or {}
    csv_text = data.get('csv_content', '')
    if not csv_text:
        return jsonify(error='csv_content required'), 400

    # Manually replicate the analyze logic for JSON input
    from core_views import _auto_detect_mapping, _compute_header_hash, _preview_rows
    from models import CsvImportTemplate

    try:
        content = csv_text.encode('utf-8-sig').decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify(error='Cannot decode CSV'), 400

    reader = _csv.DictReader(_StringIO(content))
    if not reader.fieldnames:
        return jsonify(error='CSV has no headers'), 400

    headers = [h for h in reader.fieldnames if h is not None]
    rows = list(reader)
    if not rows:
        return jsonify(error='CSV has no data rows'), 400

    auto_mapping = _auto_detect_mapping(headers)

    header_hash = _compute_header_hash(headers)
    template = CsvImportTemplate.query.filter_by(
        user_id=g.api_user.id,
        header_hash=header_hash,
    ).first()

    if template:
        saved = json.loads(template.mappings)
        auto_mapping.update({h: saved.get(h) for h in headers if h in saved})

    return jsonify(
        headers=headers,
        auto_mapping={k: v for k, v in auto_mapping.items() if k is not None},
        has_template=template is not None,
        template_label=template.label if template else None,
        preview=_preview_rows(rows[:5]),
        row_count=len(rows),
    )


@api_v1.route('/transactions/import-csv/import', methods=['POST'])
@require_api_auth
def api_csv_import_execute():
    """Execute a CSV import with the given mapping.

    Accepts JSON:
      - csv_content: raw CSV text (required)
      - mapping: dict of csv_header -> field_name (required)
      - account_id: int (optional if account_number in mapping)
      - save_template: bool (optional)
      - template_label: str (required if save_template=true)
    """
    data = request.get_json(silent=True) or {}
    csv_text = data.get('csv_content', '')
    mapping = data.get('mapping', {})
    account_id = data.get('account_id')
    save_template = data.get('save_template', False)
    template_label = data.get('template_label', '')

    if not csv_text:
        return jsonify(error='csv_content required'), 400
    if not mapping:
        return jsonify(error='mapping required'), 400

    # Reuse core_views helpers
    from core_views import (
        _parse_date, _parse_amount, _auto_detect_mapping,
        _compute_header_hash,
    )

    try:
        content = csv_text.encode('utf-8-sig').decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify(error='Cannot decode CSV'), 400

    reader = _csv.DictReader(_StringIO(content))
    if not reader.fieldnames:
        return jsonify(error='CSV has no headers'), 400

    headers = [h for h in reader.fieldnames if h is not None]
    rows = list(reader)
    if not rows:
        return jsonify(error='CSV has no data rows'), 400

    header_to_field = mapping

    has_account_number_routing = any(f == 'account_number' for f in mapping.values())

    default_account = None
    if not has_account_number_routing:
        if not account_id:
            return jsonify(error='account_id required when account_number not mapped'), 400
        default_account = Account.query.join(Credential).filter(
            Account.id == account_id,
            Credential.user_id == g.api_user.id,
            Account.status == 'Active',
        ).first()
        if not default_account:
            return jsonify(error='Account not found or not active'), 404
    elif account_id:
        default_account = Account.query.join(Credential).filter(
            Account.id == account_id,
            Credential.user_id == g.api_user.id,
            Account.status == 'Active',
        ).first()

    inserted = 0
    skipped = 0
    updated = 0
    errors = []

    credential_id = default_account.credential_id if default_account else None

    # Multi-account routing by mask
    account_number_header = None
    account_by_mask = {}
    for h, f in header_to_field.items():
        if f == 'account_number':
            account_number_header = h
            break

    if account_number_header:
        all_user_accounts = Account.query.join(Credential).filter(
            Credential.user_id == g.api_user.id,
            Account.status == 'Active',
        ).all()
        for acct in all_user_accounts:
            if acct.mask:
                account_by_mask[acct.mask] = acct.id
                account_by_mask[acct.mask.lstrip('0')] = acct.id

    for row_idx, row in enumerate(rows):
        try:
            date_val = None
            name_val = None
            debit_val = None
            credit_val = None
            amount_val = None
            amount_cad_val = None
            amount_usd_val = None
            merchant_val = None
            currency_code = None

            for header, field in header_to_field.items():
                raw = row.get(header, '').strip()
                if not raw:
                    continue
                if field == 'date':
                    date_val = _parse_date(raw)
                elif field == 'description':
                    name_val = raw
                elif field == 'debit':
                    debit_val = _parse_amount(raw)
                elif field == 'credit':
                    credit_val = _parse_amount(raw)
                elif field == 'amount':
                    amount_val = _parse_amount(raw)
                elif field == 'amount_cad':
                    amount_cad_val = _parse_amount(raw)
                    currency_code = 'CAD'
                elif field == 'amount_usd':
                    amount_usd_val = _parse_amount(raw)
                    currency_code = 'USD'
                elif field == 'merchant':
                    merchant_val = raw

            final_amount = None
            if amount_cad_val is not None:
                final_amount = amount_cad_val
                currency_code = 'CAD'
            elif amount_usd_val is not None:
                final_amount = amount_usd_val
                currency_code = 'USD'
            elif debit_val is not None and credit_val is not None:
                final_amount = -(abs(debit_val)) if debit_val != 0 else credit_val
            elif debit_val is not None:
                final_amount = -(abs(debit_val))
            elif credit_val is not None:
                final_amount = abs(credit_val)
            elif amount_val is not None:
                final_amount = amount_val

            if date_val is None or name_val is None or final_amount is None:
                errors.append({'row': row_idx + 2, 'error': 'Missing required fields'})
                continue

            target_account_id = None
            if account_number_header:
                csv_acct = row.get(account_number_header, '').strip()
                lookup_key = csv_acct[-4:] if len(csv_acct) >= 4 else csv_acct
                lookup_key = lookup_key.replace('-', '').replace(' ', '')
                matched_acct_id = account_by_mask.get(lookup_key)
                if matched_acct_id:
                    target_account_id = matched_acct_id
                    matched_acct = Account.query.get(matched_acct_id)
                    if matched_acct:
                        credential_id = matched_acct.credential_id
                else:
                    last4 = csv_acct[-4:].replace('-', '').replace(' ', '')
                    matched_acct_id = account_by_mask.get(last4)
                    if matched_acct_id:
                        target_account_id = matched_acct_id
                        matched_acct = Account.query.get(matched_acct_id)
                        if matched_acct:
                            credential_id = matched_acct.credential_id

            if not target_account_id and default_account:
                target_account_id = default_account.id

            if not target_account_id:
                errors.append({'row': row_idx + 2, 'error': 'Could not determine target account'})
                continue

            existing = Transaction.query.filter(
                Transaction.account_id == target_account_id,
                Transaction.date == date_val,
                Transaction.amount == final_amount,
                Transaction.name == name_val,
                Transaction.is_removed.is_(False),
            ).first()

            if existing:
                if existing.pending:
                    existing.amount = final_amount
                    existing.name = name_val
                    if merchant_val:
                        existing.merchant_name = merchant_val
                    existing.pending = False
                    existing.is_removed = False
                    existing.is_new = True
                    updated += 1
                else:
                    skipped += 1
                continue

            # Second dedup pass: check for Plaid-synced duplicate by
            # (account_id, date, amount) only. Catches the Plaid+CSV
            # overlap where descriptions differ.
            api_existing_plaid = Transaction.query.filter(
                Transaction.account_id == target_account_id,
                Transaction.date == date_val,
                Transaction.amount == final_amount,
                Transaction.is_removed.is_(False),
                Transaction.plaid_transaction_id.isnot(None),
                ~Transaction.plaid_transaction_id.like('csv_%'),
            ).first()

            if api_existing_plaid:
                skipped += 1
                continue

            from uuid import uuid4
            new_txn = Transaction(
                plaid_transaction_id=f'csv_{uuid4().hex}',
                user_id=g.api_user.id,
                credential_id=credential_id,
                account_id=target_account_id,
                name=name_val,
                amount=final_amount,
                iso_currency_code=currency_code or 'CAD',
                merchant_name=merchant_val or name_val,
                date=date_val,
                pending=False,
                is_new=True,
            )
            db.session.add(new_txn)
            inserted += 1

        except Exception as exc:
            current_app.logger.exception('CSV import row %s error: %s', row_idx + 2, exc)
            errors.append({'row': row_idx + 2, 'error': str(exc)})

    if inserted > 0 or updated > 0:
        apply_category_rules(g.api_user.id)

    db.session.commit()

    # Save template if requested
    if save_template and template_label:
        from models import CsvImportTemplate
        header_hash = _compute_header_hash(headers)
        existing_tpl = CsvImportTemplate.query.filter_by(
            user_id=g.api_user.id,
            header_hash=header_hash,
        ).first()
        if existing_tpl:
            existing_tpl.mappings = json.dumps(mapping)
            existing_tpl.updated_at = datetime.utcnow()
        else:
            db.session.add(CsvImportTemplate(
                label=template_label,
                user_id=g.api_user.id,
                header_hash=header_hash,
                header_names=json.dumps(headers),
                mappings=json.dumps(mapping),
            ))
        db.session.commit()

    return jsonify(
        inserted=inserted,
        skipped=skipped,
        updated=updated,
        errors=errors,
    )


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _parse_int_list(raw: str):
    if not raw:
        return []
    result = []
    for part in raw.split(','):
        p = part.strip()
        if p.isdigit():
            result.append(int(p))
    return result


def _extract_category_list(raw):
    """Re-implemented locally to avoid deep import — mirrors core_views."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except (TypeError, ValueError):
        pass
    return [str(raw)] if raw else []
