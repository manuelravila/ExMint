#!/usr/bin/env python
"""test_balances_anchor_signs.py — EX-13: balances are computed, with the right sign.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_balances_anchor_signs.py

Part A is pure: the sign rules _compute_account_balance applies to the two
sources that need no queries (the cached Plaid balance and the all-transactions
sum), and the account-type inference a CSV import leans on.
Part B runs against the dev database with throwaway rows shaped like the PROD
accounts the ticket names (WestJet 9669, RBC 1963, RBC LOC 3001, Home Depot 8134,
Scotia Amex 0283) and checks through the Flask test client that GET /api/dashboard:

- computes anchor + the transactions after the anchor, for a chequing account
  AND for a card: on a card a payment reduces what is owed and a purchase
  increases it, so the post-anchor total is subtracted, never added;
- lets any account be anchored, a live Plaid one included, and lets that anchor
  outrank the cached Plaid balance;
- stops reading an un-anchored card as an asset (the fallback keeps the debt sign);
- lists a closed (cancelled) account with its balance while counting it nowhere.

Every row it created — the daily balance snapshots included — is deleted and the
cleanup is asserted.  No pytest is used (the venv does not have it); exits
non-zero on any failure.
"""

import datetime
import sys
import uuid
from decimal import Decimal

_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


def close(a, b):
    if a is None:
        return False
    return abs(float(a) - float(b)) < 1e-6


class _AccountStandin:
    """Stands in for an Account row where the balance needs no queries."""

    def __init__(self, type=None, subtype=None, current_balance=None, balance_fetched_at=None):
        self.id = 0
        self.type = type
        self.subtype = subtype
        self.current_balance = current_balance
        self.balance_fetched_at = balance_fetched_at
        # No anchor: _compute_account_balance must not reach for the database.
        self.last_known_balance = None
        self.balance_date = None


def part_a():
    print('=== Part A: sign rules and account-type inference (pure) ===')
    from core_views import _account_owes, _compute_account_balance, _csv_account_type_from_text

    card = _AccountStandin(type='credit', subtype='credit card')
    loc = _AccountStandin(type='loan', subtype='line of credit')
    chequing = _AccountStandin(type='depository', subtype='checking')
    invest = _AccountStandin(type='investment', subtype='rrsp')
    unknown = _AccountStandin(type=None, subtype=None)

    check('credit and loan are debt; the rest are not',
          _account_owes(card) and _account_owes(loc)
          and not _account_owes(chequing) and not _account_owes(invest) and not _account_owes(unknown))

    # The fallback sums the account's whole cash flow. On a card that total is the
    # mirror image of the debt, so it must NOT be negated a second time — that is
    # what used to show Home Depot 8134 as +5,258.52 of "asset".
    bal, source, as_of = _compute_account_balance(card, txn_total=Decimal('-4258.52'))
    check('card fallback sum reads as debt (-4258.52)', close(bal, -4258.52) and source == 'sum',
          '%r %s' % (bal, source))
    bal, source, _ = _compute_account_balance(chequing, txn_total=Decimal('1147.62'))
    check('chequing fallback sum reads as money held (1147.62)', close(bal, 1147.62) and source == 'sum',
          '%r %s' % (bal, source))
    bal, source, _ = _compute_account_balance(loc, txn_total=Decimal('-17550.00'))
    check('line of credit fallback sum stays debt (-17550.00)', close(bal, -17550.00), '%r' % bal)
    bal, source, _ = _compute_account_balance(unknown, txn_total=Decimal('5258.52'))
    check('an account with no type is left as an asset, not guessed',
          close(bal, 5258.52) and source == 'sum', '%r %s' % (bal, source))

    fetched = datetime.datetime(2026, 10, 25, 14, 30)
    bal, source, as_of = _compute_account_balance(
        _AccountStandin(type='credit', subtype='credit card', current_balance=Decimal('309.71'),
                        balance_fetched_at=fetched))
    check('Plaid card balance is a negative balance (-309.71)', close(bal, -309.71) and source == 'plaid',
          '%r %s' % (bal, source))
    check('a Plaid balance is stamped with the date it was read',
          as_of == datetime.date(2026, 10, 25), repr(as_of))
    bal, source, _ = _compute_account_balance(invest, txn_total=Decimal('320.76'))
    check('an investment sum stays positive', close(bal, 320.76), '%r' % bal)

    # A disconnected credential's current_balance is whatever Plaid last reported
    # before the connection was paused: too old to show while CSV rows keep coming.
    stale = _AccountStandin(type='credit', current_balance=Decimal('999.99'))
    bal, source, _ = _compute_account_balance(stale, txn_total=Decimal('-100.00'), plaid_live=False)
    check('a stale balance on a paused credential is not used',
          close(bal, -100.00) and source == 'sum', '%r %s' % (bal, source))

    inferred = {
        'Home Depot Credit Card': ('credit', 'credit card'),
        'Mastercard': ('credit', 'credit card'),
        'RBC Revolving Credit': ('loan', 'line of credit'),
        'PC Line': ('loan', 'mortgage'),
        'Savings Account': ('depository', 'savings'),
        'Chequing Account': ('depository', 'checking'),
        'RRSP': ('investment', 'investment'),
    }
    for text, expected in inferred.items():
        check('type inferred from %r' % text, _csv_account_type_from_text(text) == expected,
              repr(_csv_account_type_from_text(text)))
    check('an account type the file does not explain is left unknown',
          _csv_account_type_from_text('Payment Account') == (None, None)
          and _csv_account_type_from_text('') == (None, None)
          and _csv_account_type_from_text(None) == (None, None))

    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database balances ===')
    from app import app
    from models import Account, AccountBalanceSnapshot, Credential, Transaction, User, db
    from sqlalchemy import func

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-BAL-%s' % uuid.uuid4().hex[:8]
    inst_csv = '%s Paused' % tag
    inst_live = '%s Live' % tag
    today = datetime.date.today()
    state = {'snap_ids': []}

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('ABORT — no User rows found in the dev database')
            return False
        state['user_id'] = user.id
        before = db.session.query(func.max(AccountBalanceSnapshot.id)).scalar()
        state['snapshot_id_before'] = before or 0

        paused = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=inst_csv,
                            access_token=None, soft_disconnected=True, requires_update=False)
        live = Credential(user_id=user.id, item_id='item-%s-live' % tag, institution_name=inst_live,
                          access_token='token-%s' % tag, soft_disconnected=False, requires_update=False)
        db.session.add_all([paused, live])
        db.session.commit()
        state['cred_ids'] = [paused.id, live.id]

        def new_account(cred, label, mask, type_, subtype, anchor=None, anchor_date=None,
                        current=None, fetched=None, is_closed=False):
            acct = Account(status='Active', credential_id=cred.id,
                           plaid_account_id='acct-%s-%s' % (tag, mask),
                           name='%s %s' % (tag, label), type=type_, subtype=subtype, mask=mask,
                           is_enabled=True,
                           last_known_balance=Decimal(anchor) if anchor is not None else None,
                           balance_date=anchor_date, current_balance=current,
                           balance_fetched_at=fetched, is_closed=is_closed)
            db.session.add(acct)
            db.session.commit()
            state.setdefault('acct_ids', []).append(acct.id)
            return acct

        def add_txn(acct, day, amount):
            txn = Transaction(plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:8]),
                              user_id=user.id, credential_id=acct.credential_id, account_id=acct.id,
                              name='%s %s %s' % (tag, acct.mask, day.isoformat()),
                              amount=Decimal(amount), date=day, iso_currency_code='CAD')
            db.session.add(txn)
            db.session.commit()

        # WestJet 9669 shape: a card anchored at 2,050.00 owed on 2026-07-14, then
        # one purchase and two payments. The post-anchor total is +2,052.16, so
        # 2,050.00 - 2,052.16 = -2.16 owed: the card is paid off, 2.16 in your
        # favour. The old anchor branch ADDED the post-anchor total and showed it
        # as 4,102.16 owed — the PROD number the ticket reports.
        westjet = new_account(paused, 'WestJet', '9669', 'credit', 'credit card',
                              anchor='2050.00', anchor_date=datetime.date(2026, 7, 14))
        add_txn(westjet, datetime.date(2026, 6, 1), '-1500.00')   # before the anchor: never counted
        add_txn(westjet, datetime.date(2026, 7, 20), '-847.84')   # purchase: owed grows
        add_txn(westjet, datetime.date(2026, 8, 5), '1200.00')    # payment: owed shrinks
        add_txn(westjet, datetime.date(2026, 9, 2), '1700.00')

        # RBC 1963 shape: anchored 4,115.68 owed on 2026-10-22, then a 300.00
        # purchase and a 115.68 payment → 4,300.00 owed, shown as -4,300.00.
        rbc = new_account(paused, 'RBC VISA', '1963', 'credit', 'credit card',
                          anchor='4115.68', anchor_date=today - datetime.timedelta(days=3))
        add_txn(rbc, today - datetime.timedelta(days=2), '-300.00')
        add_txn(rbc, today - datetime.timedelta(days=1), '115.68')

        # BMO 6845 shape: a chequing account anchored at 4,381.64 held; the
        # anchor branch ADDS what came after it.
        bmo = new_account(paused, 'BMO Chequing', '6845', 'depository', 'checking',
                          anchor='4381.64', anchor_date=today - datetime.timedelta(days=3))
        add_txn(bmo, today - datetime.timedelta(days=10), '9000.00')   # before the anchor
        add_txn(bmo, today - datetime.timedelta(days=2), '-4136.00')
        add_txn(bmo, today - datetime.timedelta(days=1), '500.00')

        # Home Depot 8134 shape: a card with no anchor and no Plaid balance.
        # -3,000 -2,258.52 +1,000 = -4,258.52 of debt (used to show as +4,258.52).
        hd = new_account(paused, 'Home Depot', '8134', 'credit', 'credit card')
        add_txn(hd, datetime.date(2026, 8, 30), '-3000.00')
        add_txn(hd, datetime.date(2026, 9, 15), '-2258.52')
        add_txn(hd, datetime.date(2026, 9, 30), '1000.00')

        # A cancelled card: listed, balance visible, counted nowhere.
        cancelled = new_account(paused, 'Cancelled Card', '9668', 'credit', 'credit card',
                                is_closed=True)
        add_txn(cancelled, datetime.date(2026, 9, 9), '-5000.00')

        # Scotia Amex 0283 shape: a live Plaid card with a cached balance and no
        # anchor → the Plaid figure is what shows.
        new_account(live, 'Scotia Amex', '0283', 'credit', 'credit card',
                    current=Decimal('309.71'),
                    fetched=datetime.datetime.combine(today, datetime.time(9, 15)))

        loc = new_account(live, 'RBC Line of Credit', '3001', 'loan', 'line of credit',
                          anchor='1410.42', anchor_date=today - datetime.timedelta(days=3),
                          current=Decimal('9999.99'),
                          fetched=datetime.datetime.combine(today, datetime.time(9, 15)))
        add_txn(loc, today - datetime.timedelta(days=1), '210.42')

    snapshot_id_before = state['snapshot_id_before']

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    def balances():
        data = client.get('/api/dashboard').get_json() or {}
        found = {}
        for group in data.get('balances', {}).get('groups', []):
            for inst in group.get('institutions', []):
                if inst.get('name') in (inst_csv, inst_live):
                    found['inst:' + inst['name']] = inst.get('total')
                    for acct in inst.get('accounts', []):
                        found[acct['mask']] = acct
        return found

    try:
        found = balances()

        westjet = found.get('9669') or {}
        check('WestJet-shape card is paid off (2.16 in your favour, not 4,102.16 owed)',
              close(westjet.get('balance'), 2.16), repr(westjet.get('balance')))
        check('its balance says anchor+tx as of the anchor date',
              westjet.get('balance_source') == 'anchor+tx'
              and westjet.get('balance_as_of') == '2026-07-14',
              '%r %r' % (westjet.get('balance_source'), westjet.get('balance_as_of')))
        check('transactions before the anchor are not double counted',
              westjet.get('balance') is not None and abs(westjet['balance']) < 3.0,
              repr(westjet.get('balance')))

        rbc = found.get('1963') or {}
        check('RBC-shape card shows 4,300.00 as debt (-4,300.00)',
              close(rbc.get('balance'), -4300.00), repr(rbc.get('balance')))

        bmo = found.get('6845') or {}
        check('chequing anchor ADDS what came after it (745.64 held)',
              close(bmo.get('balance'), 745.64) and bmo.get('balance_source') == 'anchor+tx',
              '%r %s' % (bmo.get('balance'), bmo.get('balance_source')))

        hd = found.get('8134') or {}
        check('un-anchored card fallback shows debt, not an asset (-4,258.52)',
              close(hd.get('balance'), -4258.52) and hd.get('balance_source') == 'sum',
              '%r %s' % (hd.get('balance'), hd.get('balance_source')))
        check('the fallback says which transaction it is current to',
              hd.get('balance_as_of') == '2026-09-30', repr(hd.get('balance_as_of')))

        scotia = found.get('0283') or {}
        check('live Plaid card shows the Plaid balance (-309.71, source plaid)',
              close(scotia.get('balance'), -309.71) and scotia.get('balance_source') == 'plaid',
              '%r %s' % (scotia.get('balance'), scotia.get('balance_source')))

        loc_entry = found.get('3001') or {}
        check('an anchor outranks a lagging Plaid balance (-1,200.00)',
              close(loc_entry.get('balance'), -1200.00)
              and loc_entry.get('balance_source') == 'anchor+tx',
              '%r %s' % (loc_entry.get('balance'), loc_entry.get('balance_source')))

        cancelled_entry = found.get('9668') or {}
        check('a closed card is still listed with its balance',
              cancelled_entry.get('is_closed') is True and close(cancelled_entry.get('balance'), -5000.00),
              repr(cancelled_entry))
        check('and counts in no institution total',
              close(found.get('inst:' + inst_csv), 2.16 - 4300.00 - 4258.52),
              repr(found.get('inst:' + inst_csv)))
        check('every account offers itself for reconciliation, not only CSV-only ones',
              all(a.get('is_reconcilable') is True for k, a in found.items() if not k.startswith('inst:')),
              repr({k: a.get('is_reconcilable') for k, a in found.items() if not k.startswith('inst:')}))

        scotia_id = scotia.get('id')
        r = client.put('/api/accounts/%s/reconcile' % scotia_id,
                       json={'balance': 250.00, 'as_of': (today - datetime.timedelta(days=5)).isoformat()})
        check('a live Plaid account can be anchored', r.status_code == 200,
              r.get_data(as_text=True)[:200])
        payload = r.get_json() or {}
        check('anchoring returns the computed balance and its source',
              close(payload.get('balance'), -250.00) and payload.get('balance_source') == 'anchor+tx',
              repr(payload))
        found = balances()
        check('the anchor replaces the Plaid figure in the dashboard',
              close(found['0283'].get('balance'), -250.00)
              and found['0283'].get('balance_source') == 'anchor+tx',
              repr(found['0283']))

        r = client.put('/api/accounts/%s/reconcile' % scotia_id,
                       json={'balance': 1.00, 'as_of': (today + datetime.timedelta(days=3)).isoformat()})
        check('an anchor dated in the future is refused', r.status_code == 400, r.get_data(as_text=True)[:120])
        r = client.put('/api/accounts/%s/reconcile' % scotia_id, json={'as_of': '2026-01-01'})
        check('an anchor without a balance is refused', r.status_code == 400, str(r.status_code))

        # Close Home Depot, watch the total shrink, then reopen it.
        r = client.put('/api/accounts/%s/closed' % hd['id'], json={'closed': True})
        check('an account can be marked closed', r.status_code == 200, r.get_data(as_text=True)[:160])
        found = balances()
        check('closing it takes its balance out of the total',
              close(found.get('inst:' + inst_csv), 2.16 - 4300.00), repr(found.get('inst:' + inst_csv)))
        check('and it keeps its history in the tree',
              found['8134'].get('is_closed') is True and close(found['8134'].get('balance'), -4258.52),
              repr(found.get('8134')))
        r = client.put('/api/accounts/%s/closed' % hd['id'], json={'closed': False})
        check('a closed account can be reopened', r.status_code == 200, str(r.status_code))
        found = balances()
        check('reopening puts its balance back in the total',
              close(found.get('inst:' + inst_csv), 2.16 - 4300.00 - 4258.52),
              repr(found.get('inst:' + inst_csv)))
        r = client.put('/api/accounts/%s/closed' % hd['id'], json={'closed': 'yes'})
        check('closed must be a real true/false', r.status_code == 400, str(r.status_code))

        # The daily snapshot the debt history reads.
        with app.app_context():
            from core_views import _record_balance_snapshots
            _record_balance_snapshots(state['user_id'])
            rows = {}
            for acct_id in state['acct_ids']:
                row = AccountBalanceSnapshot.query.filter_by(
                    account_id=acct_id, snapshot_date=today).first()
                if row is not None:
                    state['snap_ids'].append(row.id)
                rows[acct_id] = row
            check('every account got today\'s snapshot',
                  all(rows.get(a) is not None for a in state['acct_ids']),
                  repr({a: (rows.get(a).balance if rows.get(a) else None) for a in state['acct_ids']}))
            anchored = rows.get(scotia_id)
            check('the snapshot stores the dashboard sign and the source',
                  anchored is not None and Decimal(anchored.balance) == Decimal('-250.00')
                  and anchored.source == 'anchor+tx',
                  repr(anchored and (str(anchored.balance), anchored.source)))
            _record_balance_snapshots(state['user_id'])
            still_one = AccountBalanceSnapshot.query.filter_by(
                account_id=scotia_id, snapshot_date=today).count()
            check('re-running the snapshot refreshes the day instead of stacking rows',
                  still_one == 1, repr(still_one))
    finally:
        with app.app_context():
            snap_ids = db.session.query(AccountBalanceSnapshot.id).filter(
                AccountBalanceSnapshot.id > snapshot_id_before).all()
            for (snap_id,) in snap_ids:
                state['snap_ids'].append(snap_id)
            Transaction.query.filter(Transaction.credential_id.in_(state['cred_ids'])) \
                .delete(synchronize_session=False)
            AccountBalanceSnapshot.query.filter(
                AccountBalanceSnapshot.id > snapshot_id_before).delete(synchronize_session=False)
            AccountBalanceSnapshot.query.filter(
                AccountBalanceSnapshot.account_id.in_(state['acct_ids'])).delete(synchronize_session=False)
            Account.query.filter(Account.id.in_(state['acct_ids'])).delete(synchronize_session=False)
            Credential.query.filter(Credential.id.in_(state['cred_ids'])).delete(synchronize_session=False)
            db.session.commit()
            left = (Transaction.query.filter(Transaction.credential_id.in_(state['cred_ids'])).count()
                    + Account.query.filter(Account.id.in_(state['acct_ids'])).count()
                    + Credential.query.filter(Credential.id.in_(state['cred_ids'])).count()
                    + AccountBalanceSnapshot.query.filter(
                        AccountBalanceSnapshot.account_id.in_(state['acct_ids'])).count()
                    + AccountBalanceSnapshot.query.filter(
                        AccountBalanceSnapshot.id > snapshot_id_before).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return not _FAILURES


def main():
    ok_a = part_a()
    ok_b = part_b()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return ok_a and ok_b and not _FAILURES


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
