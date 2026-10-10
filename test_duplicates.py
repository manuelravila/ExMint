#!/usr/bin/env python
"""test_duplicates.py — duplicate finder (maintenance) and selective removal.

Run from the repository root:

    ./venv/bin/python test_duplicates.py                     # Part A only
    EXMINT_LIVE_TEST=1 ./venv/bin/python test_duplicates.py  # Part A + Part B

Part A needs no database: ``_names_look_alike`` and the pure pairing core
``_pair_cross_account_rows`` (supplementary-card mirror with text/day
differences, primary card kept, transfers and other banks never paired, split
parent never removed).

Part B is an opt-in live check against the DEV database (hard-aborts unless the
configured database URI contains ``_dev_db``). With its own throw-away user,
one connection with a primary card (more history) and a supplementary card:

- mirror rows a day apart / differently formatted are found and the primary
  card's row is kept;
- two identical rows from a CSV statement are NOT flagged, two identical
  Plaid rows are;
- every group has a reason;
- ``POST /api/maintenance/deduplicate`` with ``ids`` removes only those,
  reports ids that are not candidates in ``skipped_ids``, and leaves the rest.

Everything it creates is deleted in a ``finally`` block. No pytest is used;
exits non-zero on any failure.
"""

import datetime
import os
import sys
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from core_views import _names_look_alike, _pair_cross_account_rows

_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


def part_a():
    print('=== Part A: pure matching ===')
    check('punctuation differs', _names_look_alike('SOLID WASTE-BERMONDSEY TORONTO', 'SOLID WASTE BERMONDSEY TORONTO'))
    check('same first word, different format', _names_look_alike('Metro TORONTO 020 (Google Pay)', 'METRO 37'))
    check('different merchants', not _names_look_alike('Freshco SCARBOROUGH', 'LOBLAWS #1021'))

    d = datetime.date

    def txn(i, acct, day, amount, name, split=False):
        return SimpleNamespace(id=i, account_id=acct, date=day, amount=Decimal(amount), name=name,
                               has_split_children=split)

    primary_history = [(txn(100 + i, 1, d(2026, 1, 1), '-1.00', 'FILLER %d' % i), 7, 'credit') for i in range(5)]
    rows = primary_history + [
        (txn(1, 1, d(2026, 2, 20), '-40.00', 'SOLID WASTE-BERMONDSEY TORONTO'), 7, 'credit'),
        (txn(2, 2, d(2026, 2, 21), '-40.00', 'SOLID WASTE BERMONDSEY TORONTO'), 7, 'credit'),
        (txn(3, 1, d(2026, 2, 26), '-9.22', 'Metro TORONTO 020 (Google Pay)'), 7, 'credit'),
        (txn(4, 2, d(2026, 2, 26), '-9.22', 'METRO 37'), 7, 'credit'),
        (txn(5, 1, d(2026, 3, 1), '-12.00', 'CAFE'), 7, 'credit'),
        (txn(6, 2, d(2026, 3, 4), '-12.00', 'CAFE'), 7, 'credit'),            # 3 days apart: no
        (txn(7, 3, d(2026, 3, 5), '1600.00', 'PAYMENT FROM'), 7, 'depository'),
        (txn(8, 1, d(2026, 3, 5), '1600.00', 'PAYMENT FROM'), 7, 'credit'),   # card vs chequing: no
        (txn(9, 1, d(2026, 3, 6), '-30.00', 'SHELL'), 7, 'credit'),
        (txn(10, 4, d(2026, 3, 6), '-30.00', 'SHELL'), 8, 'credit'),          # another bank: no
        (txn(11, 1, d(2026, 3, 7), '-50.00', 'COSTCO'), 7, 'credit'),
        (txn(12, 2, d(2026, 3, 7), '-50.00', 'COSTCO', split=True), 7, 'credit'),
    ]
    pairs = {(k.id, dup.id) for k, dup in _pair_cross_account_rows(rows, set())}
    check('mirror a day apart, primary kept', (1, 2) in pairs, repr(pairs))
    check('different format same day, primary kept', (3, 4) in pairs, repr(pairs))
    check('3 days apart not paired', not any(5 in p for p in pairs))
    check('card vs chequing not paired', not any(7 in p for p in pairs))
    check('different bank not paired', not any(10 in p for p in pairs))
    check('split parent is kept, not removed', (12, 11) in pairs, repr(pairs))
    check('exactly those pairs', len(pairs) == 3, repr(pairs))
    check('excluded ids are skipped', not _pair_cross_account_rows(rows, {1, 2, 3, 4, 11, 12}))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database check ===')
    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    from app import app
    from models import Account, Credential, Transaction, User, db

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])
    ok_before = len(_FAILURES)
    tag = 'EXMINT-LIVE-DUP-%s' % uuid4().hex[:8]

    with app.app_context():
        user = User(email='%s@example.invalid' % tag.lower(), status='Active', role='User')
        user.set_password('live-test')
        db.session.add(user)
        db.session.flush()
        cred = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=tag,
                          access_token=None, soft_disconnected=True, requires_update=False)
        db.session.add(cred)
        db.session.flush()
        primary = Account(status='Active', credential_id=cred.id, plaid_account_id='p-%s' % tag, name='Gold',
                          type='credit', subtype='credit card', mask='0283', is_enabled=True)
        supp = Account(status='Active', credential_id=cred.id, plaid_account_id='s-%s' % tag, name='Gold',
                       type='credit', subtype='credit card', mask='2532', is_enabled=True)
        db.session.add_all([primary, supp])
        db.session.flush()
        ids = {}

        def add(key, acct, day, amount, name, source='plaid'):
            pid = ('csv_' if source == 'csv' else 'plaid-') + uuid4().hex
            t = Transaction(plaid_transaction_id=pid, user_id=user.id, credential_id=cred.id, account_id=acct.id,
                            name=name, amount=Decimal(amount), date=datetime.date.fromisoformat(day),
                            iso_currency_code='CAD', pending=False)
            db.session.add(t)
            db.session.flush()
            ids[key] = t.id

        for i in range(4):
            add('fill%d' % i, primary, '2026-01-0%d' % (i + 1), '-1.00', 'FILLER %d' % i)
        add('p1', primary, '2026-02-20', '-40.00', 'SOLID WASTE-BERMONDSEY TORONTO')
        add('s1', supp, '2026-02-21', '-40.00', 'SOLID WASTE BERMONDSEY TORONTO')
        add('p2', primary, '2026-02-26', '-9.22', 'Metro TORONTO 020 (Google Pay)')
        add('s2', supp, '2026-02-26', '-9.22', 'METRO 37')
        add('c1', primary, '2026-03-02', '-67.89', 'ADOM SALUD', source='csv')
        add('c2', primary, '2026-03-02', '-67.89', 'ADOM SALUD', source='csv')
        add('q1', primary, '2026-03-03', '-15.00', 'DOUBLE SYNC')
        add('q2', primary, '2026-03-03', '-15.00', 'DOUBLE SYNC')
        db.session.commit()
        user_id, cred_id = user.id, cred.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    try:
        data = client.get('/api/maintenance/duplicates').get_json()
        groups = data.get('groups', [])
        pairs = {(g['keep']['id'], tuple(t['id'] for t in g['remove'])) for g in groups}
        check('fuzzy mirror 1 found, primary kept', (ids['p1'], (ids['s1'],)) in pairs, repr(pairs))
        check('fuzzy mirror 2 found, primary kept', (ids['p2'], (ids['s2'],)) in pairs, repr(pairs))
        check('two identical CSV statement rows not flagged',
              not any(ids['c1'] in (g['keep']['id'],) + tuple(t['id'] for t in g['remove']) for g in groups))
        check('two identical Plaid rows flagged', (ids['q1'], (ids['q2'],)) in pairs, repr(pairs))
        check('3 groups, every one with a reason', len(groups) == 3 and all(g.get('reason') for g in groups),
              repr([g.get('reason') for g in groups]))

        r = client.post('/api/maintenance/deduplicate', json={'ids': [ids['s1'], ids['c1']]})
        body = r.get_json() or {}
        check('selective removal: only the approved candidate', r.status_code == 200 and body.get('removed_ids') == [ids['s1']],
              '%s %s' % (r.status_code, body))
        check('non-candidate id reported as skipped', body.get('skipped_ids') == [ids['c1']], repr(body.get('skipped_ids')))
        with app.app_context():
            removed = {t.id for t in Transaction.query.filter_by(user_id=user_id, is_removed=True)}
        check('only that row is marked removed', removed == {ids['s1']}, repr(removed))
        data = client.get('/api/maintenance/duplicates').get_json()
        check('the unapproved groups are still listed', data.get('total_groups') == 2, repr(data.get('total_groups')))
        r = client.post('/api/maintenance/deduplicate', json={'ids': 'nope'})
        check('bad ids → 400', r.status_code == 400, str(r.status_code))
    finally:
        with app.app_context():
            Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            Account.query.filter_by(credential_id=cred_id).delete(synchronize_session=False)
            Credential.query.filter_by(id=cred_id).delete(synchronize_session=False)
            User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()
            left = Transaction.query.filter_by(user_id=user_id).count() + User.query.filter_by(id=user_id).count()
            check('cleanup removed every test row', left == 0, '%d left' % left)
    return len(_FAILURES) == ok_before


if __name__ == '__main__':
    a = part_a()
    b = part_b()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if (a and b) else 1)
