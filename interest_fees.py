"""interest_fees.py — EX-07: what interest and fees cost every month.

A *charge* is an interest or fee transaction on a debt/credit account.
We detect them by category rules (text patterns) and group by month.
The report provides:
- Monthly total of all interest/fees
- Per-account breakdown
- Sub-type totals (INTEREST, OD_INTEREST, NSF, ANNUAL_FEE, OVERDRAFT, LATE_FEE, etc.)
"""

import datetime
import re
from collections import defaultdict
from statistics import median

# Sub-types of interest/fee charges we track
SUB_TYPES = [
    'INTEREST',           # Regular purchase/cash advance interest
    'OD_INTEREST',        # Overdraft interest
    'NSF',                # Non-sufficient funds fee
    'ANNUAL_FEE',         # Annual card/account fee
    'OVERDRAFT',          # Overdraft fee (flat fee, not interest)
    'LATE_FEE',           # Late payment fee
    'CASH_ADVANCE_FEE',   # Cash advance fee (not interest)
    'BALANCE_TRANSFER_FEE',  # Balance transfer fee
    'FOREIGN_TXN_FEE',    # Foreign transaction fee
]

# Patterns to auto-detect sub-type from transaction description/name
# Ordered by specificity (more specific first)
SUB_TYPE_PATTERNS = [
    ('NSF', [r'\bNSF\b', r'non.?sufficient', r'insufficient.?funds', r'returned.?item.?fee']),
    ('ANNUAL_FEE', [r'annual.*fee', r'yearly.?fee', r'membership.?fee']),
    ('OD_INTEREST', [
        r'overdraft.?interest',
        r'\bOD\b.?interest',
        r'interest.?overdraft',
        r'overdraft.?interest.?charge',
    ]),
    ('OVERDRAFT', [
        r'overdraft.?protect',      # matches "Overdraft Protect. Fee"
        r'overdraft.?fee',
        r'\bOD\b.?fee',
        r'pay.?per.?use.?overdraft.?fee',
    ]),
    ('LATE_FEE', [r'late.?fee', r'late.?payment', r'past.?due.?fee']),
    ('CASH_ADVANCE_FEE', [r'cash.?advance.?fee', r'cash.?adv.?fee']),
    ('BALANCE_TRANSFER_FEE', [r'balance.?transfer.?fee']),
    ('FOREIGN_TXN_FEE', [r'foreign.?transaction.?fee', r'foreign.?txn.?fee', r'intl.?fee']),
    # INTEREST patterns - ordered by specificity
    ('INTEREST', [
        r'cash.?advance.?interest',   # must come before generic interest
        r'purchase.?interest',
        r'loan.?interest',
        r'^interest$',                 # bare "INTEREST"
        r'\binterest\b',
    ]),
]

# Patterns that explicitly EXCLUDE a transaction from being an interest/fee charge
EXCLUDE_PATTERNS = [
    r'deposit.?interest',          # income, not a charge
    r'returned.?cheque.?-?\s*nsf', # the bounced item, not the fee
    r'interest.?payment',           # interest payment (usually principal paydown, not a charge)
    r'\bannual.?fee.?reversal\b',   # reversal handled by netting
    r'\bannual.?card.?fee.?rebate\b',
    r'\bannual.?fee.?rebate\b',
]

# Minimum amount to consider (avoid noise from tiny rounding adjustments)
MIN_CHARGE_AMOUNT = 0.01

# Lookback period for the report
LOOKBACK_DAYS = 400


def _classify_sub_type(text):
    """Classify a transaction description into a sub-type.

    Returns None if the text should be excluded (not an interest/fee charge),
    otherwise returns the sub-type string (one of SUB_TYPES).
    """
    if not text:
        return None
    low = text.lower()

    # Check for annual fee reversals/rebates FIRST (before exclusions)
    # These are positive amounts but we need to classify them for netting
    if ('annual' in low and ('reversal' in low or 'rebate' in low) and
        ('fee' in low or 'card' in low)):
        return 'ANNUAL_FEE'

    # Check exclusion patterns (but not for annual fee reversals which we handled above)
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, low, re.IGNORECASE):
            return None

    # Check classification patterns
    for sub_type, patterns in SUB_TYPE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, low, re.IGNORECASE):
                return sub_type
    return None


def _month_key(date):
    """Return YYYY-MM string for a date."""
    return date.strftime('%Y-%m')


def _parse_amount(value):
    """Parse amount to float, handling various formats."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols, commas, parentheses
        cleaned = value.replace('$', '').replace(',', '').replace('(', '-').replace(')', '')
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def detect_interest_fees(charges, today=None):
    """
    charges: list of dicts with keys:
        - date (datetime.date)
        - amount (float, negative = money out/charge in ExMint convention)
        - name (str)
        - merchant_name (str, optional)
        - custom_name (str, optional)
        - account_id (int)
        - id (int, transaction id)
        - sub_type (str, optional - pre-classified)
    Returns the report dict.
    """
    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=LOOKBACK_DAYS)

    # Filter to relevant charges:
    # - Negative amount = money out/charge in ExMint convention
    # - Must match a known interest/fee pattern (classified sub_type not None)
    # - Within date range
    # Also capture ANNUAL_FEE reversals/rebates (positive amounts) for netting
    filtered = []
    annual_fee_reversals = []  # (month_key, account_id, amount)
    for c in charges:
        amount = c.get('amount', 0)
        if not c.get('date') or not (since <= c['date'] <= today):
            continue
        text = c.get('custom_name') or c.get('name') or c.get('merchant_name') or ''
        sub_type = c.get('sub_type') or _classify_sub_type(text)

        # Check if it's an annual fee reversal/rebate (positive amount)
        low = text.lower()
        is_annual_reversal = (amount > 0 and sub_type == 'ANNUAL_FEE' and
                              ('reversal' in low or 'rebate' in low))

        if amount < -MIN_CHARGE_AMOUNT and sub_type is not None:
            # Regular charge (negative amount)
            c = dict(c)  # copy to avoid mutating input
            c['sub_type'] = sub_type
            c['amount'] = abs(amount)  # report as positive for display
            filtered.append(c)
        elif is_annual_reversal:
            # Annual fee reversal - capture for netting
            month_key = _month_key(c['date'])
            annual_fee_reversals.append((month_key, c.get('account_id'), amount))

    # Net annual fee reversals against fees in same month/account
    # Build a lookup of reversals by (month_key, account_id)
    reversal_lookup = defaultdict(float)
    for month_key, acct_id, rev_amount in annual_fee_reversals:
        reversal_lookup[(month_key, acct_id)] += rev_amount

    # Apply netting: reduce ANNUAL_FEE charges by reversal amounts
    for c in filtered:
        if c['sub_type'] == 'ANNUAL_FEE':
            month_key = _month_key(c['date'])
            acct_id = c.get('account_id')
            key = (month_key, acct_id)
            if key in reversal_lookup and reversal_lookup[key] > 0:
                reduction = min(c['amount'], reversal_lookup[key])
                c['amount'] -= reduction
                reversal_lookup[key] -= reduction
                # Keep netted charges (even at 0) so sub-type appears in report

    # Group by month
    by_month = defaultdict(list)
    for c in filtered:
        key = _month_key(c['date'])
        by_month[key].append(c)

    # Build monthly summaries
    monthly = []
    for month_key in sorted(by_month.keys()):
        month_charges = by_month[month_key]
        month_date = datetime.datetime.strptime(month_key, '%Y-%m').date()

        # Sub-type breakdown
        by_sub_type = defaultdict(lambda: {'total': 0.0, 'count': 0, 'charges': []})
        for c in month_charges:
            st = c['sub_type']
            by_sub_type[st]['total'] += c['amount']
            by_sub_type[st]['count'] += 1
            by_sub_type[st]['charges'].append(c)

        # Account breakdown
        by_account = defaultdict(lambda: {'total': 0.0, 'count': 0, 'charges': []})
        for c in month_charges:
            acct_id = c.get('account_id')
            if acct_id:
                by_account[acct_id]['total'] += c['amount']
                by_account[acct_id]['count'] += 1
                by_account[acct_id]['charges'].append(c)

        sub_type_summary = {}
        for st in SUB_TYPES:
            if st in by_sub_type:
                sub_type_summary[st] = {
                    'total': round(by_sub_type[st]['total'], 2),
                    'count': by_sub_type[st]['count'],
                }

        account_summary = {}
        for acct_id, data in by_account.items():
            account_summary[str(acct_id)] = {
                'total': round(data['total'], 2),
                'count': data['count'],
            }

        month_total = sum(c['amount'] for c in month_charges)
        monthly.append({
            'month': month_key,
            'month_date': month_date.isoformat(),
            'total': round(month_total, 2),
            'charge_count': len(month_charges),
            'by_sub_type': sub_type_summary,
            'by_account': account_summary,
        })

    # Overall totals by sub-type (across all months)
    overall_by_sub_type = defaultdict(lambda: {'total': 0.0, 'count': 0})
    for c in filtered:
        st = c['sub_type']
        overall_by_sub_type[st]['total'] += c['amount']
        overall_by_sub_type[st]['count'] += 1

    overall_sub_type_summary = {}
    for st in SUB_TYPES:
        if st in overall_by_sub_type:
            overall_sub_type_summary[st] = {
                'total': round(overall_by_sub_type[st]['total'], 2),
                'count': overall_by_sub_type[st]['count'],
            }

    # Overall totals by account
    overall_by_account = defaultdict(lambda: {'total': 0.0, 'count': 0})
    for c in filtered:
        acct_id = c.get('account_id')
        if acct_id:
            overall_by_account[acct_id]['total'] += c['amount']
            overall_by_account[acct_id]['count'] += 1

    overall_account_summary = {}
    for acct_id, data in sorted(overall_by_account.items(), key=lambda x: -x[1]['total']):
        overall_account_summary[str(acct_id)] = {
            'total': round(data['total'], 2),
            'count': data['count'],
        }

    return {
        'as_of': today.isoformat(),
        'lookback_days': LOOKBACK_DAYS,
        'monthly': monthly,
        'total_overall': round(sum(c['amount'] for c in filtered), 2),
        'charge_count_overall': len(filtered),
        'by_sub_type': overall_sub_type_summary,
        'by_account': overall_account_summary,
        'sub_types': SUB_TYPES,
    }


def collect_interest_fees(user_id, today=None):
    """The SQLAlchemy read: the user's interest/fee charges of the last LOOKBACK_DAYS."""
    from models import db, Account, Transaction

    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=LOOKBACK_DAYS)

    # Get transactions that are likely interest/fees:
    # - Negative amount (money out = charge in ExMint convention)
    # - On any enabled account (not just credit/loan - overdraft fees are on depository)
    # - Not removed, not pending, not split children
    rows = (db.session.query(Transaction, Account)
            .join(Account, Account.id == Transaction.account_id)
            .filter(Transaction.user_id == user_id,
                    Transaction.is_removed.is_(False),
                    Transaction.pending.is_(False),
                    Transaction.has_split_children.is_(False),
                    Transaction.amount < 0,  # Negative = charge/fee in ExMint convention
                    Transaction.date >= since,
                    Transaction.date <= today,
                    Account.is_enabled.is_(True))
            .all())

    charges = [{
        'id': t.id,
        'date': t.date,
        'amount': float(t.amount),  # negative
        'name': t.name,
        'merchant_name': t.merchant_name,
        'custom_name': t.custom_name,
        'account_id': t.account_id,
    } for t, acct in rows]

    return detect_interest_fees(charges, today)


def monthly_cost_of_debt(user_id, today=None):
    """Return the monthly cost of debt (interest + fees) for EX-02 integration.

    Returns a dict with:
    - 'monthly': list of {'month': 'YYYY-MM', 'total': float} for each month
    - 'total_overall': float, sum over lookback period
    - 'by_sub_type': dict of sub_type -> {'total': float, 'count': int}
    """
    report = collect_interest_fees(user_id, today)
    monthly_simple = [{'month': m['month'], 'total': m['total']} for m in report['monthly']]
    return {
        'monthly': monthly_simple,
        'total_overall': report['total_overall'],
        'by_sub_type': report['by_sub_type'],
    }


def ensure_interest_fees_category(user_id):
    """Ensure the 'Interest & Fees' custom category exists for the user.
    Returns the CustomCategory instance.
    """
    from models import db, CustomCategory
    cat = CustomCategory.query.filter_by(user_id=user_id, name='Interest & Fees').first()
    if not cat:
        cat = CustomCategory(user_id=user_id, name='Interest & Fees', color='#C0392B')
        db.session.add(cat)
        db.session.commit()
    return cat


def apply_interest_fees_tags(user_id, today=None):
    """Apply 'Interest & Fees' category tags to detected interest/fee transactions.

    Creates CategoryRules for each sub-type pattern and assigns the
    'Interest & Fees' custom category to matching transactions.
    Returns the number of transactions tagged.
    """
    from models import db, Transaction, Account, CategoryRule, CustomCategory

    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=LOOKBACK_DAYS)

    cat = ensure_interest_fees_category(user_id)

    # Build rules for each sub-type pattern
    # We create rules that match the text patterns used in _classify_sub_type
    rule_patterns = []
    for sub_type, patterns in SUB_TYPE_PATTERNS:
        for pattern in patterns:
            # Convert regex pattern to a simpler LIKE pattern for CategoryRule
            # CategoryRule uses text_to_match with field_to_match='description'
            # which does a case-insensitive substring match
            like_pattern = pattern.replace(r'\b', '').replace(r'\.', '.').replace('?', '')
            # Only add reasonable patterns (skip complex regex)
            if len(like_pattern) > 3 and not any(c in like_pattern for c in ['[', ']', '(', ')', '|', '^', '$']):
                rule_patterns.append((sub_type, like_pattern.lower()))

    # Deduplicate
    seen = set()
    unique_rules = []
    for sub_type, pattern in rule_patterns:
        if pattern not in seen:
            seen.add(pattern)
            unique_rules.append((sub_type, pattern))

    # Create CategoryRules if they don't exist
    for sub_type, pattern in unique_rules:
        existing = CategoryRule.query.filter_by(
            user_id=user_id, category_id=cat.id, text_to_match=pattern
        ).first()
        if not existing:
            rule = CategoryRule(
                user_id=user_id,
                category_id=cat.id,
                text_to_match=pattern,
                field_to_match='description',
            )
            db.session.add(rule)

    db.session.commit()

    # Now apply the category to matching transactions
    # We re-use the detection logic but assign the custom_category_id
    rows = (db.session.query(Transaction, Account)
            .join(Account, Account.id == Transaction.account_id)
            .filter(Transaction.user_id == user_id,
                    Transaction.is_removed.is_(False),
                    Transaction.pending.is_(False),
                    Transaction.has_split_children.is_(False),
                    Transaction.amount < 0,
                    Transaction.date >= since,
                    Transaction.date <= today,
                    Account.is_enabled.is_(True),
                    Transaction.custom_category_id.is_(None))  # only untagged
            .all())

    tagged = 0
    for t, acct in rows:
        text = t.custom_name or t.name or t.merchant_name or ''
        sub_type = _classify_sub_type(text)
        if sub_type is not None:
            t.custom_category_id = cat.id
            tagged += 1

    db.session.commit()
    return tagged


def net_annual_fee_reversals(user_id, today=None):
    """Net annual fee reversals/rebates against their fees for accurate monthly totals.

    This finds ANNUAL_FEE charges and their corresponding reversals (positive amounts
    with 'REVERSAL' or 'REBATE' in the name) in the same month on the same account,
    and adjusts the monthly totals to show the net amount.

    Returns a dict of month_key -> net_adjustment (negative = reduction).
    """
    from models import db, Transaction, Account

    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=LOOKBACK_DAYS)

    # Find all annual fee charges and reversals
    rows = (db.session.query(Transaction, Account)
            .join(Account, Account.id == Transaction.account_id)
            .filter(Transaction.user_id == user_id,
                    Transaction.is_removed.is_(False),
                    Transaction.pending.is_(False),
                    Transaction.has_split_children.is_(False),
                    Transaction.date >= since,
                    Transaction.date <= today,
                    Account.is_enabled.is_(True),
                    Transaction.name.ilike('%ANNUAL%'))
            .all())

    by_month_account = defaultdict(lambda: {'fees': 0.0, 'reversals': 0.0})
    for t, acct in rows:
        month_key = _month_key(t.date)
        key = (month_key, t.account_id)
        amount = float(t.amount)
        name_low = (t.name or '').lower()
        if 'reversal' in name_low or 'rebate' in name_low:
            by_month_account[key]['reversals'] += abs(amount)  # positive amount
        else:
            by_month_account[key]['fees'] += abs(amount)  # negative amount, take abs

    # Compute net adjustments
    adjustments = {}
    for key, vals in by_month_account.items():
        net = vals['fees'] - vals['reversals']
        if net < vals['fees']:  # there was a reversal
            adjustments[key[0]] = -min(vals['reversals'], vals['fees'])  # reduction

    return adjustments