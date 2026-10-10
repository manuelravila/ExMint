#!/usr/bin/env python
"""test_csv_new_institution.py — header-less / tab files and CSV-only institutions.

Run from the repository root:

    ./venv/bin/python test_csv_new_institution.py                     # Part A only
    EXMINT_LIVE_TEST=1 ./venv/bin/python test_csv_new_institution.py  # Part A + Part B

Part A needs no database: delimiter detection, re-serialisation, header-less
detection and the synthesised header, end to end through
``_csv_content_without_preamble`` (a Home Depot export: BOM, TAB-separated, no
header), plus regressions (a normal comma file and a preamble file are
unchanged).

Part B is an opt-in live check against the DEV database (hard-aborts unless the
configured database URI contains ``_dev_db``). With its own throw-away user it
imports a Home Depot style file into a NEW institution through the UI route and
the API v1 route: the sign guard stops the "owe" file (payments would be money
out), ``invert`` imports it, the institution is CSV-only and the account is a
credit card, the balance is right, a duplicate institution name is refused and
a re-import into the created account inserts nothing. Everything it creates is
deleted in a ``finally`` block.

No pytest is used (the venv does not have it); exits non-zero on any failure.
"""

import csv
import io
import json
import os
import sys
from io import BytesIO
from uuid import uuid4

from csv_import_routing import detect_delimiter, first_row_is_data, synthesise_header, to_comma_separated
from core_views import _auto_detect_mapping, _csv_content_without_preamble

_PASSES = []
_FAILURES = []

HD_FILE = ('﻿12/19/2025\t$1479.94\tHOME DEPOT SCARBOROUGH ON\tpurchase\n'
           '12/31/2025\t$-522.06\tHOME DEPOT SCARBOROUGH ON\tcredit\n'
           '01/07/2026\t$1619.29\tHOMEDEPOT.CA 800-628-0525\tpurchase\n'
           '01/27/2026\t$-235.00\tPAYMENT - THANK YOU\tpayment\n'
           '02/25/2026\t$-235.00\tPAYMENT - THANK YOU\tpayment\n'
           '03/25/2026\t$-235.00\tPAYMENT - THANK YOU\tpayment\n'
           '08/03/2026\t$228.85\tINTEREST CHARGE\tinterest charged')


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


def part_a():
    print('=== Part A: delimiter + header-less detection ===')
    check('tab file → tab', detect_delimiter('a\tb\tc\n1\t2\t3\n') == '\t')
    check('semicolon file → ;', detect_delimiter('Date;Amount\n2026-01-01;5,00\n') == ';')
    check('comma wins a tie', detect_delimiter('a,b\tc\n') == ',')
    check('one-column text stays comma', detect_delimiter('hello\nworld\n') == ',')
    check('tabs re-serialised with commas (quoting a comma value)',
          to_comma_separated('a\tb,c\n', '\t') == 'a,"b,c"\n', repr(to_comma_separated('a\tb,c\n', '\t')))

    is_date = lambda v: v[:2].isdigit() and '/' in v
    is_amount = lambda v: any(c.isdigit() for c in v) and '/' not in v
    check('data first row detected', first_row_is_data('12/19/2025,$5.00,X\n', is_date, is_amount))
    check('header first row is not data', not first_row_is_data('Date,Amount,Description\n', is_date, is_amount))
    check('alias-looking data row ("credit") still data',
          first_row_is_data('12/31/2025,$-5.00,HOME DEPOT,credit\n', is_date, is_amount))
    out = synthesise_header('12/19/2025,$5.00,HOME DEPOT SCARBOROUGH ON,purchase\n', is_date, is_amount)
    check('synthesised header', out.splitlines()[0] == 'Date,Amount,Description,Type', out.splitlines()[0])

    content = _csv_content_without_preamble(HD_FILE.lstrip('﻿'))
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    mapping = _auto_detect_mapping(reader.fieldnames)
    check('Home Depot file: header synthesised', reader.fieldnames == ['Date', 'Amount', 'Description', 'Type'], repr(reader.fieldnames))
    check('Home Depot file: every row kept (none mistaken for a preamble)', len(rows) == 7, str(len(rows)))
    check('Home Depot file: auto-mapping finds date/amount/description',
          mapping.get('Date') == 'date' and mapping.get('Amount') == 'amount' and mapping.get('Description') == 'description', repr(mapping))
    normal = 'Date,Description,Amount\n2026-01-01,X,-5.00\n'
    check('normal comma file unchanged', _csv_content_without_preamble(normal) == normal)
    pre = 'Following data is valid as of 10/10/2026\n\nDate,Description,Amount\n2026-01-01,X,-5.00\n'
    check('preamble still dropped', _csv_content_without_preamble(pre).startswith('Date,Description,Amount'))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database check ===')
    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    from app import app
    from models import (Account, Budget, Credential, CsvImportTemplate, MonthlyBudget,
                        Transaction, User, db)

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])
    ok_before = len(_FAILURES)
    tag = 'EXMINT-LIVE-NEWINST-%s' % uuid4().hex[:8]

    with app.app_context():
        user = User(email='%s@example.invalid' % tag.lower(), status='Active', role='User')
        user.set_password('live-test')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
    mapping = {'Date': 'date', 'Amount': 'amount', 'Description': 'description'}
    new_fields = {'new_institution_name': '%s Home Depot' % tag, 'new_account_name': 'Home Depot Card',
                  'new_account_type': 'credit_card', 'new_account_mask': '8134'}

    def post_ui(**extra):
        data = {'file': (BytesIO(HD_FILE.encode('utf-8')), 'hd.csv'), 'mapping': json.dumps(mapping),
                'save_template': 'false'}
        data.update(extra)
        return client.post('/api/transactions/import-csv/import', data=data, content_type='multipart/form-data')

    try:
        r = client.post('/api/transactions/import-csv/analyze',
                        data={'file': (BytesIO(HD_FILE.encode('utf-8')), 'hd.csv')}, content_type='multipart/form-data')
        body = r.get_json() or {}
        check('analyze: header-less tab file → 4 named columns, 7 rows',
              r.status_code == 200 and body.get('headers') == ['Date', 'Amount', 'Description', 'Type'] and body.get('row_count') == 7,
              '%s %s' % (r.status_code, str(body)[:200]))

        r = post_ui(**new_fields)
        body = r.get_json() or {}
        reasons = (body.get('sign_check') or {}).get('reasons', [])
        check('owe-style card file into a new card → 409 (payments would be money out)',
              r.status_code == 409 and any('payments/refunds' in x for x in reasons), '%s %r' % (r.status_code, reasons))
        with app.app_context():
            check('nothing created on 409', Credential.query.filter_by(user_id=user_id).count() == 0)

        r = post_ui(amount_sign='invert', **new_fields)
        body = r.get_json() or {}
        check('invert → 200, 7 inserted', r.status_code == 200 and body.get('inserted') == 7, '%s %s' % (r.status_code, str(body)[:300]))
        created = (body.get('created_accounts') or [{}])[0]
        check('response reports the new institution', created.get('new_institution') is True and created.get('mask') == '8134', repr(created))
        with app.app_context():
            cred = Credential.query.filter_by(user_id=user_id).one()
            acct = Account.query.filter_by(credential_id=cred.id).one()
            total = sum(float(t.amount) for t in Transaction.query.filter_by(account_id=acct.id))
            pay = Transaction.query.filter_by(account_id=acct.id, name='PAYMENT - THANK YOU').first()
            check('institution is CSV-only (paused, no token)', cred.soft_disconnected and cred.access_token is None
                  and cred.institution_name == new_fields['new_institution_name'])
            check('account is a credit card ••8134', (acct.type, acct.subtype, acct.mask, acct.name)
                  == ('credit', 'credit card', '8134', 'Home Depot Card'), repr((acct.type, acct.subtype, acct.mask, acct.name)))
            check('signs follow ExMint (net owed -2101.02, payment positive)',
                  abs(total - (-2101.02)) < 1e-6 and pay is not None and float(pay.amount) == 235.0, '%r %r' % (total, pay and pay.amount))
            acct_id = acct.id

        r = post_ui(amount_sign='invert', **new_fields)
        check('same institution name again → 400', r.status_code == 400, '%s %s' % (r.status_code, r.get_data(as_text=True)[:200]))

        r = post_ui(amount_sign='invert', account_id=str(acct_id))
        body = r.get_json() or {}
        check('re-import into the created account inserts nothing', r.status_code == 200 and body.get('inserted') == 0
              and body.get('skipped') == 7, '%s %s' % (r.status_code, str(body)[:200]))

        r = client.post('/api/v1/transactions/import-csv/import', json={
            'csv_content': HD_FILE, 'mapping': mapping, 'amount_sign': 'invert',
            'new_institution_name': '%s Second Card' % tag, 'new_account_type': 'credit_card'})
        body = r.get_json() or {}
        check('API v1: new institution import → 200, 7 inserted', r.status_code == 200 and body.get('inserted') == 7,
              '%s %s' % (r.status_code, str(body)[:300]))
        r = client.post('/api/v1/transactions/import-csv/import', json={
            'csv_content': HD_FILE, 'mapping': mapping, 'new_institution_name': '%s Bad' % tag,
            'new_account_type': 'mortgage'})
        check('API v1: unknown account type → 400', r.status_code == 400, str(r.status_code))
    finally:
        with app.app_context():
            cred_ids = [c.id for c in Credential.query.filter_by(user_id=user_id)]
            Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            if cred_ids:
                Account.query.filter(Account.credential_id.in_(cred_ids)).delete(synchronize_session=False)
            Credential.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            MonthlyBudget.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            Budget.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            CsvImportTemplate.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()
            left = (Transaction.query.filter_by(user_id=user_id).count()
                    + Credential.query.filter_by(user_id=user_id).count()
                    + User.query.filter_by(id=user_id).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)
    return len(_FAILURES) == ok_before


if __name__ == '__main__':
    a = part_a()
    b = part_b()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if (a and b) else 1)
