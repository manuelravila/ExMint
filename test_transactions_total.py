#!/usr/bin/env python
"""test_transactions_total.py — net total of the filtered transactions list.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_transactions_total.py

Hard-aborts unless the configured database URI contains ``_dev_db``. Under the
first user it creates a throwaway credential, account and transactions, then
checks through the Flask test client that ``GET /api/transactions`` returns
``total_amount``:

- the signed net sum of EVERY matching row, not only the current page;
- it follows the filters (search, date range, amount);
- a manual category (an override row, joined by the list query) does not
  double-count its transaction;
- a hidden split parent is not counted, its children are.

Every row it created is deleted and the cleanup is asserted. No pytest is
used (the venv does not have it); exits non-zero on any failure.
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
    return a is not None and abs(a - b) < 1e-9


def main():
    from app import app
    from models import (Account, Credential, CustomCategory, Transaction,
                        TransactionCategoryOverride, User, db)

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-TOTAL-%s' % uuid.uuid4().hex[:10]
    state = {}

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('ABORT — no User rows found in the dev database')
            return False
        state['user_id'] = user.id
        cred = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=tag,
                          access_token=None, soft_disconnected=True, requires_update=False)
        db.session.add(cred)
        db.session.commit()
        state['cred_id'] = cred.id
        acct = Account(status='Active', credential_id=cred.id, plaid_account_id='acct-%s' % tag,
                       name='%s account' % tag, type='depository', subtype='checking', mask='0003',
                       is_enabled=True)
        db.session.add(acct)
        db.session.commit()
        state['acct_id'] = acct.id

        def add_txn(day, amount, name, **extra):
            txn = Transaction(plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:8]),
                              user_id=user.id, credential_id=cred.id, account_id=acct.id,
                              name='%s %s' % (tag, name), amount=Decimal(amount), date=day,
                              iso_currency_code='CAD', **extra)
            db.session.add(txn)
            db.session.commit()
            return txn.id

        t1 = add_txn(datetime.date(2026, 3, 1), '-100.25', 'GROCER')
        t2 = add_txn(datetime.date(2026, 3, 2), '-40.00', 'CAFE')
        t3 = add_txn(datetime.date(2026, 3, 3), '250.00', 'REFUND')
        t4 = add_txn(datetime.date(2026, 4, 1), '-9.75', 'APRIL')
        parent = add_txn(datetime.date(2026, 4, 2), '-80.00', 'SPLITPARENT', has_split_children=True)
        add_txn(datetime.date(2026, 4, 2), '-50.00', 'SPLITCHILD A', parent_transaction_id=parent, is_split_child=True)
        add_txn(datetime.date(2026, 4, 2), '-30.00', 'SPLITCHILD B', parent_transaction_id=parent, is_split_child=True)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    base = '/api/transactions?search=%s&account_ids=%d' % (tag, state['acct_id'])
    try:
        # all rows: -100.25 - 40 + 250 - 9.75 - 50 - 30 = 20.00 (the split parent is hidden)
        data = client.get(base + '&page_size=500').get_json()
        check('response carries total_amount', 'total_amount' in data, repr(list(data)[:12]))
        check('count excludes the split parent (6)', data.get('total_count') == 6, repr(data.get('total_count')))
        check('net total of all rows = 20.00', close(data.get('total_amount'), 20.0), repr(data.get('total_amount')))

        data = client.get(base + '&page_size=2&page=1').get_json()
        check('page 1 holds 2 rows', len(data.get('transactions', [])) == 2)
        check('total covers every page, not just page 1', close(data.get('total_amount'), 20.0), repr(data.get('total_amount')))

        data = client.get(base + '&start_date=2026-03-01&end_date=2026-03-31').get_json()
        check('date filter: March total = 109.75', close(data.get('total_amount'), 109.75), repr(data.get('total_amount')))

        data = client.get(base + '&min_amount=200').get_json()
        check('amount filter: |amount| >= 200 total = 250.00', close(data.get('total_amount'), 250.0), repr(data.get('total_amount')))

        r = client.patch('/api/transactions/bulk-category',
                         json={'transaction_ids': [t1, t2], 'label': '%s Cat' % tag, 'force_create': True})
        check('manual category set → 200', r.status_code == 200, r.get_data(as_text=True)[:200])
        data = client.get(base + '&page_size=500').get_json()
        check('manual-category override does not double rows', data.get('total_count') == 6 and close(data.get('total_amount'), 20.0),
              '%r %r' % (data.get('total_count'), data.get('total_amount')))

        data = client.get(base + '&start_date=2030-01-01').get_json()
        check('no match → total 0', data.get('total_count') == 0 and close(data.get('total_amount'), 0.0),
              '%r %r' % (data.get('total_count'), data.get('total_amount')))
    finally:
        with app.app_context():
            txns = Transaction.query.filter_by(credential_id=state['cred_id']).all()
            txn_ids = [t.id for t in txns]
            if txn_ids:
                TransactionCategoryOverride.query.filter(
                    TransactionCategoryOverride.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
                Transaction.query.filter(Transaction.parent_transaction_id.in_(txn_ids)).delete(synchronize_session=False)
                Transaction.query.filter(Transaction.id.in_(txn_ids)).delete(synchronize_session=False)
            CustomCategory.query.filter(CustomCategory.name.like('%s%%' % tag)).delete(synchronize_session=False)
            Account.query.filter_by(id=state['acct_id']).delete()
            Credential.query.filter_by(id=state['cred_id']).delete()
            db.session.commit()
            left = (Transaction.query.filter(Transaction.name.like('%s%%' % tag)).count()
                    + CustomCategory.query.filter(CustomCategory.name.like('%s%%' % tag)).count()
                    + Credential.query.filter_by(institution_name=tag).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)
