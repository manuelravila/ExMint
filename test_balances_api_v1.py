#!/usr/bin/env python
"""test_balances_api_v1.py — EX-13: the machine API reports and sets computed balances.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_balances_api_v1.py

Under the first user it creates throwaway CSV-only rows and drives, through the
Flask test client (session auth, which ``require_api_auth`` accepts like an API
key, plus one call made with a real X-API-Key):

- ``GET /api/v1/accounts`` now carries the balance the dashboard shows with its
  ``balance_source`` (plaid | anchor+tx | sum) and ``balance_as_of``, next to the
  raw stored figures it already returned;
- ``PUT /api/v1/accounts/<id>/anchor`` sets the anchor a balance is computed
  from, back-dated with ``as_of`` so a script can record a statement balance
  from an older date; balance, source and date come back in the response;
- ``PUT /api/v1/accounts/<id>/type`` finishes an account an import could not
  identify — and the sign of the whole account flips with the answer;
- ``PUT /api/v1/accounts/<id>/closed`` retires a cancelled account: its history
  stays, its balance is still reported, and it counts in no total;
- bad input is rejected (no balance, a future as_of, an unknown type, an account
  that is not yours) instead of half-applied.

Every row it created, the balance snapshots included, is deleted and the cleanup
is asserted.  No pytest is used (the venv does not have it); exits non-zero on
any failure.
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


def main():
    from app import app
    from models import Account, AccountBalanceSnapshot, ApiKey, Credential, Transaction, User, db
    from sqlalchemy import func

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-V1BAL-%s' % uuid.uuid4().hex[:8]
    institution = '%s Cards' % tag
    state = {'key_ids': []}

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('ABORT — no User rows found in the dev database')
            return False
        state['user_id'] = user.id
        state['snapshot_id_before'] = db.session.query(func.max(AccountBalanceSnapshot.id)).scalar() or 0

        cred = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=institution,
                          access_token=None, soft_disconnected=True, requires_update=False)
        db.session.add(cred)
        db.session.commit()
        state['cred_id'] = cred.id

        def new_account(label, mask, type_=None, subtype=None):
            acct = Account(status='Active', credential_id=cred.id,
                           plaid_account_id='csv_acct_%s' % uuid.uuid4().hex,
                           name='%s %s' % (tag, label), type=type_, subtype=subtype, mask=mask,
                           is_enabled=True)
            db.session.add(acct)
            db.session.commit()
            state.setdefault('acct_ids', []).append(acct.id)
            return acct

        def add_txn(acct, day, amount):
            txn = Transaction(plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:8]),
                              user_id=user.id, credential_id=cred.id, account_id=acct.id,
                              name='%s %s %s' % (tag, acct.mask, day.isoformat()),
                              amount=Decimal(amount), date=day, iso_currency_code='CAD')
            db.session.add(txn)
            db.session.commit()

        # Home Depot 8134 shape, but with no type: an import that could not tell
        # what the account is, which is exactly what v1.19 asks the user about.
        unknown = new_account('Mystery Card', '8134')
        add_txn(unknown, datetime.date(2026, 8, 30), '-3000.00')
        add_txn(unknown, datetime.date(2026, 9, 15), '-2258.52')
        add_txn(unknown, datetime.date(2026, 9, 30), '1000.00')

        # WestJet 9669 shape: a card the script anchors from an old statement.
        anchored = new_account('WestJet', '9669', 'credit', 'credit card')
        add_txn(anchored, datetime.date(2026, 6, 1), '-1500.00')
        add_txn(anchored, datetime.date(2026, 7, 20), '-847.84')
        add_txn(anchored, datetime.date(2026, 8, 5), '1200.00')
        add_txn(anchored, datetime.date(2026, 9, 2), '1700.00')

        # An API key, so the header path is exercised too, not only the session.
        from api_views import _generate_api_key, _hash_api_key
        full_key, _raw_key, prefix = _generate_api_key()
        api_key = ApiKey(key_hash=_hash_api_key(full_key), key_prefix=prefix,
                         user_id=user.id, name='%s key' % tag)
        db.session.add(api_key)
        db.session.commit()
        state['key_ids'].append(api_key.id)
        api_headers = {'X-API-Key': full_key}

        # Ids, not rows: outside the app context an ORM instance is detached.
        unknown_id, anchored_id = [obj.id for obj in (unknown, anchored)]

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    def v1_accounts(headers=None):
        data = client.get('/api/v1/accounts', headers=headers).get_json() or {}
        return {a['id']: a for a in data.get('accounts', [])}

    try:
        accounts = v1_accounts()
        unknown_entry = accounts.get(unknown_id) or {}
        check('v1 GET /accounts reports the computed balance (-4,258.52)',
              close(unknown_entry.get('balance'), -4258.52) and unknown_entry.get('balance_source') == 'sum',
              repr(unknown_entry))
        check('v1 says which transaction that balance is current to',
              unknown_entry.get('balance_as_of') == '2026-09-30', repr(unknown_entry.get('balance_as_of')))
        check('v1 keeps the raw stored figures it already returned',
              'current_balance' in unknown_entry and 'last_known_balance' in unknown_entry
              and 'balance_date' in unknown_entry, repr(sorted(unknown_entry)))
        check('an account with no type is reported as it is, not guessed',
              unknown_entry.get('type') is None, repr(unknown_entry.get('type')))

        # Anchor it while its type is still unknown: the only reading left is
        # money held, which is the wrong reading for a card.  This is why the
        # import asks instead of guessing.
        r = client.put('/api/v1/accounts/%s/anchor' % unknown_id,
                       json={'balance': 5000.00, 'as_of': '2026-08-29'})
        check('an untyped account can be anchored too', r.status_code == 200,
              r.get_data(as_text=True)[:200])
        payload = r.get_json() or {}
        check('an unknown type reads the anchor as money held (5,000.00 less 4,258.52 = 741.48)',
              close(payload.get('balance'), 741.48) and payload.get('balance_source') == 'anchor+tx',
              repr(payload))

        # The answer then re-reads the very same anchor as debt.
        r = client.put('/api/v1/accounts/%s/type' % unknown_id, json={'account_type': 'credit_card'})
        check('v1 can type an account an import could not identify', r.status_code == 200,
              r.get_data(as_text=True)[:200])
        payload = r.get_json() or {}
        check('typing it flips the same anchor into debt (-9,258.52 owed)',
              close(payload.get('balance'), -9258.52) and payload.get('type') == 'credit', repr(payload))
        accounts = v1_accounts()
        check('the dashboard sign follows the type it was given',
              close(accounts[unknown_id].get('balance'), -9258.52)
              and accounts[unknown_id].get('type') == 'credit', repr(accounts[unknown_id]))
        r = client.put('/api/v1/accounts/%s/type' % unknown_id, json={'account_type': 'banana'})
        check('an unknown type is refused', r.status_code == 400, r.get_data(as_text=True)[:160])

        # Anchor from a script, back-dated to the statement's own date.
        r = client.put('/api/v1/accounts/%s/anchor' % anchored_id,
                       json={'balance': 2050.00, 'as_of': '2026-07-14'})
        check('v1 anchor accepted', r.status_code == 200, r.get_data(as_text=True)[:200])
        payload = r.get_json() or {}
        check('the anchor is stored with the date it was back-dated to',
              payload.get('last_known_balance') == 2050.0
              and payload.get('balance_date') == '2026-07-14', repr(payload))
        check('anchoring returns the computed balance: 2,050.00 owed less 2,052.16 of payments',
              close(payload.get('balance'), 2.16) and payload.get('balance_source') == 'anchor+tx',
              repr(payload))
        accounts = v1_accounts()
        check('v1 GET /accounts then shows the anchored balance and its source',
              close(accounts[anchored_id].get('balance'), 2.16)
              and accounts[anchored_id].get('balance_source') == 'anchor+tx'
              and accounts[anchored_id].get('balance_as_of') == '2026-07-14',
              repr(accounts[anchored_id]))

        r = client.get('/api/v1/accounts/%s/balance' % anchored_id)
        check('v1 reports one account\'s balance on its own', r.status_code == 200, str(r.status_code))
        single = r.get_json() or {}
        check('and it agrees with the list',
              close(single.get('balance'), 2.16) and single.get('balance_source') == 'anchor+tx',
              repr(single))

        r = client.put('/api/v1/accounts/%s/anchor' % anchored_id, json={'as_of': '2026-07-14'})
        check('an anchor without a balance is refused', r.status_code == 400, str(r.status_code))
        r = client.put('/api/v1/accounts/%s/anchor' % anchored_id,
                       json={'balance': 1.00, 'as_of': 'not-a-date'})
        check('a malformed as_of is refused', r.status_code == 400, r.get_data(as_text=True)[:160])
        future = (datetime.date.today() + datetime.timedelta(days=4)).isoformat()
        r = client.put('/api/v1/accounts/%s/anchor' % anchored_id,
                       json={'balance': 1.00, 'as_of': future})
        check('a future as_of is refused', r.status_code == 400, r.get_data(as_text=True)[:160])
        r = client.put('/api/v1/accounts/%s/anchor' % anchored_id, json={'balance': 'x'})
        check('a non-numeric balance is refused', r.status_code == 400, str(r.status_code))
        r = client.put('/api/v1/accounts/999999999/anchor', json={'balance': 1.00})
        check('an account that is not yours is a 404, not a silent no-op', r.status_code == 404,
              str(r.status_code))
        with app.app_context():
            anchored_row = db.session.get(Account, anchored_id)
            check('the refused calls left the anchor untouched',
                  anchored_row.balance_date == datetime.date(2026, 7, 14), repr(anchored_row.balance_date))

        # A cancelled card: closed, not deleted.
        r = client.put('/api/v1/accounts/%s/closed' % unknown_id, json={'closed': True})
        check('v1 can close a cancelled account', r.status_code == 200, r.get_data(as_text=True)[:160])
        accounts = v1_accounts()
        check('a closed account is still listed with its history and balance',
              accounts[unknown_id].get('is_closed') is True
              and close(accounts[unknown_id].get('balance'), -9258.52), repr(accounts[unknown_id]))
        with app.app_context():
            check('and closing it kept every transaction',
                  Transaction.query.filter_by(account_id=unknown_id).count() == 3,
                  repr(Transaction.query.filter_by(account_id=unknown_id).count()))
        r = client.put('/api/v1/accounts/%s/closed' % unknown_id, json={'closed': 'true'})
        check('closed must be a real true/false', r.status_code == 400, str(r.status_code))
        client.put('/api/v1/accounts/%s/closed' % unknown_id, json={'closed': False})

        # The same balance answers through the X-API-Key path.
        keyed = v1_accounts(headers=api_headers)
        check('the same endpoints work with an X-API-Key',
              close(keyed.get(anchored_id, {}).get('balance'), 2.16)
              and keyed.get(unknown_id, {}).get('type') == 'credit', repr(sorted(keyed)))
        bad = client.get('/api/v1/accounts', headers={'X-API-Key': 'exm_not_a_key_at_all'})
        check('a bogus key is rejected', bad.status_code == 401, str(bad.status_code))

        # The daily snapshot these routes trigger.
        with app.app_context():
            row = AccountBalanceSnapshot.query.filter_by(
                account_id=anchored_id, snapshot_date=datetime.date.today()).first()
            check('the v1 routes recorded today\'s snapshot for the account',
                  row is not None and Decimal(row.balance) == Decimal('2.16') and row.source == 'anchor+tx',
                  repr(row and (str(row.balance), row.source)))
    finally:
        snapshot_id_before = state['snapshot_id_before']
        with app.app_context():
            Transaction.query.filter(Transaction.credential_id == state['cred_id']) \
                .delete(synchronize_session=False)
            AccountBalanceSnapshot.query.filter(
                AccountBalanceSnapshot.id > snapshot_id_before).delete(synchronize_session=False)
            Account.query.filter(Account.id.in_(state['acct_ids'])).delete(synchronize_session=False)
            Credential.query.filter(Credential.id == state['cred_id']).delete(synchronize_session=False)
            ApiKey.query.filter(ApiKey.id.in_(state['key_ids'])).delete(synchronize_session=False)
            db.session.commit()
            left = (Transaction.query.filter(Transaction.credential_id == state['cred_id']).count()
                    + Account.query.filter(Account.id.in_(state['acct_ids'])).count()
                    + Credential.query.filter(Credential.id == state['cred_id']).count()
                    + ApiKey.query.filter(ApiKey.id.in_(state['key_ids'])).count()
                    + AccountBalanceSnapshot.query.filter(
                        AccountBalanceSnapshot.id > snapshot_id_before).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return not _FAILURES


if __name__ == '__main__':
    result = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if result else 1)
