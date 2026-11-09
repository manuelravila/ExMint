"""recurring.py — EX-06: what charges every month, what it costs, what changed.

A *series* is one bill: the same merchant charging about the same amount on a
monthly (median gap 26–35 days) or biweekly (12–16 days) rhythm, at least
``MIN_CHARGES`` times.  The read works in four steps, per merchant:

1. **Merchant key.**  Bank text is noisy (``FIDO MOBILE ******2752 020`` and
   ``Fido 020`` are the same bill; ``INSURANCE`` with merchant ``Economical
   Ins.`` and ``Insurance Economical Ins.`` too), so the key is the first
   meaningful word of ``custom_name`` / ``name`` / ``merchant_name`` once
   digits, reference tokens and generic words (insurance, mobile, payment...)
   are dropped.  Behind a payment processor (``DLO*Starlink``,
   ``PAYPAL *STARLINKSAT``) the merchant is the part after the ``*``.
2. **Amount clusters.**  Charges within ``AMOUNT_TOLERANCE`` of each other are
   one candidate, so two policies billed on the same day by the same insurer
   (Economical x2) are two series, and movie tickets do not pollute a
   Cineclub membership.
3. **Price changes.**  A bill whose price moved (Fido $30 -> $60) splits into
   clusters that follow each other in time without overlapping; those are
   chained back into one series.  A stray charge that sits exactly where a
   missing cycle should be (Fido's $120 month) is absorbed as well.
4. **Cadence.**  The latest unbroken run (no gap longer than two cycles) must
   have a monthly or biweekly median gap with most gaps near it; random
   repeats are rejected.

Same-day, same-amount charges of one merchant are counted once: a replacement
card (old and new account both synced) must not double a bill.

A series whose last charge is more than two cycles old is *inactive*: it is
listed separately and left out of ``total_monthly``.

``detect_recurring`` is pure Python over plain dicts so the rule is testable
without a database; ``collect_recurring`` is the SQLAlchemy read.
"""

import datetime
import re
from statistics import median

MIN_CHARGES = 3
AMOUNT_TOLERANCE = 0.15          # same bill when within 15% of the cluster median
PRICE_CHANGE_THRESHOLD = 0.10    # alert when a charge moves more than 10%
MONTHLY_GAP = (26, 35)
BIWEEKLY_GAP = (12, 16)
ALERT_WINDOW_DAYS = 45           # price changes / new series this recent alert
LOOKBACK_DAYS = 400
ABSORB_SLACK_DAYS = 5            # a stray charge fits a cycle within +/- 5 days
ABSORB_RATIO = 3.0               # ...and costs between 1/3x and 3x the bill
BIWEEKLY_PER_MONTH = 26 / 12

ALERT_PRICE_CHANGE = 'price_change'
ALERT_NEW = 'new'

_PROCESSORS = {'paypal', 'dlo', 'd local', 'dlocal', 'sq', 'sp', 'tst', 'pp', 'google', 'apple'}
_STOPWORDS = {
    'insurance', 'ins', 'life', 'mobile', 'canada', 'ob', 'miscellaneous', 'misc',
    'payment', 'pymt', 'pmt', 'the', 'inc', 'ltd', 'llc', 'corp', 'co', 'www', 'com',
    'ca', 'net', 'org', 'bill', 'billpay', 'preauthorized', 'pre', 'auth', 'debit',
    'purchase', 'pos', 'pad', 'online', 'recurring',
}


def merchant_key(*texts):
    """First meaningful lowercase word of the first text that has one."""
    for text in texts:
        if not text:
            continue
        low = text.lower()
        if '*' in low:
            head, tail = low.split('*', 1)
            low = tail if head.strip() in _PROCESSORS else head
        for token in re.split(r'[^a-z0-9]+', low):
            if len(token) < 2 or any(c.isdigit() for c in token) or token in _STOPWORDS:
                continue
            return token
    return None


def _display_name(charge):
    merchant = (charge.get('merchant_name') or '').strip()
    if charge.get('custom_name'):
        return charge['custom_name']
    if merchant and merchant[0].isalpha():
        return merchant
    return charge.get('name') or merchant


def _gaps(dates):
    return [(b - a).days for a, b in zip(dates, dates[1:])]


def _cadence(gap):
    if MONTHLY_GAP[0] <= gap <= MONTHLY_GAP[1]:
        return 'monthly'
    if BIWEEKLY_GAP[0] <= gap <= BIWEEKLY_GAP[1]:
        return 'biweekly'
    return None


def _regular(dates):
    """(cadence, median gap) when the dates beat regularly, else (None, gap)."""
    gaps = _gaps(dates)
    if not gaps:
        return None, None
    gap = median(gaps)
    cadence = _cadence(gap)
    if cadence is None:
        return None, gap
    # One missed cycle is fine, two are a break (handled by _latest_run).  A
    # short gap (a catch-up charge) is tolerated as long as most gaps sit near
    # the cycle; random repeats fail that test.
    if any(g > 2 * gap + 7 for g in gaps):
        return None, gap
    near = sum(1 for g in gaps if 0.75 * gap <= g <= 1.35 * gap)
    if near < 0.6 * len(gaps):
        return None, gap
    return cadence, gap


def _amount_clusters(charges):
    """Group charges whose amounts sit within AMOUNT_TOLERANCE of the cluster median."""
    clusters = []
    for charge in sorted(charges, key=lambda c: c['amount']):
        if clusters:
            ref = median(c['amount'] for c in clusters[-1])
            if abs(charge['amount'] - ref) <= AMOUNT_TOLERANCE * ref:
                clusters[-1].append(charge)
                continue
        clusters.append([charge])
    return [sorted(c, key=lambda c: c['date']) for c in clusters]


def _ratio_ok(a, b):
    lo, hi = sorted((a, b))
    return lo > 0 and hi / lo <= ABSORB_RATIO


def _chain(clusters):
    """Chain clusters that follow each other without overlapping (a price change)."""
    chains = []
    for cluster in sorted(clusters, key=lambda c: c[0]['date']):
        for chain in chains:
            last = chain[-1]
            gap = median(_gaps([c['date'] for c in chain]) or [30])
            if (last['date'] < cluster[0]['date']
                    and (cluster[0]['date'] - last['date']).days <= 2 * gap + 7
                    and _ratio_ok(last['amount'], cluster[0]['amount'])):
                chain.extend(cluster)
                break
        else:
            chains.append(list(cluster))
    return chains


def _latest_run(charges):
    """The newest stretch of charges with no gap longer than two cycles."""
    dates = [c['date'] for c in charges]
    gaps = _gaps(dates)
    if not gaps:
        return charges
    gap = median(gaps)
    start = 0
    for i, g in enumerate(gaps):
        if g > 2 * gap + 7:
            start = i + 1
    run = charges[start:]
    if len(run) >= MIN_CHARGES:
        return run
    # The newest stretch is too short to judge (a stray after a cancelled
    # membership): fall back to the longest earlier stretch.
    best, cur = [], [charges[0]]
    for prev, nxt in zip(charges, charges[1:]):
        if (nxt['date'] - prev['date']).days > 2 * gap + 7:
            cur = [nxt]
        else:
            cur.append(nxt)
        if len(cur) >= len(best):
            best = list(cur)
    return best


def _absorb(series, leftovers, gap):
    """Pull in strays that sit exactly where a missing cycle (or the next/previous one) is."""
    slack = ABSORB_SLACK_DAYS
    changed = True
    while changed and leftovers:
        changed = False
        dates = [c['date'] for c in series]
        targets = [dates[0] - datetime.timedelta(days=gap),
                   dates[-1] + datetime.timedelta(days=gap)]
        for a, b in zip(dates, dates[1:]):
            if (b - a).days > 1.5 * gap:
                targets.append(a + datetime.timedelta(days=gap))
        for target in targets:
            # Compare with the bill's charges either side of the slot: a price
            # that moved since last year must not make this month look foreign.
            before = [c for c in series if c['date'] <= target][-1:]
            after = [c for c in series if c['date'] > target][:1]
            fits = [c for c in leftovers
                    if abs((c['date'] - target).days) <= slack
                    and any(_ratio_ok(c['amount'], n['amount']) for n in before + after)]
            if fits:
                pick = min(fits, key=lambda c: abs((c['date'] - target).days))
                trial = sorted(series + [pick], key=lambda c: c['date'])
                if not _regular([c['date'] for c in trial])[0]:
                    continue  # a stray must not break the bill's rhythm
                leftovers.remove(pick)
                series[:] = trial
                changed = True
                break
    return series


def _dedupe(charges):
    seen, out = set(), []
    for c in sorted(charges, key=lambda c: (c['date'], c['amount'], c.get('id') or 0)):
        sig = (c['date'], round(c['amount'], 2))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


def _series_record(key, charges, cadence, gap, today):
    dates = [c['date'] for c in charges]
    last = charges[-1]
    gap_days = int(round(gap))
    monthly = last['amount'] * (BIWEEKLY_PER_MONTH if cadence == 'biweekly' else 1)
    window_start = today - datetime.timedelta(days=ALERT_WINDOW_DAYS)

    alerts = []
    changes = []
    for prev, cur in zip(charges, charges[1:]):
        if abs(cur['amount'] - prev['amount']) > PRICE_CHANGE_THRESHOLD * prev['amount']:
            changes.append({
                'date': cur['date'].isoformat(),
                'old_amount': round(prev['amount'], 2),
                'new_amount': round(cur['amount'], 2),
                'change_pct': round(100 * (cur['amount'] - prev['amount']) / prev['amount'], 1),
            })
    recent = [ch for ch in changes if ch['date'] >= window_start.isoformat()]
    if recent:
        alerts.append(dict(recent[-1], type=ALERT_PRICE_CHANGE))
    if dates[MIN_CHARGES - 1] >= window_start:
        alerts.append({'type': ALERT_NEW, 'date': dates[MIN_CHARGES - 1].isoformat()})

    next_expected = dates[-1] + datetime.timedelta(days=gap_days)
    inactive = (today - dates[-1]).days > 2 * gap + 7
    return {
        'key': key,
        'merchant': _display_name(last),
        'cadence': cadence,
        'gap_days': gap_days,
        'charges': len(charges),
        'last_amount': round(last['amount'], 2),
        'typical_amount': round(median(c['amount'] for c in charges[-3:]), 2),
        'monthly_equivalent': round(monthly, 2),
        'first_date': dates[0].isoformat(),
        'last_date': dates[-1].isoformat(),
        'next_expected': next_expected.isoformat(),
        'overdue': (not inactive) and next_expected < today,
        'active': not inactive,
        'account_id': last.get('account_id'),
        'transaction_ids': [c.get('id') for c in charges],
        'price_changes': changes,
        'alerts': alerts,
    }


def detect_recurring(charges, today=None):
    """charges: dicts with date, amount (positive = money out), name,
    merchant_name, custom_name, account_id, id.  Returns the report dict."""
    today = today or datetime.date.today()
    by_key = {}
    for c in charges:
        if c['amount'] <= 0:
            continue
        key = merchant_key(c.get('custom_name'), c.get('name'), c.get('merchant_name'))
        if key:
            by_key.setdefault(key, []).append(c)

    found = []
    for key, group in by_key.items():
        group = _dedupe(group)
        if len(group) < MIN_CHARGES:
            continue
        clusters = _amount_clusters(group)
        candidates = _chain([c for c in clusters if len(c) >= 2])
        used = set()
        for cand in candidates:
            if len(cand) < MIN_CHARGES:
                continue
            run = _latest_run(cand)
            if len(run) < MIN_CHARGES:
                continue
            cadence, gap = _regular([c['date'] for c in run])
            if not cadence:
                continue
            found.append((key, run, gap))
            used.update(id(c) for c in run)
        leftovers = [c for c in group if id(c) not in used]
        for key_, run, gap in found:
            if key_ == key and leftovers:
                _absorb(run, leftovers, gap)

    series = []
    for key, run, _gap in found:
        cadence, gap = _regular([c['date'] for c in run])
        series.append(_series_record(key, run, cadence, gap, today))

    series.sort(key=lambda s: -s['monthly_equivalent'])
    active = [s for s in series if s['active']]
    inactive = [s for s in series if not s['active']]
    return {
        'as_of': today.isoformat(),
        'total_monthly': round(sum(s['monthly_equivalent'] for s in active), 2),
        'recurring': active,
        'inactive': inactive,
        'alerts': [dict(a, merchant=s['merchant'], key=s['key'])
                   for s in active for a in s['alerts']],
    }


def collect_recurring(user_id, today=None):
    """The SQLAlchemy read: the user's outflows of the last LOOKBACK_DAYS."""
    from models import db, Account, Transaction

    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=LOOKBACK_DAYS)
    rows = (db.session.query(Transaction)
            .join(Account, Account.id == Transaction.account_id)
            .filter(Transaction.user_id == user_id,
                    Transaction.is_removed.is_(False),
                    Transaction.pending.is_(False),
                    Transaction.has_split_children.is_(False),
                    Transaction.amount < 0,
                    Transaction.date >= since,
                    Transaction.date <= today,
                    Account.is_enabled.is_(True))
            .all())
    charges = [{
        'id': t.id,
        'date': t.date,
        'amount': -float(t.amount),
        'name': t.name,
        'merchant_name': t.merchant_name,
        'custom_name': t.custom_name,
        'account_id': t.account_id,
    } for t in rows]
    return detect_recurring(charges, today)
