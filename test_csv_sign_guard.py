#!/usr/bin/env python
"""test_csv_sign_guard.py — CSV import refuses a file whose signs look reversed.

Run from the repository root:

    ./venv/bin/python test_csv_sign_guard.py                     # Part A only
    EXMINT_LIVE_TEST=1 ./venv/bin/python test_csv_sign_guard.py  # Part A + Part B

Part A needs no database: ``core_views._csv_parse_row`` (debit/credit,
CAD/USD priority, signed amount, missing amount).

Part B is an opt-in live check against the DEV database (hard-aborts unless the
configured database URI contains ``_dev_db``). It creates its own throw-away
User, Credential, a credit-card and a chequing Account, and deletes every row
in a ``finally`` block. Through the real UI and API v1 import endpoints:

- a card file in the "owe" convention (purchases positive) that overlaps rows
  already synced from Plaid is refused with 409 + ``sign_check`` suggesting
  ``invert``, and nothing is written;
- the same file with ``invert`` imports (the Plaid rows absorb it as duplicates);
- ``sign_confirmed`` lets the user import as chosen anyway;
- a card file that is mostly money in (no overlap) is refused (majority rule);
- a chequing file with "BILL PMT" money out and a payroll deposit is NOT flagged.

No pytest is used (the venv does not have it); exits non-zero on any failure.
"""

import json
import os
import sys
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from core_views import _csv_parse_row

_PASSES = []
_FAILURES = []
_TAG = 'EXMINT-LIVE-SIGN'


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


def part_a():
    print('=== Part A: _csv_parse_row ===')
    m = {'Date': 'date', 'Desc': 'description', 'Amount': 'amount', 'Debit': 'debit', 'Credit': 'credit',
         'CAD$': 'amount_cad', 'USD$': 'amount_usd', 'Acct': 'account_number', 'Junk': 'ignore'}
    r = _csv_parse_row({'Date': '2026-03-01', 'Desc': 'X', 'Amount': '-12.50'}, m)
    check('signed amount kept as in the file', r['amount'] == Decimal('-12.50') and r['currency'] is None, repr(r))
    check('description becomes the name', r['name'] == 'X')
    r = _csv_parse_row({'Debit': '40.00', 'Amount': '99'}, m)
    check('debit column wins over amount, stored negative', r['amount'] == Decimal('-40.00'), repr(r['amount']))
    r = _csv_parse_row({'Credit': '(15.00)'}, m)
    check('credit column stored positive', r['amount'] == Decimal('15.00'), repr(r['amount']))
    r = _csv_parse_row({'Debit': '0', 'Credit': '7.25'}, m)
    check('zero debit with credit → credit', r['amount'] == Decimal('7.25'), repr(r['amount']))
    r = _csv_parse_row({'CAD$': '-3.00', 'USD$': '-2.00', 'Debit': '9'}, m)
    check('CAD column wins and sets currency', r['amount'] == Decimal('-3.00') and r['currency'] == 'CAD')
    r = _csv_parse_row({'USD$': '-2.00'}, m)
    check('USD column sets currency', r['amount'] == Decimal('-2.00') and r['currency'] == 'USD')
    r = _csv_parse_row({'Date': '2026-03-01', 'Acct': '1234', 'Junk': 'z'}, m)
    check('no amount → None', r['amount'] is None)
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database check ===')
    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    import datetime
    from app import app
    from models import (Account, Budget, Credential, CsvImportTemplate, MonthlyBudget,
                        Transaction, User, db)

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])
    ok_before = len(_FAILURES)
    state = {}

    with app.app_context():
        user = User(email='%s-%s@example.invalid' % (_TAG.lower(), uuid4().hex), status='Active', role='User')
        user.set_password('live-test')
        db.session.add(user)
        db.session.flush()
        state['user_id'] = user.id
        cred = Credential(user_id=user.id, item_id='item-%s-%s' % (_TAG, uuid4().hex[:8]),
                          institution_name=_TAG, access_token=None, soft_disconnected=True,
                          requires_update=False)
        db.session.add(cred)
        db.session.flush()
        state['cred_id'] = cred.id
        card = Account(status='Active', credential_id=cred.id, plaid_account_id='card-%s' % uuid4().hex[:8],
                       name='Sign Test Card', type='credit', subtype='credit card', mask='7001', is_enabled=True)
        card2 = Account(status='Active', credential_id=cred.id, plaid_account_id='card2-%s' % uuid4().hex[:8],
                        name='Sign Test Card 2', type='credit', subtype='credit card', mask='7002', is_enabled=True)
        cheq = Account(status='Active', credential_id=cred.id, plaid_account_id='cheq-%s' % uuid4().hex[:8],
                       name='Sign Test Chequing', type='depository', subtype='checking', mask='7003', is_enabled=True)
        db.session.add_all([card, card2, cheq])
        db.session.flush()
        state.update(card=card.id, card2=card2.id, cheq=cheq.id)
        # Rows already synced from Plaid (non-csv ids), ExMint convention.
        for day, amount, name in (('2026-03-02', '-50.00', 'GROCER'), ('2026-03-03', '-20.50', 'CAFE'),
                                  ('2026-03-04', '-12.00', 'BAKERY'), ('2026-03-05', '300.00', 'PAYMENT THANK YOU')):
            db.session.add(Transaction(plaid_transaction_id='plaid-%s' % uuid4().hex, user_id=user.id,
                                       credential_id=cred.id, account_id=card.id, name=name,
                                       amount=Decimal(amount), date=datetime.date.fromisoformat(day),
                                       iso_currency_code='CAD', pending=False))
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    mapping = {'Date': 'date', 'Description': 'description', 'Amount': 'amount'}

    def post_ui(account_id, csv_text, **extra):
        data = {'file': (BytesIO(csv_text.encode('utf-8')), 'sign.csv'), 'mapping': json.dumps(mapping),
                'save_template': 'false', 'account_id': str(account_id)}
        data.update(extra)
        return client.post('/api/transactions/import-csv/import', data=data, content_type='multipart/form-data')

    def post_api(account_id, csv_text, **extra):
        body = {'csv_content': csv_text, 'mapping': mapping, 'account_id': account_id}
        body.update(extra)
        return client.post('/api/v1/transactions/import-csv/import', json=body)

    def count(account_id):
        with app.app_context():
            return Transaction.query.filter_by(account_id=account_id, is_removed=False).count()

    owe_file = ('Date,Description,Amount\n2026-03-02,GROCER,50.00\n2026-03-03,CAFE,20.50\n'
                '2026-03-04,BAKERY,12.00\n2026-03-05,PAYMENT THANK YOU,-300.00\n')
    try:
        r = post_ui(state['card'], owe_file)
        body = r.get_json() or {}
        check('UI: reversed card file → 409', r.status_code == 409, '%s %s' % (r.status_code, str(body)[:200]))
        sc = body.get('sign_check') or {}
        check('sign_check suggests invert', sc.get('suggested_amount_sign') == 'invert' and sc.get('amount_sign') == 'as_is', repr(sc))
        check('reason names the opposite-sign overlap', any('opposite sign' in x for x in sc.get('reasons', [])), repr(sc.get('reasons')))
        check('nothing written on 409', count(state['card']) == 4, str(count(state['card'])))

        r = post_api(state['card'], owe_file)
        check('API v1: same file → 409 with sign_check', r.status_code == 409 and 'sign_check' in (r.get_json() or {}), str(r.status_code))

        r = post_ui(state['card'], owe_file, amount_sign='invert')
        body = r.get_json() or {}
        check('UI: inverted → 200, Plaid rows absorb it', r.status_code == 200 and body.get('inserted') == 0 and body.get('skipped') == 4,
              '%s %s' % (r.status_code, str(body)[:200]))

        r = post_ui(state['card'], owe_file, sign_confirmed='true')
        body = r.get_json() or {}
        check('UI: sign_confirmed imports as chosen', r.status_code == 200 and body.get('inserted') == 4,
              '%s %s' % (r.status_code, str(body)[:200]))

        majority = 'Date,Description,Amount\n' + ''.join(
            '2026-04-%02d,SHOP %d,%d.00\n' % (d, d, 10 + d) for d in range(1, 12))
        r = post_api(state['card2'], majority)
        body = r.get_json() or {}
        reasons = (body.get('sign_check') or {}).get('reasons', [])
        check('API v1: card file mostly money in → 409 (majority rule)',
              r.status_code == 409 and any('money in' in x for x in reasons), '%s %r' % (r.status_code, reasons))
        check('nothing written to card 2', count(state['card2']) == 0)

        cheq_file = ('Date,Description,Amount\n2026-03-10,WWW BILL PMT TIN0-1,-235.00\n'
                     '2026-03-11,PAYROLL DEPOSIT,3000.00\n2026-03-12,ONLINE BANKING PAYMENT AMEX,-500.00\n')
        r = post_ui(state['cheq'], cheq_file)
        body = r.get_json() or {}
        check('chequing bill payments + payroll are not flagged', r.status_code == 200 and body.get('inserted') == 3,
              '%s %s' % (r.status_code, str(body)[:200]))
    finally:
        with app.app_context():
            Transaction.query.filter_by(user_id=state['user_id']).delete(synchronize_session=False)
            Account.query.filter_by(credential_id=state['cred_id']).delete(synchronize_session=False)
            Credential.query.filter_by(id=state['cred_id']).delete(synchronize_session=False)
            MonthlyBudget.query.filter_by(user_id=state['user_id']).delete(synchronize_session=False)
            Budget.query.filter_by(user_id=state['user_id']).delete(synchronize_session=False)
            CsvImportTemplate.query.filter_by(user_id=state['user_id']).delete(synchronize_session=False)
            User.query.filter_by(id=state['user_id']).delete(synchronize_session=False)
            db.session.commit()
            left = (Transaction.query.filter_by(user_id=state['user_id']).count()
                    + Account.query.filter_by(credential_id=state['cred_id']).count()
                    + User.query.filter_by(id=state['user_id']).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)
    return len(_FAILURES) == ok_before


if __name__ == '__main__':
    a = part_a()
    b = part_b()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if (a and b) else 1)
