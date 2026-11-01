"""sync_health.py — EX-03: which accounts have quietly stopped receiving transactions?

Two questions are answered for every account the user still sees in the app:

  * ``last_transaction_date`` — the newest non-removed transaction the account
    has, whatever its age;
  * what it usually does — ``expected_tx_per_month`` (the median of the three
    30-day buckets that make up the last 90 days) and ``expected_gap_days``
    (the median gap between consecutive transaction dates over the last 365
    days).

An account is reported when its connection is already flagged (Plaid
``requires_update``, soft-disconnected/paused, or a revoked credential or
account) or when nothing has arrived for longer than
``max(MIN_SILENT_DAYS, GAP_MULTIPLIER x its own usual gap)``.

Both halves of that threshold matter.  A fixed window would ignore how often an
account normally posts; a pure multiple of the usual gap would let a card that
normally posts every 12 days drift for 36 days unnoticed.  Multiplying the
account's own gap keeps an account that legitimately transacts quarterly out of
the alert, while a card that posts every few days and has been silent since
August is named on the day it stops.

An account that has never had a transaction is reported only when it is a
spending account (``depository``/``credit``): a GIC, an RDSP or a mortgage
genuinely produces no transactions and is not a broken feed, and calling it one
would bury the alerts that are.

Pure-stdlib math lives in ``evaluate_account`` so the rule can be checked
without a database; ``collect_sync_health`` is the SQLAlchemy read.
"""

import datetime
from collections import defaultdict
from statistics import median

from models import db, Account, Credential, Transaction
from sqlalchemy import func

# ``expected activity`` is measured over ACTIVITY_WINDOW_DAYS, cut into
# MONTH_DAYS buckets so a partial calendar month cannot masquerade as a slow
# month; the usual gap is allowed to look back BASELINE_WINDOW_DAYS.
ACTIVITY_WINDOW_DAYS = 90
MONTH_DAYS = 30
BASELINE_WINDOW_DAYS = 365
# Nothing at all for MIN_SILENT_DAYS is suspicious whatever the account's
# cadence; past that, the limit is GAP_MULTIPLIER x the account's own gap.
MIN_SILENT_DAYS = 10
GAP_MULTIPLIER = 3

# Reason codes, most urgent first.  ``status`` is the first one that applies;
# ``reasons`` keeps every one that does, so a revoked account that has also
# gone quiet shows both.
REASON_REVOKED = 'revoked'
REASON_REQUIRES_UPDATE = 'requires_update'
REASON_SOFT_DISCONNECTED = 'soft_disconnected'
REASON_NO_RECENT_ACTIVITY = 'no_recent_activity'
REASON_NO_TRANSACTIONS = 'no_transactions'
REASON_ORDER = (
    REASON_REVOKED,
    REASON_REQUIRES_UPDATE,
    REASON_SOFT_DISCONNECTED,
    REASON_NO_RECENT_ACTIVITY,
    REASON_NO_TRANSACTIONS,
)
STATUS_HEALTHY = 'healthy'

# The four ways a connection actually fails.  ``no_transactions`` is reported
# with the account but is not one of them: an account that has never had a
# transaction says nothing about a feed that stopped, and putting it in the
# banner buries the ones that did.
ALERT_REASONS = (
    REASON_REVOKED,
    REASON_REQUIRES_UPDATE,
    REASON_SOFT_DISCONNECTED,
    REASON_NO_RECENT_ACTIVITY,
)

# Two kinds of failure, and they need to be shown differently.  A revoked,
# paused or needs-reconnect credential is a fault of the *connection*: naming
# every account under it (RBC alone has twelve) drowns the banner.  An account
# that has gone quiet while its connection looks healthy is a fault of that
# *account*, and only that account is named.
CONNECTION_REASONS = (REASON_REVOKED, REASON_REQUIRES_UPDATE, REASON_SOFT_DISCONNECTED)
ACTIVITY_REASONS = (REASON_NO_RECENT_ACTIVITY, REASON_NO_TRANSACTIONS)

# One line per reason, ready for the dashboard banner and the daily report.
REASON_TEXT = {
    REASON_REVOKED: 'connection revoked',
    REASON_REQUIRES_UPDATE: 'needs to be reconnected',
    REASON_SOFT_DISCONNECTED: 'paused (no new data from the bank)',
    REASON_NO_RECENT_ACTIVITY: 'no transactions since {last_activity}',
    REASON_NO_TRANSACTIONS: 'no transactions in ExMint yet',
}

# Account types where silence means real spending is going unrecorded.
SPENDING_TYPES = {'depository', 'credit'}

# The dashboard banner is read on a phone, and Manuel's honest render is ten
# institution lines with twenty-two accounts under them — long enough that the
# revoked card at the top gets scrolled past.  The banner therefore shows the
# most urgent institutions only and hands the rest to the Accounts pane, which
# already names every one of them.
BANNER_INSTITUTION_LIMIT = 5


def _csv_only_credential(credential):
    """True for an institution that was built by the CSV importer, not by Plaid.

    ``_csv_new_institution`` gives those credentials an ``csv-`` item id and
    they never carry a Plaid cursor.  They are soft-disconnected by design, so
    their paused state is not a fault — but a CSV account nobody has imported
    for two months still has to be named.

    ``access_token`` is deliberately not consulted: it is an encrypted column,
    and reading it only to ask "is it null" would tie a read-only report to the
    key that encrypted it.
    """
    return bool(str(credential.item_id or '').startswith('csv-'))


def _median_gap_days(dates):
    """Median gap in days between consecutive transaction *dates* (None if unusable).

    Same-day transactions collapse to one date: the question is how long
    between episodes of activity, not how many purchases one Saturday held.
    """
    ordered = sorted(set(dates))
    if len(ordered) < 2:
        return None
    gaps = [(later - earlier).days for earlier, later in zip(ordered, ordered[1:])]
    return float(median(gaps))


def _median_tx_per_month(dates, today):
    """Median transactions per 30-day bucket over the last 90 days.

    Three fixed buckets rather than calendar months: with calendar months the
    first and last buckets are partial, and a month that has only just begun
    would read as a slow month.  A future-dated row (a scheduled payment)
    counts as current activity, in bucket 0.
    """
    buckets = [0, 0, 0]
    for day in dates:
        age = (today - day).days
        if age < 0:
            age = 0
        if age < ACTIVITY_WINDOW_DAYS:
            buckets[age // MONTH_DAYS] += 1
    return float(median(buckets))


def _format_date(day):
    """'Oct 5, 2026' — no zero padding, and portable (no platform strftime flags)."""
    return '%s %d, %d' % (day.strftime('%b'), day.day, day.year)


def _plural(count, singular):
    """'1 day' but '23.5 days' — %g keeps the fraction, never the plural."""
    return '%g %s%s' % (count, singular, '' if abs(float(count) - 1.0) < 1e-9 else 's')


def _cadence_phrase(expected_tx_per_month, expected_gap_days):
    """The account's own rhythm, as one readable clause.

    The monthly figure is left out when it is zero.  For an account already
    quiet for a quarter, the window it was measured over is empty *because* it
    stopped, so "usually 0 transactions a month" would describe the failure and
    read as though the card had always been idle.
    """
    parts = []
    if expected_tx_per_month > 0:
        parts.append('%s a month' % _plural(expected_tx_per_month, 'transaction'))
    if expected_gap_days is not None:
        parts.append('one every %s' % _plural(expected_gap_days, 'day'))
    if not parts:
        return 'no cadence to measure'
    return 'usually ' + ', '.join(parts)


def _silent_after_days(expected_gap_days):
    """How long an account may stay quiet before it is reported."""
    if expected_gap_days is None:
        return MIN_SILENT_DAYS
    return max(MIN_SILENT_DAYS, int(round(GAP_MULTIPLIER * expected_gap_days)))


def evaluate_account(account, credential, transaction_dates, last_transaction_date,
                     today, transaction_count=None):
    """Judge one account. Returns the sync-health record for it.

    ``transaction_dates`` are the account's transaction dates inside the
    baseline window (they set the expected activity); ``last_transaction_date``
    is its newest transaction date whatever its age, so an account that stopped
    two years ago is still reported with the right number of quiet days.
    """
    today = today or datetime.date.today()
    csv_only = _csv_only_credential(credential)

    if last_transaction_date is not None:
        days_since = (today - last_transaction_date).days
        if days_since < 0:
            days_since = 0
    else:
        days_since = None

    expected_gap_days = _median_gap_days(transaction_dates)
    silent_after = _silent_after_days(expected_gap_days)
    expected_tx_per_month = _median_tx_per_month(transaction_dates, today)

    reasons = []
    if credential.status == 'Revoked' or account.status == 'Revoked':
        reasons.append(REASON_REVOKED)
    if credential.requires_update:
        reasons.append(REASON_REQUIRES_UPDATE)
    if credential.soft_disconnected and not csv_only:
        reasons.append(REASON_SOFT_DISCONNECTED)

    if last_transaction_date is None:
        if (account.type or '').lower() in SPENDING_TYPES and not csv_only:
            reasons.append(REASON_NO_TRANSACTIONS)
    elif days_since > silent_after:
        reasons.append(REASON_NO_RECENT_ACTIVITY)

    status = STATUS_HEALTHY
    for reason in REASON_ORDER:
        if reason in reasons:
            status = reason
            break

    # Only the reasons that name a date carry {last_activity}; formatting the
    # others with one would need a date the account does not have.
    text_parts = [
        (REASON_TEXT[reason].format(last_activity=_format_date(last_transaction_date))
         if '{last_activity}' in REASON_TEXT[reason] else REASON_TEXT[reason])
        for reason in reasons
    ]
    if REASON_NO_RECENT_ACTIVITY in reasons:
        text_parts.append('quiet for %s (%s; reported after %s)'
                          % (_plural(days_since, 'day'),
                             _cadence_phrase(expected_tx_per_month, expected_gap_days),
                             _plural(silent_after, 'day')))

    return {
        'account_id': account.id,
        'account_name': account.name,
        'mask': account.mask,
        'account_type': account.type,
        'subtype': account.subtype,
        'is_closed': bool(account.is_closed),
        'credential_id': credential.id,
        'institution_name': credential.institution_name,
        'credential_label': credential.label,
        'csv_only': csv_only,
        'status': status,
        'reasons': reasons,
        'connection_reasons': [r for r in reasons if r in CONNECTION_REASONS],
        'activity_reasons': [r for r in reasons if r in ACTIVITY_REASONS],
        'needs_attention': any(reason in ALERT_REASONS for reason in reasons),
        'detail': '; '.join(text_parts),
        'last_transaction_date': (last_transaction_date.isoformat()
                                  if last_transaction_date else None),
        'days_since_last_transaction': days_since,
        'transaction_count': (transaction_count if transaction_count is not None
                              else len(transaction_dates)),
        'expected_tx_per_month': round(expected_tx_per_month, 2),
        'expected_gap_days': (round(expected_gap_days, 2)
                              if expected_gap_days is not None else None),
        'silent_after_days': silent_after,
        'requires_update': bool(credential.requires_update),
        'soft_disconnected': bool(credential.soft_disconnected),
        'revoked': (credential.status == 'Revoked' or account.status == 'Revoked'),
        # Set by collect_sync_health: this card is also shown by a credential of
        # the same bank that still works, so it is reported once, there.
        'shadowed': False,
    }


def collect_sync_health(user_id, today=None):
    """Read the whole sync picture for one user: every visible account, flagged or not."""
    today = today or datetime.date.today()

    rows = (
        db.session.query(Account, Credential)
        .join(Credential, Account.credential_id == Credential.id)
        .filter(
            Credential.user_id == user_id,
            Credential.status.in_(['Active', 'Revoked']),
            Account.status.in_(['Active', 'Revoked']),
            Account.is_enabled.is_(True),
            Account.is_closed.is_(False),
        )
        .all()
    )

    # A revoked credential whose accounts all reappear under a live credential
    # of the same bank is a leftover from re-connecting, not a broken feed — and
    # GET /api/banks already hides it from the accounts pane.  The report has to
    # hide it too, or the banner would name a dozen dead CIBC connections every
    # day and Manuel would stop reading it.
    rows_by_credential = defaultdict(list)
    masks_by_credential = defaultdict(set)
    for account, credential in rows:
        rows_by_credential[credential.id].append((account, credential))
        if account.mask:
            masks_by_credential[credential.id].add(account.mask)

    covered_masks = defaultdict(set)
    visible_rows = []
    shadowed_ids = set()
    superseded_ids = []
    for credential_id in sorted(rows_by_credential,
                                key=lambda cid: (1 if rows_by_credential[cid][0][1].status == 'Revoked'
                                                 else 0, cid)):
        credential_rows = rows_by_credential[credential_id]
        credential = credential_rows[0][1]
        institution = (credential.institution_name or '').lower()
        masks = masks_by_credential[credential_id]
        if credential.status == 'Revoked':
            if not masks - covered_masks[institution]:
                superseded_ids.append(credential_id)
                continue
            # A re-connection leaves the same card under two credentials.  Under
            # the dead one it has no transactions of its own, so it would be
            # named a second time as if it had never synced — name it only under
            # the credential that still represents it.
            shadowed_ids.update(account.id for account, _ in credential_rows
                                if account.mask and account.mask in covered_masks[institution])
        covered_masks[institution] |= masks
        visible_rows.extend(credential_rows)

    # Newest transaction per account, whatever its age: an account that stopped
    # syncing last year still needs the true number of quiet days.
    newest = dict(
        db.session.query(Transaction.account_id, func.max(Transaction.date))
        .filter(Transaction.user_id == user_id, Transaction.is_removed.is_(False))
        .group_by(Transaction.account_id)
        .all()
    )
    total_counts = dict(
        db.session.query(Transaction.account_id, func.count(Transaction.id))
        .filter(Transaction.user_id == user_id, Transaction.is_removed.is_(False))
        .group_by(Transaction.account_id)
        .all()
    )
    # Dates inside the baseline window: what this account usually does.
    window_start = today - datetime.timedelta(days=BASELINE_WINDOW_DAYS)
    windowed = defaultdict(list)
    for account_id, day in (
        db.session.query(Transaction.account_id, Transaction.date)
        .filter(
            Transaction.user_id == user_id,
            Transaction.is_removed.is_(False),
            Transaction.date >= window_start,
        )
        .all()
    ):
        windowed[account_id].append(day)

    accounts = [
        evaluate_account(
            account, credential,
            windowed.get(account.id, []),
            newest.get(account.id),
            today,
            transaction_count=total_counts.get(account.id, 0),
        )
        for account, credential in visible_rows
    ]
    for record in accounts:
        record['shadowed'] = record['account_id'] in shadowed_ids

    # Counted and named once, under the credential that represents the card
    # today; a shadowed record stays in ``accounts`` so the accounts pane can
    # still show it.
    counted = [a for a in accounts if not a['shadowed']]

    alerts = [a for a in counted if a['needs_attention']]
    alerts.sort(key=lambda a: (REASON_ORDER.index(a['status']),
                               -(a['days_since_last_transaction'] or 0)))

    counts = {reason: sum(1 for a in counted if reason in a['reasons'])
              for reason in REASON_ORDER}
    institutions = summarize_institutions(accounts)
    banner_institutions, banner_omitted = banner_selection(institutions)
    return {
        'today': today.isoformat(),
        'activity_window_days': ACTIVITY_WINDOW_DAYS,
        'baseline_window_days': BASELINE_WINDOW_DAYS,
        'min_silent_days': MIN_SILENT_DAYS,
        'gap_multiplier': GAP_MULTIPLIER,
        'account_count': len(accounts),
        'alert_count': len(alerts),
        # What a reader is actually being told: how many connections are broken
        # and how many accounts have stopped receiving anything.
        'alert_institution_count': sum(1 for i in institutions if i['needs_attention']),
        'connection_problem_count': sum(1 for i in institutions if i['connection_reasons']),
        'quiet_account_count': sum(1 for a in counted if a['activity_reasons']),
        # Credentials left behind by a re-connection.  They are not a broken
        # feed — the same bank is connected elsewhere — so a caller that lists
        # every credential (v1 /institutions does) should not report one as
        # disconnected next to the connection that works.
        'superseded_credential_ids': superseded_ids,
        'counts': counts,
        'accounts': accounts,
        'alerts': alerts,
        'institutions': institutions,
        # The banner's slice of that list, already in urgency order, plus the
        # count it left out so the page can say where to find the rest.
        'banner_institution_limit': BANNER_INSTITUTION_LIMIT,
        'banner_institutions': banner_institutions,
        'banner_omitted_institution_count': banner_omitted,
    }


def _account_brief(record):
    """The per-account line the banner, the accounts pane and the daily report all show."""
    return {
        'account_id': record['account_id'],
        'account_name': record['account_name'],
        'mask': record['mask'],
        'status': record['status'],
        'reasons': record['reasons'],
        'activity_reasons': record['activity_reasons'],
        'last_transaction_date': record['last_transaction_date'],
        'days_since_last_transaction': record['days_since_last_transaction'],
        'expected_tx_per_month': record['expected_tx_per_month'],
        'silent_after_days': record['silent_after_days'],
        'detail': record['detail'],
    }


def summarize_institutions(accounts):
    """Roll the per-account records up per credential, most troubled institution first.

    A credential-level fault (revoked, paused, needs reconnect) is reported once
    for the institution; only the accounts that have actually gone quiet are
    named individually.  That is what keeps a banner readable: RBC Royal Bank has
    twelve accounts, and "RBC is disconnected" is one line, not twelve.
    """
    by_credential = defaultdict(list)
    for record in accounts:
        by_credential[record['credential_id']].append(record)

    institutions = []
    for credential_id, records in by_credential.items():
        flagged = [r for r in records if r['needs_attention']]
        # A card this bank already shows through a credential that still works is
        # named there, not again under the dead one.
        named = [r for r in records if not r.get('shadowed')]
        named_flagged = [r for r in named if r['needs_attention']]
        dated = [r['last_transaction_date'] for r in records if r['last_transaction_date']]
        connection_reasons = [reason for reason in CONNECTION_REASONS
                              if any(reason in r['connection_reasons'] for r in records)]
        quiet = sorted((r for r in named if r['activity_reasons']),
                       key=lambda r: -(r['days_since_last_transaction'] or 0))
        reasons = list(connection_reasons)
        for reason in ACTIVITY_REASONS:
            if any(reason in r['activity_reasons'] for r in records):
                reasons.append(reason)

        institutions.append({
            'id': credential_id,
            'institution_name': records[0]['institution_name'],
            'label': records[0]['credential_label'],
            'csv_only': records[0]['csv_only'],
            'needs_attention': bool(flagged),
            # The institution's own standing is the most urgent thing wrong with
            # any of its accounts; its accounts keep their individual statuses.
            'status': REASON_ORDER[min((REASON_ORDER.index(r['status']) for r in flagged),
                                       default=len(REASON_ORDER))] if flagged else STATUS_HEALTHY,
            'reasons': reasons,
            'connection_reasons': connection_reasons,
            'last_transaction_date': max(dated) if dated else None,
            'days_since_last_transaction': min(
                (r['days_since_last_transaction'] for r in records
                 if r['days_since_last_transaction'] is not None),
                default=None),
            'account_count': len(records),
            'alert_account_count': len(named_flagged),
            'quiet_account_count': len(quiet),
            'headline': _institution_headline(connection_reasons, quiet),
            # The accounts this institution has to answer for: quiet on their own,
            # or carried along by a credential that is itself broken.
            'quiet_accounts': [_account_brief(r) for r in quiet],
            'alert_accounts': [_account_brief(r) for r in sorted(
                named_flagged, key=lambda r: -(r['days_since_last_transaction'] or 0))],
        })
    institutions.sort(key=_institution_urgency)
    return institutions


def _institution_urgency(institution):
    """Banner rank: worst reason first, then most accounts quiet, then longest silence.

    Sorting by id instead puts a bank that lost twelve accounts behind one that
    lost none, so a cap cuts the wrong institutions.  Unhealthy institutions are
    forced ahead of healthy ones by the leading element: ``no_transactions`` is
    in ``REASON_ORDER`` but is not an alert, and an institution whose only
    account has never transacted must not outrank one that is actually broken.
    """
    reason_rank = (REASON_ORDER.index(institution['status'])
                   if institution['status'] in REASON_ORDER else len(REASON_ORDER))
    longest_silence = max((a['days_since_last_transaction'] or 0
                           for a in institution['quiet_accounts']), default=0)
    return (not institution['needs_attention'], reason_rank,
            -institution['quiet_account_count'], -longest_silence,
            (institution['institution_name'] or '').lower(), institution['id'])


def banner_selection(institutions):
    """The institutions the banner shows, and how many it leaves to the Accounts pane.

    The full list stays in the payload — the accounts sidebar, the API and the
    daily report all need every institution — so only the banner is capped.
    """
    attention = [inst for inst in institutions if inst['needs_attention']]
    shown = attention[:BANNER_INSTITUTION_LIMIT]
    return shown, max(0, len(attention) - len(shown))


def _institution_headline(connection_reasons, quiet_accounts):
    """One line saying what is wrong with this institution, ready for the banner."""
    parts = [REASON_TEXT[reason] for reason in connection_reasons]
    if quiet_accounts:
        parts.append('%d %s with nothing arriving'
                     % (len(quiet_accounts),
                        'account' if len(quiet_accounts) == 1 else 'accounts'))
    return '; '.join(parts) if parts else 'receiving transactions normally'
