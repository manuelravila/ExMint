#!/usr/bin/env python
"""test_transaction_description.py — your own transaction description, and user
edits surviving Plaid's pending -> posted replacement.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_transaction_description.py

Hard-aborts unless the configured database URI contains ``_dev_db``. With its own
throw-away user, credential, account, category and project it checks:

- PATCH /api/transactions/<id>/description (UI) and /api/v1/... : ``name`` shows
  the user's text, ``original_name`` keeps the bank's; null, blank or the bank's
  own text restore it; 255+ characters and non-text are refused; another user's
  transaction is 404;
- the list search finds both texts; sorting by name uses what the user sees;
- a category rule still matches the bank's text of a renamed transaction;
- the CSV export has Description (user's) and Bank Description (bank's);
- ``_persist_transactions_from_payload``: when Plaid removes a pending row and
  adds the posted one with ``pending_transaction_id``, the description, manual
  category and project move to the posted row (and never overwrite what the
  posted row already has).

Every row it created is deleted and the cleanup is asserted. No pytest is used;
exits non-zero on any failure.
"""

import csv
import datetime
import io
import sys
from decimal import Decimal
from uuid import uuid4

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
    from models import (Account, Budget, CategoryRule, Credential, CustomCategory, MonthlyBudget, Project,
                        Transaction, TransactionCategoryOverride, User, db)
    from core_views import _persist_transactions_from_payload, apply_category_rules

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])
    tag = 'EXMINT-LIVE-DESC-%s' % uuid4().hex[:8]
    ids = {}

    with app.app_context():
        user = User(email='%s@example.invalid' % tag.lower(), status='Active', role='User')
        user.set_password('live-test')
        other = User(email='%s-other@example.invalid' % tag.lower(), status='Active', role='User')
        other.set_password('live-test')
        db.session.add_all([user, other])
        db.session.flush()
        cred = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=tag,
                          access_token=None, soft_disconnected=True, requires_update=False)
        db.session.add(cred)
        db.session.flush()
        acct = Account(status='Active', credential_id=cred.id, plaid_account_id='acct-%s' % tag, name='Card',
                       type='credit', subtype='credit card', mask='0001', is_enabled=True)
        cat = CustomCategory(user_id=user.id, name='%s Gifts' % tag, color='#123456')
        project = Project(user_id=user.id, name='%s Trip' % tag)
        db.session.add_all([acct, cat, project])
        db.session.flush()

        def add(key, name, amount, plaid_id=None, pending=False, day='2026-03-01'):
            t = Transaction(plaid_transaction_id=plaid_id or 'plaid-%s' % uuid4().hex, user_id=user.id,
                            credential_id=cred.id, account_id=acct.id, name=name, amount=Decimal(amount),
                            date=datetime.date.fromisoformat(day), iso_currency_code='CAD', pending=pending)
            db.session.add(t)
            db.session.flush()
            ids[key] = t.id

        add('a', 'AMZN Mktp CA*5O65Z3OK0 TORONTO ON', '-123.46')
        add('b', 'ZZZ LAST BY BANK TEXT', '-5.00')
        state = {'user_id': user.id, 'other_id': other.id, 'cred_id': cred.id, 'cat_id': cat.id,
                 'project_id': project.id, 'acct_plaid': acct.plaid_account_id, 'acct_id': acct.id}
        pending_plaid = 'pending-%s' % uuid4().hex
        add('pending', 'UBER *PENDING', '-18.40', plaid_id=pending_plaid, pending=True, day='2026-03-05')
        pend = db.session.get(Transaction, ids['pending'])
        pend.custom_name = 'Ride to the airport'
        pend.projects = [project]
        db.session.add(TransactionCategoryOverride(transaction_id=pend.id, custom_category_id=cat.id))
        pending_plaid2 = 'pending-%s' % uuid4().hex
        add('pending2', 'CAFE *PENDING', '-4.00', plaid_id=pending_plaid2, pending=True, day='2026-03-06')
        db.session.get(Transaction, ids['pending2']).custom_name = 'Coffee with Ana'
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True
    base = '/api/transactions?account_ids=%d&page_size=500' % state['acct_id']

    def row(tid):
        return next((t for t in client.get(base).get_json()['transactions'] if t['id'] == tid), None)

    try:
        r = client.patch('/api/transactions/%d/description' % ids['a'], json={'description': '  Birthday   present for Ana '})
        t = (r.get_json() or {}).get('transaction') or {}
        check('UI: set → 200, name is the user text (spaces tidied)', r.status_code == 200 and t.get('name') == 'Birthday present for Ana', repr(t.get('name')))
        check('original_name keeps the bank text', t.get('original_name') == 'AMZN Mktp CA*5O65Z3OK0 TORONTO ON')
        check('list shows it too', (row(ids['a']) or {}).get('custom_name') == 'Birthday present for Ana')

        found = {t['id'] for t in client.get(base + '&search=Birthday').get_json()['transactions']}
        check('search finds the user text', ids['a'] in found, repr(found))
        found = {t['id'] for t in client.get(base + '&search=AMZN').get_json()['transactions']}
        check('search still finds the bank text', ids['a'] in found, repr(found))
        names = [t['name'] for t in client.get(base + '&sort_key=name&sort_desc=false').get_json()['transactions']]
        check('sorting by name uses what the user sees', names.index('Birthday present for Ana') < names.index('ZZZ LAST BY BANK TEXT'), repr(names))

        with app.app_context():
            db.session.add(CategoryRule(user_id=state['user_id'], text_to_match='AMZN Mktp', field_to_match='description',
                                        category_id=state['cat_id']))
            db.session.commit()
            apply_category_rules(state['user_id'])
            db.session.commit()
            renamed = db.session.get(Transaction, ids['a'])
            check('a rule still matches the bank text of a renamed row', renamed.custom_category_id == state['cat_id'],
                  repr(renamed.custom_category_id))

        body = client.get('/api/transactions/export?format=csv&account_ids=%d' % state['acct_id']).get_data(as_text=True)
        rows = list(csv.DictReader(io.StringIO(body)))
        exp = next((x for x in rows if x['Description'] == 'Birthday present for Ana'), None)
        check('export: Description = user text, Bank Description = bank text',
              exp is not None and exp.get('Bank Description') == 'AMZN Mktp CA*5O65Z3OK0 TORONTO ON', repr(exp))

        r = client.patch('/api/v1/transactions/%d/description' % ids['b'], json={'description': 'Parking'})
        check('API v1: set → 200', r.status_code == 200 and r.get_json()['transaction']['name'] == 'Parking')
        r = client.patch('/api/v1/transactions/%d/description' % ids['b'], json={'description': None})
        t = r.get_json()['transaction']
        check('null restores the bank text', t['name'] == 'ZZZ LAST BY BANK TEXT' and t['custom_name'] is None, repr(t))
        r = client.patch('/api/transactions/%d/description' % ids['b'], json={'description': 'ZZZ LAST BY BANK TEXT'})
        check("typing the bank's own text stores nothing", r.get_json()['transaction']['custom_name'] is None)
        r = client.patch('/api/transactions/%d/description' % ids['b'], json={'description': '   '})
        check('blank restores', r.status_code == 200 and r.get_json()['transaction']['custom_name'] is None)
        r = client.patch('/api/transactions/%d/description' % ids['b'], json={'description': 'x' * 256})
        check('256 characters → 400', r.status_code == 400, str(r.status_code))
        r = client.patch('/api/transactions/%d/description' % ids['b'], json={'description': 42})
        check('non-text → 400', r.status_code == 400, str(r.status_code))
        r = client.patch('/api/transactions/%d/description' % ids['b'], json={})
        check('missing field → 400', r.status_code == 400, str(r.status_code))
        other_client = app.test_client()
        with other_client.session_transaction() as sess:
            sess['_user_id'] = str(state['other_id'])
            sess['_fresh'] = True
        r = other_client.patch('/api/transactions/%d/description' % ids['a'], json={'description': 'hijack'})
        check("another user's transaction → 404", r.status_code == 404, str(r.status_code))

        # Plaid replaces the pending rows with posted ones.
        posted_plaid, posted_plaid2 = 'posted-%s' % uuid4().hex, 'posted-%s' % uuid4().hex
        with app.app_context():
            user = db.session.get(User, state['user_id'])
            cred = db.session.get(Credential, state['cred_id'])
            # The second posted row already exists with its own description: it must win.
            existing = Transaction(plaid_transaction_id=posted_plaid2, user_id=user.id, credential_id=cred.id,
                                   account_id=state['acct_id'], name='CAFE', amount=Decimal('-4.00'),
                                   date=datetime.date(2026, 3, 7), custom_name='Kept on the posted row')
            db.session.add(existing)
            db.session.commit()
            data = {
                'removed': [{'transaction_id': pending_plaid}, {'transaction_id': pending_plaid2}],
                'added': [{'transaction_id': posted_plaid, 'pending_transaction_id': pending_plaid,
                           'account_id': state['acct_plaid'], 'amount': 18.40, 'name': 'UBER CANADA TORONTO',
                           'date': '2026-03-07', 'pending': False}],
                'modified': [{'transaction_id': posted_plaid2, 'pending_transaction_id': pending_plaid2,
                              'account_id': state['acct_plaid'], 'amount': 4.00, 'name': 'CAFE',
                              'date': '2026-03-07', 'pending': False}],
            }
            counts = _persist_transactions_from_payload(user, cred, data)
            db.session.commit()
            posted = Transaction.query.filter_by(plaid_transaction_id=posted_plaid).one()
            pend = db.session.get(Transaction, ids['pending'])
            ov = TransactionCategoryOverride.query.filter_by(transaction_id=posted.id).first()
            check('sync counts: 1 added, 1 modified, 2 removed', counts == {'added': 1, 'modified': 1, 'removed': 2}, repr(counts))
            check('pending row is removed', pend.is_removed)
            check('description carried to the posted row', posted.custom_name == 'Ride to the airport', repr(posted.custom_name))
            check('manual category carried', ov is not None and ov.custom_category_id == state['cat_id'])
            check('project carried', [p.id for p in posted.projects] == [state['project_id']])
            check('posted amount uses the ExMint sign', posted.amount == Decimal('-18.40'), repr(posted.amount))
            kept = Transaction.query.filter_by(plaid_transaction_id=posted_plaid2).one()
            check("posted row's own description is not overwritten", kept.custom_name == 'Kept on the posted row', repr(kept.custom_name))
        r = row(posted.id)
        check('posted row shows the carried description in the list', r and r['name'] == 'Ride to the airport'
              and r['custom_category'] == '%s Gifts' % tag, repr(r and (r['name'], r['custom_category'])))
    finally:
        with app.app_context():
            uid = state['user_id']
            txn_ids = [t.id for t in Transaction.query.filter_by(user_id=uid)]
            if txn_ids:
                TransactionCategoryOverride.query.filter(TransactionCategoryOverride.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
            Transaction.query.filter_by(user_id=uid).delete(synchronize_session=False)
            CategoryRule.query.filter_by(user_id=uid).delete(synchronize_session=False)
            Project.query.filter_by(user_id=uid).delete(synchronize_session=False)
            CustomCategory.query.filter_by(user_id=uid).delete(synchronize_session=False)
            Account.query.filter_by(credential_id=state['cred_id']).delete(synchronize_session=False)
            Credential.query.filter_by(id=state['cred_id']).delete(synchronize_session=False)
            MonthlyBudget.query.filter_by(user_id=uid).delete(synchronize_session=False)
            Budget.query.filter_by(user_id=uid).delete(synchronize_session=False)
            User.query.filter(User.id.in_([uid, state['other_id']])).delete(synchronize_session=False)
            db.session.commit()
            left = Transaction.query.filter_by(user_id=uid).count() + User.query.filter_by(id=uid).count()
            check('cleanup removed every test row', left == 0, '%d left' % left)
    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)
