#!/usr/bin/env python
"""test_api_v1_projects.py — machine API v1 project endpoints.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_api_v1_projects.py

Hard-aborts unless the configured database URI contains ``_dev_db``. Under the
first user it creates a throwaway credential, account and transactions and
drives, through the Flask test client (session auth, which ``require_api_auth``
accepts like an API key):

- ``POST /api/v1/projects`` (201, duplicate name 409, short name 400);
- ``PATCH /api/v1/transactions/bulk-project`` (assign, unknown project 404,
  foreign/unknown transaction 404, clear with null);
- ``GET /api/v1/projects`` totals, and that the UI routes still agree.

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


def main():
    from app import app
    from models import Account, Credential, Project, Transaction, User, db

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-V1PROJ-%s' % uuid.uuid4().hex[:10]
    state = {'project_ids': []}

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
                       name='%s account' % tag, type='credit', subtype='credit card', mask='0004',
                       is_enabled=True)
        db.session.add(acct)
        db.session.commit()
        state['acct_id'] = acct.id
        ids = []
        for day, amount, name in ((datetime.date(2024, 10, 9), '-102.26', 'BOXTY HOUSE DUBLIN'),
                                  (datetime.date(2024, 10, 10), '-45.79', 'CAVERN CLUB LIVERPOOL'),
                                  (datetime.date(2024, 10, 20), '12.00', 'REFUND AMSTERDAM')):
            txn = Transaction(plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:8]),
                              user_id=user.id, credential_id=cred.id, account_id=acct.id,
                              name='%s %s' % (tag, name), amount=Decimal(amount), date=day,
                              iso_currency_code='CAD')
            db.session.add(txn)
            db.session.commit()
            ids.append(txn.id)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    try:
        r = client.post('/api/v1/projects', json={'name': '%s Europe 2024' % tag})
        check('v1 create → 201', r.status_code == 201, r.get_data(as_text=True)[:200])
        project = (r.get_json() or {}).get('project') or {}
        if project.get('id'):
            state['project_ids'].append(project['id'])
        r = client.post('/api/v1/projects', json={'name': ('%s europe 2024' % tag).upper()})
        check('v1 duplicate name → 409', r.status_code == 409, str(r.status_code))
        r = client.post('/api/v1/projects', json={'name': 'ab'})
        check('v1 short name → 400', r.status_code == 400, str(r.status_code))

        r = client.patch('/api/v1/transactions/bulk-project',
                         json={'transaction_ids': ids, 'project_id': project.get('id')})
        check('v1 bulk assign → 200', r.status_code == 200, r.get_data(as_text=True)[:200])
        rows = (r.get_json() or {}).get('transactions', [])
        check('rows carry the project', len(rows) == 3 and all(t['project_id'] == project.get('id') for t in rows))
        r = client.patch('/api/v1/transactions/bulk-project',
                         json={'transaction_ids': ids[:1], 'project_id': 999999999})
        check('v1 unknown project → 404', r.status_code == 404, str(r.status_code))
        r = client.patch('/api/v1/transactions/bulk-project',
                         json={'transaction_ids': [ids[0], 999999999], 'project_id': project.get('id')})
        check('v1 unknown transaction → 404', r.status_code == 404, str(r.status_code))

        v1 = {p['id']: p for p in client.get('/api/v1/projects').get_json()['projects']}
        ui = {p['id']: p for p in client.get('/api/projects').get_json()['projects']}
        p = v1.get(project.get('id'))
        check('v1 list has the project', p is not None)
        check('v1 total = signed net sum (-136.05)', p and abs(p['total'] - (-136.05)) < 1e-9, repr(p and p['total']))
        check('v1 and UI lists agree', p == ui.get(project.get('id')))

        r = client.patch('/api/v1/transactions/bulk-project', json={'transaction_ids': ids[2:], 'project_id': None})
        check('v1 clear with null → 200', r.status_code == 200 and r.get_json()['transactions'][0]['project_id'] is None)
        p = {x['id']: x for x in client.get('/api/v1/projects').get_json()['projects']}.get(project.get('id'))
        check('total after clearing the refund = -148.05', p and abs(p['total'] - (-148.05)) < 1e-9, repr(p and p['total']))
    finally:
        with app.app_context():
            Transaction.query.filter_by(credential_id=state['cred_id']).delete(synchronize_session=False)
            for pid in state['project_ids']:
                Project.query.filter_by(id=pid).delete()
            Account.query.filter_by(id=state['acct_id']).delete()
            Credential.query.filter_by(id=state['cred_id']).delete()
            db.session.commit()
            left = (Transaction.query.filter(Transaction.name.like('%s%%' % tag)).count()
                    + Project.query.filter(Project.name.like('%s%%' % tag)).count()
                    + Credential.query.filter_by(institution_name=tag).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)
