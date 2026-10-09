#!/usr/bin/env python
"""test_projects.py — Projects feature and override stickiness.

Run from the repository root:

    ./venv/bin/python test_projects.py                     # Part A only
    EXMINT_LIVE_TEST=1 ./venv/bin/python test_projects.py  # Part A + Part B

Part A needs no database: it unit-tests the project serializer (year/month
tree, signed totals) and the name validation.

Part B is an opt-in live check against the DEV database (hard-aborts unless
the configured database URI contains ``_dev_db``). Under the first user it
creates a throwaway credential, account and transactions, then drives the
UI endpoints through the Flask test client:

- projects CRUD (create, duplicate name, short name, rename, delete keeps
  the transactions and unassigns them);
- bulk assign / clear, totals by year and month, the ``project_id`` filter
  on the list and on the CSV export, and a split copying the parent's project;
- regression: a manual category and a split are NOT reversed when the
  category rules are re-applied (``apply_rules_to_transactions``).

Every row it created is deleted and the cleanup is asserted. No pytest is
used (the venv does not have it); exits non-zero on any failure.
"""

import datetime
import os
import sys
import uuid
from decimal import Decimal

from core_views import _serialize_project, _validate_project_name

_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


class _FakeProject:
    id = 7
    name = 'Trip to Colombia'
    color = '#2C6B4F'
    created_at = None
    updated_at = None


def part_a():
    print('=== Part A: serializer and validation ===')
    stats = {
        'count': 3,
        'total': Decimal('-150.50'),
        'years': {
            2025: {'total': Decimal('-100.00'), 'count': 1,
                   'months': {12: {'total': Decimal('-100.00'), 'count': 1}}},
            2026: {'total': Decimal('-50.50'), 'count': 2,
                   'months': {1: {'total': Decimal('-70.50'), 'count': 1},
                              2: {'total': Decimal('20.00'), 'count': 1}}},
        },
    }
    out = _serialize_project(_FakeProject(), stats)
    check('grand total is the signed net sum', out['total'] == -150.5, repr(out['total']))
    check('transaction count', out['transaction_count'] == 3)
    check('years newest first', [y['year'] for y in out['by_year']] == [2026, 2025])
    check('months newest first', [m['month'] for m in out['by_year'][0]['by_month']] == [2, 1])
    check('a refund counts positive', out['by_year'][0]['by_month'][0]['total'] == 20.0)
    empty = _serialize_project(_FakeProject())
    check('a project with no transactions totals 0', empty['total'] == 0 and empty['by_year'] == [])

    check('name is trimmed', _validate_project_name('  Home Renovation ') == 'Home Renovation')
    for bad in ('ab', '', None, 'x' * 121):
        try:
            _validate_project_name(bad)
            check('rejects %r' % (bad if bad is None or len(bad) < 10 else bad[:5] + '…'), False)
        except ValueError:
            check('rejects %r' % (bad if bad is None or len(bad) < 10 else bad[:5] + '…'), True)
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database check ===')
    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    from app import app
    from models import (Account, CategoryRule, Credential, CustomCategory, Project,
                        Transaction, TransactionCategoryOverride, User, db)
    from core_views import apply_rules_to_transactions

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-PROJ-%s' % uuid.uuid4().hex[:10]
    state = {'cat_ids': [], 'project_ids': []}
    ok_before = len(_FAILURES)

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('Part B: ABORT — no User rows found in the dev database')
            return False
        state['user_id'] = user.id
        cred = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=tag,
                          access_token=None, soft_disconnected=True, requires_update=False)
        db.session.add(cred)
        db.session.commit()
        state['cred_id'] = cred.id
        acct = Account(status='Active', credential_id=cred.id, plaid_account_id='acct-%s' % tag,
                       name='%s account' % tag, type='depository', subtype='checking', mask='0002',
                       is_enabled=True)
        db.session.add(acct)
        db.session.commit()
        state['acct_id'] = acct.id

        def add_txn(day, amount, name):
            txn = Transaction(plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:8]),
                              user_id=user.id, credential_id=cred.id, account_id=acct.id,
                              name='%s %s' % (tag, name), amount=Decimal(amount), date=day,
                              iso_currency_code='CAD')
            db.session.add(txn)
            db.session.commit()
            return txn.id

        t1 = add_txn(datetime.date(2025, 12, 20), '-100.00', 'HOTEL')
        t2 = add_txn(datetime.date(2026, 1, 5), '-70.50', 'FLIGHT')
        t3 = add_txn(datetime.date(2026, 2, 2), '20.00', 'REFUND')
        t4 = add_txn(datetime.date(2026, 2, 3), '-60.00', 'SPLITME')
        t5 = add_txn(datetime.date(2026, 2, 4), '-12.00', 'RULEMATCH')
    ids = [t1, t2, t3, t4, t5]

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    try:
        # --- CRUD ---
        r = client.post('/api/projects', json={'name': '%s Trip' % tag, 'color': '#aa3300'})
        check('create project → 201', r.status_code == 201, r.get_data(as_text=True)[:200])
        project = r.get_json()['project']
        state['project_ids'].append(project['id'])
        check('color normalized', project['color'] == '#AA3300', repr(project['color']))
        r = client.post('/api/projects', json={'name': ('%s trip' % tag).lower()})
        check('duplicate name (case-insensitive) → 409', r.status_code == 409, str(r.status_code))
        r = client.post('/api/projects', json={'name': 'ab'})
        check('short name → 400', r.status_code == 400, str(r.status_code))

        # --- bulk assign ---
        r = client.patch('/api/transactions/bulk-project', json={'transaction_ids': [t1, t2, t3, t4], 'project_id': project['id']})
        check('bulk assign → 200', r.status_code == 200, r.get_data(as_text=True)[:200])
        rows = r.get_json()['transactions']
        check('serialized rows carry the project', all(t['project_id'] == project['id'] and t['project_name'] for t in rows))
        r = client.patch('/api/transactions/bulk-project', json={'transaction_ids': [t1], 'project_id': 999999999})
        check('unknown project → 404', r.status_code == 404, str(r.status_code))
        r = client.patch('/api/transactions/bulk-project', json={'transaction_ids': [], 'project_id': project['id']})
        check('empty id list → 400', r.status_code == 400, str(r.status_code))

        # --- totals ---
        listed = {p['id']: p for p in client.get('/api/projects').get_json()['projects']}
        p = listed.get(project['id'])
        check('listed with totals', p is not None)
        check('grand total = signed net sum (-210.50)', p and abs(p['total'] - (-210.5)) < 1e-9, repr(p and p['total']))
        check('count = 4', p and p['transaction_count'] == 4)
        years = {y['year']: y for y in p['by_year']} if p else {}
        check('two years', sorted(years) == [2025, 2026], repr(sorted(years)))
        months_2026 = {m['month']: m for m in years.get(2026, {}).get('by_month', [])}
        check('2026 months Jan and Feb', sorted(months_2026) == [1, 2], repr(sorted(months_2026)))
        check('Feb 2026 total = -40.00 (refund nets out)', 2 in months_2026 and abs(months_2026[2]['total'] - (-40.0)) < 1e-9)

        # --- filter + export ---
        r = client.get('/api/transactions?project_id=%d&page_size=500' % project['id'])
        got = {t['id'] for t in r.get_json()['transactions']}
        check('project filter returns exactly the project rows', got == {t1, t2, t3, t4}, repr(got))
        r = client.get('/api/transactions?project_id=%d&start_date=2026-02-01&end_date=2026-02-28' % project['id'])
        got = {t['id'] for t in r.get_json()['transactions']}
        check('project + month filter (drill-down)', got == {t3, t4}, repr(got))
        r = client.get('/api/transactions?project_id=none&search=%s&page_size=500' % tag)
        got = {t['id'] for t in r.get_json()['transactions']}
        check('project_id=none returns the unassigned row', got == {t5}, repr(got))
        r = client.get('/api/transactions/export?format=csv&project_id=%d' % project['id'])
        body = r.get_data(as_text=True)
        check('CSV export honours the project filter', r.status_code == 200 and 'HOTEL' in body and 'RULEMATCH' not in body)

        # --- regression: manual category and split survive rule re-application ---
        with app.app_context():
            cat_a = CustomCategory(user_id=state['user_id'], name='%s CatA' % tag, color='#111111')
            db.session.add(cat_a)
            db.session.commit()
            state['cat_ids'].append(cat_a.id)
            state['cat_a'] = cat_a.id
            rule = CategoryRule(user_id=state['user_id'], category_id=cat_a.id,
                                text_to_match='*%s*' % tag, field_to_match='description')
            db.session.add(rule)
            db.session.commit()
            state['rule_id'] = rule.id

        r = client.patch('/api/transactions/%d/category' % t5, json={'label': '%s CatB' % tag, 'force_create': True})
        check('manual category set → 200', r.status_code == 200, r.get_data(as_text=True)[:200])
        r = client.post('/api/transactions/%d/split' % t4, json={'splits': [
            {'description': 'part one', 'category': '%s SplitX' % tag, 'amount': '35.00'},
            {'description': 'part two', 'category': '%s SplitY' % tag, 'amount': '25.00'},
        ]})
        check('split → 2xx', r.status_code in (200, 201), r.get_data(as_text=True)[:200])

        with app.app_context():
            for name in ('CatB', 'SplitX', 'SplitY'):
                c = CustomCategory.query.filter_by(user_id=state['user_id'], name='%s %s' % (tag, name)).first()
                if c:
                    state['cat_ids'].append(c.id)
            children = Transaction.query.filter_by(parent_transaction_id=t4).all()
            before = {c.id: c.custom_category_id for c in children}
            check('split children inherit the project', children and all(c.project_id == project['id'] for c in children))
            summary = apply_rules_to_transactions(state['user_id'], transaction_ids=ids + list(before))
            db.session.commit()
            check('the rule matched something (it is live)', summary['matched_transactions'] >= 1, repr(summary))
            override = db.session.get(TransactionCategoryOverride, t5)
            cat_b = CustomCategory.query.filter_by(user_id=state['user_id'], name='%s CatB' % tag).first()
            check('manual category NOT reversed by the rule',
                  override is not None and cat_b is not None and override.custom_category_id == cat_b.id)
            after = {c.id: c.custom_category_id for c in Transaction.query.filter_by(parent_transaction_id=t4).all()}
            check('split children keep their categories', after == before, '%r vs %r' % (before, after))
            parent = db.session.get(Transaction, t4)
            check('split stays split', parent.has_split_children and len(after) == 2)
            untouched = db.session.get(Transaction, t1)
            check('a plain row does follow the rule (control)', untouched.custom_category_id == state['cat_a'])

        # --- category linked to a project ---
        r = client.post('/api/projects', json={'name': '%s Pocket' % tag})
        pocket = r.get_json()['project']
        state['project_ids'].append(pocket['id'])
        with app.app_context():
            cat_b_id = CustomCategory.query.filter_by(user_id=state['user_id'], name='%s CatB' % tag).first().id
        r = client.patch('/api/custom-categories/%d/project' % cat_b_id, json={'project_id': pocket['id']})
        check('link category → project', r.status_code == 200 and r.get_json()['category']['project_id'] == pocket['id'],
              r.get_data(as_text=True)[:200])
        r = client.patch('/api/custom-categories/%d/project' % cat_b_id, json={'project_id': 999999999})
        check('link to unknown project → 404', r.status_code == 404)
        listed = {p['id']: p for p in client.get('/api/projects').get_json()['projects']}
        check('linked-category row counts in the project (t5, -12.00)',
              listed[pocket['id']]['transaction_count'] == 1 and abs(listed[pocket['id']]['total'] - (-12.0)) < 1e-9,
              repr(listed[pocket['id']]))
        check('project lists its linked category', [c['id'] for c in listed[pocket['id']]['categories']] == [cat_b_id])
        check('hand-assigned rows stay in their own project', listed[project['id']]['transaction_count'] == 3 + 2,
              repr(listed[project['id']]['transaction_count']))
        r = client.get('/api/transactions?project_id=%d&page_size=500' % pocket['id'])
        got = r.get_json()['transactions']
        check('filter by the pocket returns the linked row', [t['id'] for t in got] == [t5], repr([t['id'] for t in got]))
        check('row says it is in the project via its category', got and got[0]['project_source'] == 'category')
        r = client.get('/api/transactions?project_id=none&search=%s&page_size=500' % tag)
        check('linked row is not under "No project"', t5 not in {t['id'] for t in r.get_json()['transactions']})
        r = client.patch('/api/transactions/bulk-project', json={'transaction_ids': [t5], 'project_id': project['id']})
        listed = {p['id']: p for p in client.get('/api/projects').get_json()['projects']}
        check('assigning by hand wins over the category link',
              listed[pocket['id']]['transaction_count'] == 0 and r.get_json()['transactions'][0]['project_source'] == 'manual')
        client.patch('/api/transactions/bulk-project', json={'transaction_ids': [t5], 'project_id': None})
        r = client.delete('/api/projects/%d' % pocket['id'])
        check('deleting the project unlinks the category', r.get_json().get('categories_unlinked') == 1, repr(r.get_json()))
        state['project_ids'].remove(pocket['id'])
        with app.app_context():
            check('category survives, unlinked', CustomCategory.query.get(cat_b_id).project_id is None)

        # --- rename + delete ---
        r = client.put('/api/projects/%d' % project['id'], json={'name': '%s Renamed' % tag})
        check('rename → 200', r.status_code == 200 and r.get_json()['project']['name'].endswith('Renamed'))
        r = client.delete('/api/projects/%d' % project['id'])
        body = r.get_json() or {}
        check('delete → 200 and unassigns rows', r.status_code == 200 and body.get('unassigned', 0) >= 4, repr(body))
        with app.app_context():
            alive = Transaction.query.filter(Transaction.id.in_([t1, t2, t3])).all()
            check('transactions survive the project delete', len(alive) == 3 and all(t.project_id is None for t in alive))
            check('project row gone', db.session.get(Project, project['id']) is None)
        state['project_ids'].remove(project['id'])
    finally:
        with app.app_context():
            txns = Transaction.query.filter_by(credential_id=state['cred_id']).all()
            txn_ids = [t.id for t in txns]
            if txn_ids:
                TransactionCategoryOverride.query.filter(
                    TransactionCategoryOverride.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
                Transaction.query.filter(Transaction.parent_transaction_id.in_(txn_ids)).delete(synchronize_session=False)
                Transaction.query.filter(Transaction.id.in_(txn_ids)).delete(synchronize_session=False)
            if state.get('rule_id'):
                CategoryRule.query.filter_by(id=state['rule_id']).delete()
            for cid in state['cat_ids']:
                CategoryRule.query.filter_by(category_id=cid).delete()
                CustomCategory.query.filter_by(id=cid).delete()
            for pid in state['project_ids']:
                Project.query.filter_by(id=pid).delete()
            Account.query.filter_by(id=state['acct_id']).delete()
            Credential.query.filter_by(id=state['cred_id']).delete()
            db.session.commit()
            left = (Transaction.query.filter(Transaction.name.like('%s%%' % tag)).count()
                    + CustomCategory.query.filter(CustomCategory.name.like('%s%%' % tag)).count()
                    + Project.query.filter(Project.name.like('%s%%' % tag)).count()
                    + Credential.query.filter_by(institution_name=tag).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return len(_FAILURES) == ok_before


if __name__ == '__main__':
    a = part_a()
    b = part_b()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if (a and b) else 1)
