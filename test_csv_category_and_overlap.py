#!/usr/bin/env python
"""test_csv_category_and_overlap.py — CSV imports must not invent categories or
re-import a purchase the account already holds.

Run from the repository root:

    ./venv/bin/python test_csv_category_and_overlap.py
    EXMINT_LIVE_TEST=1 ./venv/bin/python test_csv_category_and_overlap.py

Part A always runs and needs no application or database (importing ``core_views``
only binds a Blueprint and imports models/config, the same approach as
``test_csv_import_routing.py``). It covers:

  * ``csv_import_routing.looks_like_account_type_header`` — which column headers
    describe the account rather than the transaction;
  * ``csv_import_routing.guard_category_mapping`` — an account-describing column
    can never feed the category field, whether auto-detected, user-picked or
    saved in an old template;
  * ``core_views._auto_detect_mapping`` on the header set that produced the
    2026-10-22 RBC damage ("Account Type Description" + "Account Type");
  * ``core_views._csv_resolve_category_text`` — a CSV category cell may only name
    a category the user already has; account labels and unknown words are refused
    so an import cannot mint a category;
  * ``csv_import_routing.match_duplicate_window`` — the count-aware, nearest-first
    pairing behind the ±3-day overlap question;
  * ``core_views._take_exact_stored_row`` — the rows the normal dedup already
    handles are consumed silently, which is what keeps a plain re-import from
    raising a question.

Part B is an opt-in live check against the DEV database (it hard-aborts unless the
configured URI contains ``_dev_db``) with its own throw-away user, so no real
account is touched. It exercises the real analyze and import endpoints for: the
RBC-shaped file creating 0 categories, the ±3-day overlap refusing the insert with
a 409 and listing the matched row, importing anyway after an explicit
confirmation, and a plain re-import staying a silent no-op.

No pytest is used (the venv does not have it); this is a plain-Python script that
exits non-zero on any failure.
"""

import json
import os
import sys
from datetime import date
from decimal import Decimal

try:
    from csv_import_routing import (
        looks_like_account_type_header, guard_category_mapping, match_duplicate_window,
    )
except ImportError:  # pragma: no cover - only true before the fix
    looks_like_account_type_header = guard_category_mapping = match_duplicate_window = None

try:
    from core_views import (
        _auto_detect_mapping, _csv_resolve_category_text, _take_exact_stored_row,
        _CSV_DUPLICATE_WINDOW_DAYS,
    )
except ImportError:  # pragma: no cover - only true before the fix
    _auto_detect_mapping = None
    _csv_resolve_category_text = None
    _take_exact_stored_row = None
    _CSV_DUPLICATE_WINDOW_DAYS = None


_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


# ── Part A: which headers describe the account ───────────────────────────────

def _test_account_type_headers():
    print('── looks_like_account_type_header ──')
    if looks_like_account_type_header is None:
        check('header guard exists', False, 'looks_like_account_type_header missing (pre-fix tree)')
        return

    account_columns = ['Account Type', 'account type', 'ACCOUNT TYPE', 'Account Type Description',
                       'Acct Type', 'Account Name', 'Product Name', 'Card Type',
                       'Institution Name', 'Account Category']
    for header in account_columns:
        check("'%s' is an account column" % header,
              looks_like_account_type_header(header), repr(header))

    row_columns = ['Type', 'Transaction Type', 'txn type', 'Classification', 'Category',
                   'Description', 'Account Number', 'Card Transaction Type',
                   'Transaction Description', 'Amount', 'Date', '', None]
    for header in row_columns:
        check("'%s' is not an account column" % header,
              not looks_like_account_type_header(header), repr(header))


# ── Part A: the mapping guard ────────────────────────────────────────────────

def _test_guard_category_mapping():
    print('── guard_category_mapping ──')
    if guard_category_mapping is None:
        check('mapping guard exists', False, 'guard_category_mapping missing (pre-fix tree)')
        return

    mapping = {'Date': 'date', 'Description': 'description', 'Account Type': 'category',
               'Amount': 'amount'}
    fixed, notes = guard_category_mapping(mapping)
    check('account column mapped to category is moved to account_type',
          fixed.get('Account Type') == 'account_type', repr(fixed))
    check('the change is explained to the user', len(notes) == 1 and 'Account Type' in notes[0],
          repr(notes))
    check('the input mapping is not mutated',
          mapping['Account Type'] == 'category', repr(mapping))

    # account_type already taken by a better-named column: the leftover column is
    # skipped rather than quietly becoming a category.
    both = {'Account Type Description': 'account_type', 'Account Type': 'category',
            'Date': 'date', 'Amount': 'amount'}
    fixed2, notes2 = guard_category_mapping(both)
    check('the second account column is unmapped, not turned into a category',
          fixed2.get('Account Type') is None, repr(fixed2))
    check('both columns are reported', len(notes2) == 1 and 'Royal' not in notes2[0],
          repr(notes2))

    legit = {'Date': 'date', 'Type': 'category', 'Category': 'category', 'Amount': 'amount'}
    fixed3, notes3 = guard_category_mapping(legit)
    check("a genuine 'Type' column keeps the category field",
          fixed3['Type'] == 'category' and fixed3['Category'] == 'category', repr(fixed3))
    check('a clean mapping produces no notes', notes3 == [], repr(notes3))

    fixed4, notes4 = guard_category_mapping({})
    check('an empty mapping is handled', fixed4 == {} and notes4 == [], repr(fixed4))


# ── Part A: auto-detect must not produce the 2026-10-22 damage ───────────────

def _test_auto_detect():
    print('── _auto_detect_mapping ──')
    if _auto_detect_mapping is None:
        check('auto-detect available', False, '_auto_detect_mapping missing')
        return

    # The RBC-style file that produced custom_category 'Chequing' /
    # 'Royal Credit Line': two account-describing columns, and the second one
    # used to fall through to the bare 'type' alias of the category field.
    headers = ['Account Type Description', 'Account Type', 'Date', 'Description',
               'Amount', 'Account Number']
    mapping = _auto_detect_mapping(headers)
    check('no account-describing column is auto-mapped to category',
          'category' not in mapping.values(), repr(mapping))
    check('the account columns land on account_type or are skipped',
          mapping['Account Type Description'] == 'account_type'
          and mapping['Account Type'] is None, repr(mapping))

    single = _auto_detect_mapping(['Date', 'Description', 'Account Type', 'Debit', 'Credit'])
    check('a single Account Type column stays account_type',
          single['Account Type'] == 'account_type'
          and 'category' not in single.values(), repr(single))

    typed = _auto_detect_mapping(['Date', 'Description', 'Type', 'Amount'])
    check('a file with a real Type column still gets a category column',
          typed['Type'] == 'category', repr(typed))


# ── Part A: what a category cell is allowed to become ────────────────────────

def _test_resolve_category_text():
    print('── _csv_resolve_category_text ──')
    if _csv_resolve_category_text is None:
        check('category resolver exists', False, '_csv_resolve_category_text missing (pre-fix tree)')
        return

    known = {'dining out': 'Dining Out', 'reimbursable': 'Reimbursable'}

    for text in ['Chequing', 'CHEQUING', 'Royal Credit Line', 'Savings', 'Credit Card',
                 'Visa', 'Investment', 'Mortgage']:
        label, reason = _csv_resolve_category_text(text, known)
        check("'%s' is refused as a category" % text,
              label is None and 'account type' in reason, repr((label, reason)))

    label, reason = _csv_resolve_category_text('dining out', known)
    check('a known category keeps the user\'s own spelling',
          label == 'Dining Out' and reason == '', repr((label, reason)))

    label, reason = _csv_resolve_category_text('Groceries UK', known)
    check('an unknown word is refused instead of becoming a new category',
          label is None and 'not one of your categories' in reason, repr((label, reason)))

    label, reason = _csv_resolve_category_text('', known)
    check('an empty cell is no category and nothing to report',
          label is None and reason == '', repr((label, reason)))

    label, reason = _csv_resolve_category_text(None, known)
    check('a missing cell is no category and nothing to report',
          label is None and reason == '', repr((label, reason)))

    label, reason = _csv_resolve_category_text('Chequing', None)
    check('an account label is refused even with no categories known',
          label is None and 'account type' in reason, repr((label, reason)))


# ── Part A: the ±3-day pairing behind the overlap question ───────────────────

def _test_match_duplicate_window():
    print('── match_duplicate_window ──')
    if match_duplicate_window is None:
        check('window pairing exists', False, 'match_duplicate_window missing (pre-fix tree)')
        return
    if _CSV_DUPLICATE_WINDOW_DAYS != 3:
        check('the overlap window is 3 days', False, repr(_CSV_DUPLICATE_WINDOW_DAYS))
    else:
        check('the overlap window is 3 days', True)

    # Posted vs transaction date, the BMO case: -153.68 on 2026-10-09 against a
    # stored row on 2026-10-07.
    pairs = match_duplicate_window([(0, date(2026, 10, 9))],
                                   [(7001, date(2026, 10, 7))], 3)
    check('a row 2 days from a stored row is paired',
          pairs == [(0, 7001, 2)], repr(pairs))

    pairs = match_duplicate_window([(0, date(2026, 10, 9))],
                                   [(7001, date(2026, 10, 4))], 3)
    check('a row 5 days from a stored row is not paired', pairs == [], repr(pairs))

    pairs = match_duplicate_window([(0, date(2026, 10, 9))],
                                   [(7001, date(2026, 10, 12))], 3)
    check('the window reaches both directions', pairs == [(0, 7001, 3)], repr(pairs))

    # Count-aware: two stored rows justify two flags, never three.
    pairs = match_duplicate_window([(0, date(2026, 10, 9)), (1, date(2026, 10, 9)),
                                    (2, date(2026, 10, 10))],
                                   [(7001, date(2026, 10, 8)), (7002, date(2026, 10, 9))], 3)
    check('two stored rows flag at most two file rows', len(pairs) == 2, repr(pairs))
    check('the unflagged occurrence is the later file row',
          [p[0] for p in pairs] == [0, 1], repr(pairs))

    # Nearest-first, so the row reported as the match is the closest one.
    pairs = match_duplicate_window([(0, date(2026, 10, 9))],
                                   [(7001, date(2026, 10, 6)), (7002, date(2026, 10, 8))], 3)
    check('the nearest stored row is the one paired',
          pairs == [(0, 7002, 1)], repr(pairs))

    pairs = match_duplicate_window([(2, date(2026, 10, 20)), (0, date(2026, 10, 1)),
                                    (1, date(2026, 10, 10))],
                                   [(7001, date(2026, 10, 1)), (7002, date(2026, 10, 10))], 3)
    check('results come back in file order', [p[0] for p in pairs] == [0, 1], repr(pairs))

    check('an empty file side pairs nothing',
          match_duplicate_window([], [(7001, date(2026, 10, 1))], 3) == [])
    check('an empty stored side pairs nothing',
          match_duplicate_window([(0, date(2026, 10, 1))], [], 3) == [])


# ── Part A: exact rows stay silent ───────────────────────────────────────────

class _Row(object):
    """Minimal stand-in for a stored Transaction."""

    def __init__(self, txn_id, day, amount, name, plaid_id='csv_x'):
        self.id = txn_id
        self.date = day
        self.amount = Decimal(amount)
        self.name = name
        self.plaid_transaction_id = plaid_id


def _test_take_exact_stored_row():
    print('── _take_exact_stored_row ──')
    if _take_exact_stored_row is None:
        check('exact-row consumption exists', False, '_take_exact_stored_row missing (pre-fix tree)')
        return

    free = [_Row(1, date(2026, 10, 9), '-153.68', 'ROYAL TAEKWONDO')]
    taken = _take_exact_stored_row(free, date(2026, 10, 9), Decimal('-153.68'), 'ROYAL TAEKWONDO')
    check('an identical stored row is consumed', taken is not None and taken.id == 1, repr(taken))
    check('the consumed row leaves the pool', free == [], repr(free))

    near = _take_exact_stored_row([_Row(2, date(2026, 10, 7), '-153.68', 'ROYAL TAEKWONDO')],
                                  date(2026, 10, 9), Decimal('-153.68'), 'ROYAL TAEKWONDO')
    check('a row only close in date is not consumed as exact', near is None, repr(near))

    synced = [_Row(3, date(2026, 10, 9), '-7.00', 'synced name', plaid_id='plaid_ABC')]
    taken = _take_exact_stored_row(synced, date(2026, 10, 9), Decimal('-7.00'), 'csv name')
    check('a Plaid row at the same date and amount is consumed for the K2 guard',
          taken is not None and taken.id == 3, repr(taken))

    csv_rows = [_Row(4, date(2026, 10, 9), '-7.00', 'other name', plaid_id='csv_DEF')]
    check('a row imported by CSV does not absorb a different CSV row',
          _take_exact_stored_row(csv_rows, date(2026, 10, 9), Decimal('-7.00'), 'csv name') is None,
          repr(csv_rows))


def part_a():
    print('=== Part A: pure mapping / category / overlap tests ===')
    _test_account_type_headers()
    _test_guard_category_mapping()
    _test_auto_detect()
    _test_resolve_category_text()
    _test_match_duplicate_window()
    _test_take_exact_stored_row()
    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


# ── Part B: live dev-database check ──────────────────────────────────────────

_TAG = 'EXMINT-LIVE-cat-dup'


def _rbc_csv():
    """The shape of the 2026-10-22 RBC upload: account-describing columns whose
    values are the bank's own account names, plus an E-TRF row from that file."""
    return (
        'Account Type Description,Account Type,Date,Description,Amount,Account Number\n'
        'Chequing,Chequing,2026-10-21,%s E-TRF REQFUL,-1000.48,5501\n'
        'Royal Credit Line,Royal Credit Line,2026-10-22,%s INTERAC ETRANSFER,-285.00,5501\n'
        % (_TAG, _TAG)
    )


_RBC_MAPPING = {'Account Type Description': 'account_type', 'Account Type': 'category',
                'Date': 'date', 'Description': 'description', 'Amount': 'amount',
                'Account Number': 'account_number'}


def part_b():
    print('=== Part B: live dev-database category / overlap check ===')

    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    try:
        from app import app
        from models import (
            db, User, Credential, Account, Transaction, AccountBalanceSnapshot,
            CustomCategory, MonthlyBudget, Budget, CsvImportTemplate,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not import the Flask app: %r' % (exc,))
        return False

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Part B: ABORT — refusing to run against non-dev database (%s)'
              % uri.split('@', 1)[-1])
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    from io import BytesIO
    from uuid import uuid4

    ok = True

    try:
        with app.app_context():
            user = User(email='%s-%s@example.invalid' % (_TAG.lower(), uuid4().hex),
                        status='Active', role='User')
            user.set_password('live-test')
            db.session.add(user)
            db.session.flush()
            user_id = user.id

            cred = Credential(item_id='live-test-%s' % uuid4().hex, status='Active',
                              user_id=user_id, institution_name='Live Test Bank')
            db.session.add(cred)
            db.session.flush()
            cred_id = cred.id

            # A chequing account, so the card sign heuristics stay out of the way.
            acct = Account(status='Active', credential_id=cred_id,
                           plaid_account_id='live_test_%s' % uuid4().hex,
                           name='Live Test Chequing', type='depository',
                           subtype='checking', mask='5501')
            db.session.add(acct)
            db.session.flush()
            acct_id = acct.id

            # The stored side of the BMO overlap: -153.68 posted on 2026-10-07.
            db.session.add(Transaction(
                plaid_transaction_id='live_synced_%s' % uuid4().hex,
                user_id=user_id, credential_id=cred_id, account_id=acct_id,
                name='ROYAL TAEKWONDO', amount=Decimal('-153.68'),
                date=date(2026, 10, 7), pending=False, is_removed=False,
                last_action='added',
            ))
            # A category the user really has, for the known-text case.
            known_cat = CustomCategory(user_id=user_id, name='Dining Out', color='#2C6B4F')
            db.session.add(known_cat)
            db.session.commit()
            cat_id = known_cat.id
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not create the isolated test user: %r' % (exc,))
        return False

    print('Part B: isolated user=%s account=%s category=%s' % (user_id, acct_id, cat_id))
    baseline_cats = _category_count(app, CustomCategory, user_id)

    def _login(client):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _post_core(client, csv_text, mapping, extra=None):
        data = {'file': (BytesIO(csv_text.encode('utf-8')), 'live.csv'),
                'mapping': json.dumps(mapping), 'save_template': 'false',
                'account_id': str(acct_id)}
        if extra:
            data.update(extra)
        return client.post('/api/transactions/import-csv/import',
                           data=data, content_type='multipart/form-data')

    def _analyze(client, csv_text):
        return client.post('/api/transactions/import-csv/analyze',
                           data={'file': (BytesIO(csv_text.encode('utf-8')), 'live.csv')},
                           content_type='multipart/form-data')

    def _json(resp):
        try:
            payload = resp.get_json()
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None

    def _rows(name_part):
        with app.app_context():
            return Transaction.query.filter(
                Transaction.user_id == user_id,
                Transaction.name.like('%%%s%%' % name_part)).all()

    def _categories():
        with app.app_context():
            return sorted(c.name for c in CustomCategory.query.filter_by(user_id=user_id).all())

    try:
        # ── 1: analyze reports the account column instead of offering it as a category
        with app.test_client() as client:
            _login(client)
            resp = _analyze(client, _rbc_csv())
        payload = _json(resp)
        print('Part B (analyze): HTTP=%s auto_mapping=%s notes=%s'
              % (resp.status_code,
                 payload.get('auto_mapping') if payload else None,
                 payload.get('mapping_notes') if payload else None))
        if resp.status_code != 200 or not payload:
            print('Part B (analyze): FAIL — expected HTTP 200 + JSON')
            ok = False
        else:
            check('analyze maps no account column to category',
                  'category' not in (payload.get('auto_mapping') or {}).values(),
                  repr(payload.get('auto_mapping')))
            check('analyze explains what it changed',
                  bool(payload.get('mapping_notes')), repr(payload.get('mapping_notes')))

        # ── 2: importing that file creates 0 categories and no account-type labels
        with app.test_client() as client:
            _login(client)
            resp = _post_core(client, _rbc_csv(), _RBC_MAPPING)
        payload = _json(resp)
        print('Part B (import rbc): HTTP=%s inserted=%s mapping_notes=%s category_check=%s'
              % (resp.status_code, payload.get('inserted') if payload else None,
                 payload.get('mapping_notes') if payload else None,
                 payload.get('category_check') if payload else None))
        if resp.status_code != 200 or not payload or payload.get('inserted') != 2:
            print('Part B (import rbc): FAIL — expected HTTP 200 and inserted == 2')
            ok = False
        else:
            check('re-importing the RBC file creates 0 new categories',
                  _categories() == ['Dining Out'], repr(_categories()))
            check('the account columns are reported, not silently used',
                  len(payload.get('mapping_notes') or []) == 1, repr(payload.get('mapping_notes')))
            rows = _rows(_TAG)
            check('the imported rows carry no category at all',
                  len(rows) == 2 and all(r.category is None and r.custom_category_id is None
                                         for r in rows),
                  repr([(r.name, r.category, r.custom_category_id) for r in rows]))
            check('no row is filed under an account label',
                  not any((r.category or '').lower() in ('chequing', 'royal credit line')
                          for r in rows),
                  repr([r.category for r in rows]))

        # ── 3: re-importing the same file is still a silent no-op, not a question
        with app.test_client() as client:
            _login(client)
            resp = _post_core(client, _rbc_csv(), _RBC_MAPPING)
        payload = _json(resp)
        print('Part B (re-import): HTTP=%s inserted=%s skipped=%s'
              % (resp.status_code, payload.get('inserted') if payload else None,
                 payload.get('skipped') if payload else None))
        if resp.status_code != 200 or not payload:
            print('Part B (re-import): FAIL — expected HTTP 200 (exact re-import must not '
                  'raise the duplicate question), got %s' % resp.status_code)
            ok = False
        elif payload.get('inserted') != 0 or payload.get('skipped') != 2:
            print('Part B (re-import): FAIL — expected inserted 0 / skipped 2, got %s'
                  % repr((payload.get('inserted'), payload.get('skipped'))))
            ok = False
        else:
            check('a plain re-import is skipped, not inserted', True)
        check('the category count never moved', _categories() == ['Dining Out'],
              repr(_categories()))

        # ── 4: the ±3-day overlap is flagged and NOT inserted
        overlap_csv = ('Date,Description,Amount\n'
                       '2026-10-09,ROYAL TAEKWONDO,-153.68\n')
        with app.test_client() as client:
            _login(client)
            resp = _post_core(client, overlap_csv,
                              {'Date': 'date', 'Description': 'description', 'Amount': 'amount'})
        payload = _json(resp)
        print('Part B (overlap): HTTP=%s body=%s' % (resp.status_code, payload))
        check('an overlap row is refused with 409', resp.status_code == 409, repr(resp.status_code))
        check('the refusal names the overlap',
              bool(payload and payload.get('duplicate_check')), repr(payload))
        check('nothing was inserted for an overlap',
              len([r for r in _rows('TAEKWONDO')]) == 1,
              repr([(r.id, r.date, r.amount) for r in _rows('TAEKWONDO')]))
        candidates = (payload or {}).get('duplicate_check', {}).get('candidates') or []
        if len(candidates) == 1:
            cand = candidates[0]
            check('the flag shows the stored row it matched',
                  cand.get('matched', {}).get('gap_days') == 2
                  and cand.get('matched', {}).get('date') == '2026-10-07'
                  and cand.get('amount') == '-153.68',
                  repr(cand))
        else:
            check('the flag lists exactly one candidate', False, repr(candidates))

        # ── 5: API v1 asks the same question (session auth, as require_api_auth
        # accepts it — the same approach test_balances_api_v1.py uses). Still
        # before any confirmation, so the stored row is unmatched and the overlap
        # is real on this path too.
        with app.test_client() as client:
            _login(client)
            resp = client.post('/api/v1/transactions/import-csv/import', json={
                'csv_content': overlap_csv,
                'mapping': {'Date': 'date', 'Description': 'description', 'Amount': 'amount'},
                'account_id': acct_id,
            })
        payload = _json(resp)
        print('Part B (api overlap): HTTP=%s duplicate_check=%s'
              % (resp.status_code, bool(payload and payload.get('duplicate_check'))))
        check('API v1 refuses an overlap with 409 too', resp.status_code == 409,
              repr(resp.status_code))
        check('API v1 listed the same overlap',
              bool(payload and payload.get('duplicate_check')), repr(payload))

        # ── 6: a confirmed import does insert it, and only once
        with app.test_client() as client:
            _login(client)
            resp = _post_core(client, overlap_csv,
                              {'Date': 'date', 'Description': 'description', 'Amount': 'amount'},
                              {'duplicate_confirmed': 'true'})
        payload = _json(resp)
        print('Part B (confirmed): HTTP=%s inserted=%s skipped=%s'
              % (resp.status_code, payload.get('inserted') if payload else None,
                 payload.get('skipped') if payload else None))
        if resp.status_code != 200 or not payload or payload.get('inserted') != 1:
            print('Part B (confirmed): FAIL — expected HTTP 200 and inserted == 1')
            ok = False
        check('the overlap is still filed Uncategorized',
              all(r.custom_category_id is None for r in _rows('TAEKWONDO')),
              repr([(r.id, r.category, r.custom_category_id) for r in _rows('TAEKWONDO')]))

        # ── 7: a known category name in the file is kept, an unknown one is refused
        cat_csv = ('Date,Description,Amount,Category\n'
                   '2026-10-25,%s known category,-12.00,dining out\n'
                   '2026-10-26,%s unknown category,-13.00,Royal Credit Line\n'
                   '2026-10-27,%s brand new word,-14.00,Waffle House\n' % (_TAG, _TAG, _TAG))
        cat_mapping = {'Date': 'date', 'Description': 'description', 'Amount': 'amount',
                       'Category': 'category'}
        with app.test_client() as client:
            _login(client)
            resp = _post_core(client, cat_csv, cat_mapping)
        payload = _json(resp)
        print('Part B (categories): HTTP=%s inserted=%s category_check=%s'
              % (resp.status_code, payload.get('inserted') if payload else None,
                 payload.get('category_check') if payload else None))
        if resp.status_code != 200 or not payload:
            print('Part B (categories): FAIL — expected HTTP 200, got %s' % resp.status_code)
            ok = False
        else:
            dropped = payload.get('category_check', {}).get('dropped') or []
            check('the known category was accepted, the two unknowns refused',
                  payload.get('inserted') == 3 and len(dropped) == 2,
                  repr((payload.get('inserted'), dropped)))
            with app.app_context():
                kept = Transaction.query.filter_by(user_id=user_id,
                                                   name='%s known category' % _TAG).first()
                refused = Transaction.query.filter_by(user_id=user_id,
                                                      name='%s unknown category' % _TAG).first()
            check('the accepted value is stored with the user\'s spelling',
                  kept is not None and kept.category == 'Dining Out',
                  repr(kept and kept.category))
            check('a value that reads as an account type is not stored',
                  refused is not None and refused.category is None,
                  repr(refused and refused.category))
            check('an unknown word still does not create a category',
                  _categories() == ['Dining Out'], repr(_categories()))

        check('the category count is untouched end to end',
              _category_count(app, CustomCategory, user_id) == baseline_cats,
              repr(_categories()))
    finally:
        # ── Mandatory cleanup: remove every row created for this test ───────
        try:
            with app.app_context():
                accts = Account.query.filter_by(credential_id=cred_id).all()
                for acct in accts:
                    AccountBalanceSnapshot.query.filter_by(account_id=acct.id) \
                        .delete(synchronize_session=False)
                Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
                CustomCategory.query.filter_by(user_id=user_id).delete(synchronize_session=False)
                Account.query.filter_by(credential_id=cred_id).delete(synchronize_session=False)
                Credential.query.filter_by(id=cred_id).delete(synchronize_session=False)
                MonthlyBudget.query.filter_by(user_id=user_id).delete(synchronize_session=False)
                Budget.query.filter_by(user_id=user_id).delete(synchronize_session=False)
                CsvImportTemplate.query.filter_by(user_id=user_id).delete(synchronize_session=False)
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
                db.session.commit()
                left_t = Transaction.query.filter_by(user_id=user_id).count()
                left_c = CustomCategory.query.filter_by(user_id=user_id).count()
                left_a = Account.query.filter_by(credential_id=cred_id).count()
                left_u = User.query.filter_by(id=user_id).count()
            print('Part B: cleanup transactions=%d categories=%d accounts=%d user=%d (all must be 0)'
                  % (left_t, left_c, left_a, left_u))
            if left_t or left_c or left_a or left_u:
                print('Part B: FAIL — cleanup left rows behind')
                ok = False
        except Exception as exc:  # pragma: no cover - environment dependent
            print('Part B: FAIL — cleanup error: %r' % (exc,))
            ok = False

    if ok:
        print('Part B: PASS (0 new categories, overlap flagged then confirmed, '
              'API parity, known/unknown category text)')
    return ok


def _category_count(app, CustomCategory, user_id):
    with app.app_context():
        return CustomCategory.query.filter_by(user_id=user_id).count()


def main():
    ok_a = part_a()
    print('')
    ok_b = part_b()
    total = len(_FAILURES)
    print('')
    # Part B also records through check(), so a FAIL there has to fail the run
    # even when Part B returned True: exit on every failed check, not on the
    # two part flags alone.
    if ok_a and ok_b and total == 0:
        print('RESULT: PASS')
        return 0
    print('RESULT: FAIL (%d failed check(s); part_a=%s part_b=%s)' % (total, ok_a, ok_b))
    return 1


if __name__ == '__main__':
    sys.exit(main())
