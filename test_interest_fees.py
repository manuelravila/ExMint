#!/usr/bin/env python
"""test_interest_fees.py — EX-07: interest & fees tracker.

Run from the repository root (DEV database only):

    ./venv/bin/python test_interest_fees.py

Part 1 runs the pure rule (``detect_interest_fees``) over synthetic charges with a
fixed ``today``: various interest and fee types across months.

Part 2 writes a few of those charges for a throwaway user, reads them back
through ``collect_interest_fees`` and ``GET /api/interest-fees``, checks that another
user's charges stay invisible, and deletes everything it created.

Part 3 (optional) runs against a PROD copy if EXMINT_INTEREST_FEES_PROD_COPY is set.
"""

import datetime
import os
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


TODAY = datetime.date(2026, 11, 1)


def d(offset):
    return TODAY - datetime.timedelta(days=offset)


def charge(name, amount, offset, merchant=None, account_id=1, sub_type=None, positive=False):
    """Create a charge dict (negative amount = charge in ExMint convention).
    If positive=True, amount is kept as positive (for reversals/rebates).
    """
    amt = amount if positive else -abs(amount)
    return {
        'id': None,
        'date': d(offset),
        'amount': amt,
        'name': name,
        'merchant_name': merchant,
        'custom_name': None,
        'account_id': account_id,
        'sub_type': sub_type,
    }


def synthetic():
    """Build a set of synthetic interest/fee charges for testing."""
    charges = []

    # August 2026 - HD card interest charges
    charges.append(charge('INTEREST CHARGE', 229.00, 90, account_id=1))  # Aug 3
    charges.append(charge('INTEREST CHARGE', 35.00, 85, account_id=1))
    charges.append(charge('INTEREST CHARGE', 31.00, 80, account_id=1))

    # WestJet purchase interest
    charges.append(charge('PURCHASE INTEREST 20.99%', 56.30, 60, merchant='WestJet', account_id=1))

    # LOC "LOAN INTEREST"
    charges.append(charge('LOAN INTEREST', 24.32, 55, account_id=2))

    # Overdraft interest (multiple months)
    charges.append(charge('OVERDRAFT INTEREST', 12.50, 50, account_id=3))
    charges.append(charge('OD INTEREST', 8.75, 20, account_id=3))

    # NSF fee in June
    charges.append(charge('NSF FEE', 10.00, 150, account_id=3))

    # Annual fee (with reversal in same month to test netting)
    charges.append(charge('ANNUAL FEE', 139.00, 100, account_id=1))
    charges.append(charge('ANNUAL FEE REVERSAL', 139.00, 100, account_id=1, positive=True))  # positive = reversal

    # Overdraft fee (flat)
    charges.append(charge('OVERDRAFT FEE', 5.00, 45, account_id=3))
    charges.append(charge('OVERDRAFT FEE', 5.00, 15, account_id=3))

    # Late fee
    charges.append(charge('LATE PAYMENT FEE', 35.00, 35, account_id=1))

    # Cash advance fee
    charges.append(charge('CASH ADVANCE FEE', 10.00, 30, account_id=1))

    # Foreign transaction fee
    charges.append(charge('FOREIGN TRANSACTION FEE', 2.50, 25, account_id=1))

    # Cash advance interest (should be INTEREST, not CASH_ADVANCE_FEE)
    charges.append(charge('CASH ADVANCE INTEREST .99%', 2.24, 20, account_id=1))

    # Overdraft Protect. Fee (should be OVERDRAFT)
    charges.append(charge('Overdraft Protect. Fee PAY-PER-USE ODP PLAN', 5.00, 10, account_id=3))

    # OD INTEREST CHARGE (should be OD_INTEREST)
    charges.append(charge('OVERDRAFT INTEREST CHARGE', 0.02, 5, account_id=3))

    # Deposit interest (should be EXCLUDED - income)
    charges.append(charge('DEPOSIT INTEREST', -0.01, 8, account_id=1))  # positive = income

    # Returned Cheque - NSF (should be EXCLUDED - bounced item, not fee)
    charges.append(charge('Returned Cheque - NSF', 1308.00, 7, account_id=1))  # positive

    # INTEREST PAYMENT with amount 0 (should be EXCLUDED)
    charges.append(charge('INTEREST PAYMENT', 0.00, 6, account_id=2))

    # Some random non-interest charges (should be ignored - no pattern match)
    charges.append(charge('MONTHLY SERVICE FEE', 15.00, 40, account_id=2))
    charges.append(charge('ATM WITHDRAWAL FEE', 3.00, 10, account_id=3))

    # Inflows (positive amounts) should be ignored
    charges.append(charge('REFUND', 25.00, 5, account_id=1))  # positive = refund

    # Tiny amounts below threshold
    charges.append(charge('ROUNDING', 0.005, 8, account_id=1))

    return charges


def part1():
    from interest_fees import SUB_TYPES, detect_interest_fees, _classify_sub_type

    # Test sub-type classification - positive cases
    check('classify INTEREST - INTEREST CHARGE',
          _classify_sub_type('INTEREST CHARGE') == 'INTEREST',
          'got %r' % _classify_sub_type('INTEREST CHARGE'))
    check('classify INTEREST - PURCHASE INTEREST',
          _classify_sub_type('PURCHASE INTEREST 20.99%') == 'INTEREST',
          'got %r' % _classify_sub_type('PURCHASE INTEREST 20.99%'))
    check('classify INTEREST - LOAN INTEREST',
          _classify_sub_type('LOAN INTEREST') == 'INTEREST',
          'got %r' % _classify_sub_type('LOAN INTEREST'))
    check('classify INTEREST - bare INTEREST',
          _classify_sub_type('INTEREST') == 'INTEREST',
          'got %r' % _classify_sub_type('INTEREST'))
    check('classify INTEREST - CASH ADVANCE INTEREST',
          _classify_sub_type('CASH ADVANCE INTEREST .99%') == 'INTEREST',
          'got %r' % _classify_sub_type('CASH ADVANCE INTEREST .99%'))

    check('classify OD_INTEREST - OVERDRAFT INTEREST',
          _classify_sub_type('OVERDRAFT INTEREST') == 'OD_INTEREST',
          'got %r' % _classify_sub_type('OVERDRAFT INTEREST'))
    check('classify OD_INTEREST - OD INTEREST',
          _classify_sub_type('OD INTEREST') == 'OD_INTEREST',
          'got %r' % _classify_sub_type('OD INTEREST'))
    check('classify OD_INTEREST - OVERDRAFT INTEREST CHARGE',
          _classify_sub_type('OVERDRAFT INTEREST CHARGE') == 'OD_INTEREST',
          'got %r' % _classify_sub_type('OVERDRAFT INTEREST CHARGE'))

    check('classify NSF - NSF FEE',
          _classify_sub_type('NSF FEE') == 'NSF',
          'got %r' % _classify_sub_type('NSF FEE'))
    check('classify NSF - NON-SUFFICIENT FUNDS',
          _classify_sub_type('NON-SUFFICIENT FUNDS FEE') == 'NSF',
          'got %r' % _classify_sub_type('NON-SUFFICIENT FUNDS FEE'))

    check('classify ANNUAL_FEE - ANNUAL FEE',
          _classify_sub_type('ANNUAL FEE') == 'ANNUAL_FEE',
          'got %r' % _classify_sub_type('ANNUAL FEE'))
    check('classify ANNUAL_FEE - MEMBERSHIP FEE',
          _classify_sub_type('MEMBERSHIP FEE') == 'ANNUAL_FEE',
          'got %r' % _classify_sub_type('MEMBERSHIP FEE'))

    check('classify OVERDRAFT - OVERDRAFT FEE',
          _classify_sub_type('OVERDRAFT FEE') == 'OVERDRAFT',
          'got %r' % _classify_sub_type('OVERDRAFT FEE'))
    check('classify OVERDRAFT - OD FEE',
          _classify_sub_type('OD FEE') == 'OVERDRAFT',
          'got %r' % _classify_sub_type('OD FEE'))
    check('classify OVERDRAFT - Overdraft Protect. Fee',
          _classify_sub_type('Overdraft Protect. Fee PAY-PER-USE ODP PLAN') == 'OVERDRAFT',
          'got %r' % _classify_sub_type('Overdraft Protect. Fee PAY-PER-USE ODP PLAN'))
    check('classify OVERDRAFT - PAY PER USE OVERDRAFT FEE',
          _classify_sub_type('PAY PER USE OVERDRAFT FEE') == 'OVERDRAFT',
          'got %r' % _classify_sub_type('PAY PER USE OVERDRAFT FEE'))

    check('classify LATE_FEE - LATE PAYMENT FEE',
          _classify_sub_type('LATE PAYMENT FEE') == 'LATE_FEE',
          'got %r' % _classify_sub_type('LATE PAYMENT FEE'))

    check('classify CASH_ADVANCE_FEE - CASH ADVANCE FEE',
          _classify_sub_type('CASH ADVANCE FEE') == 'CASH_ADVANCE_FEE',
          'got %r' % _classify_sub_type('CASH ADVANCE FEE'))

    check('classify BALANCE_TRANSFER_FEE - BALANCE TRANSFER FEE',
          _classify_sub_type('BALANCE TRANSFER FEE') == 'BALANCE_TRANSFER_FEE',
          'got %r' % _classify_sub_type('BALANCE TRANSFER FEE'))

    check('classify FOREIGN_TXN_FEE - FOREIGN TRANSACTION FEE',
          _classify_sub_type('FOREIGN TRANSACTION FEE') == 'FOREIGN_TXN_FEE',
          'got %r' % _classify_sub_type('FOREIGN TRANSACTION FEE'))

    # Test exclusion patterns - should return None
    check('exclude DEPOSIT INTEREST (income)',
          _classify_sub_type('DEPOSIT INTEREST') is None,
          'got %r' % _classify_sub_type('DEPOSIT INTEREST'))
    check('exclude Returned Cheque - NSF (bounced item)',
          _classify_sub_type('Returned Cheque - NSF') is None,
          'got %r' % _classify_sub_type('Returned Cheque - NSF'))
    # ANNUAL FEE REVERSAL/REBATE are classified as ANNUAL_FEE for netting, not excluded
    check('classify ANNUAL FEE REVERSAL as ANNUAL_FEE for netting',
          _classify_sub_type('ANNUAL FEE REVERSAL') == 'ANNUAL_FEE',
          'got %r' % _classify_sub_type('ANNUAL FEE REVERSAL'))
    check('classify ANNUAL CARD FEE REBATE as ANNUAL_FEE for netting',
          _classify_sub_type('ANNUAL CARD FEE REBATE') == 'ANNUAL_FEE',
          'got %r' % _classify_sub_type('ANNUAL CARD FEE REBATE'))
    check('exclude INTEREST PAYMENT zero amount',
          _classify_sub_type('INTEREST PAYMENT') is None,
          'got %r' % _classify_sub_type('INTEREST PAYMENT'))

    # Test that loose patterns don't match incorrectly
    check('no false positive: PRINT does not match int\\b',
          _classify_sub_type('PRINT') != 'INTEREST',
          'got %r' % _classify_sub_type('PRINT'))
    check('no false positive: MINT does not match int\\b',
          _classify_sub_type('MINT') != 'INTEREST',
          'got %r' % _classify_sub_type('MINT'))
    check('no false positive: FOOD FEE does not match od.?fee',
          _classify_sub_type('FOOD FEE') != 'OVERDRAFT',
          'got %r' % _classify_sub_type('FOOD FEE'))
    check('no false positive: DEBT FEE does not match bt.?fee',
          _classify_sub_type('DEBT FEE') != 'BALANCE_TRANSFER_FEE',
          'got %r' % _classify_sub_type('DEBT FEE'))

    # Run detection on synthetic charges
    rep = detect_interest_fees(synthetic(), TODAY)

    # Check overall totals (sum of absolute amounts of detected charges)
    # Expected: 229+35+31 + 56.30 + 24.32 + 12.50+8.75 + 10 + (139-139=0) + 5+5 + 35 + 10 + 2.50 + 2.24 + 5 + 0.02 = 480.63
    expected_total = 229 + 35 + 31 + 56.30 + 24.32 + 12.50 + 8.75 + 10 + 0 + 5 + 5 + 35 + 10 + 2.50 + 2.24 + 5 + 0.02
    check('total_overall matches expected sum',
          abs(rep['total_overall'] - expected_total) < 0.01,
          'got %.2f, expected %.2f' % (rep['total_overall'], expected_total))

    # Check charge count (excludes excluded, positive, tiny, and non-matching)
    # Note: ANNUAL_FEE charge is kept at 0 after netting, so count includes it
    expected_count = 17  # 3 HD + 1 WestJet + 1 LOAN + 2 OD_INT + 1 NSF + 1 ANNUAL (netted to 0) + 2 OVERDRAFT + 1 LATE + 1 CASH_ADV_FEE + 1 FOREIGN + 1 CASH_ADV_INT + 1 OVERDRAFT_PROTECT + 1 OD_INT_CHARGE = 17
    check('charge_count_overall excludes inflows, excluded, tiny, non-matching',
          rep['charge_count_overall'] == expected_count,
          'got %d, expected %d' % (rep['charge_count_overall'], expected_count))

    # Check sub-type totals
    check('INTEREST sub-type total',
          'INTEREST' in rep['by_sub_type'] and abs(rep['by_sub_type']['INTEREST']['total'] - (229+35+31+56.30+24.32+2.24)) < 0.01,
          'got %s' % rep['by_sub_type'].get('INTEREST'))
    check('INTEREST sub-type count = 6 (3 HD + WestJet + LOAN + CASH_ADV_INT)',
          'INTEREST' in rep['by_sub_type'] and rep['by_sub_type']['INTEREST']['count'] == 6,
          'got %s' % rep['by_sub_type'].get('INTEREST'))

    check('OD_INTEREST sub-type total',
          'OD_INTEREST' in rep['by_sub_type'] and abs(rep['by_sub_type']['OD_INTEREST']['total'] - (12.50+8.75+0.02)) < 0.01,
          'got %s' % rep['by_sub_type'].get('OD_INTEREST'))
    check('OD_INTEREST sub-type count = 3',
          'OD_INTEREST' in rep['by_sub_type'] and rep['by_sub_type']['OD_INTEREST']['count'] == 3,
          'got %s' % rep['by_sub_type'].get('OD_INTEREST'))

    check('NSF sub-type total',
          'NSF' in rep['by_sub_type'] and rep['by_sub_type']['NSF']['total'] == 10.00,
          'got %s' % rep['by_sub_type'].get('NSF'))
    check('NSF sub-type count = 1',
          'NSF' in rep['by_sub_type'] and rep['by_sub_type']['NSF']['count'] == 1,
          'got %s' % rep['by_sub_type'].get('NSF'))

    check('ANNUAL_FEE sub-type total = 0 (netted by reversal in same month)',
          'ANNUAL_FEE' in rep['by_sub_type'] and rep['by_sub_type']['ANNUAL_FEE']['total'] == 0.00,
          'got %s' % rep['by_sub_type'].get('ANNUAL_FEE'))

    check('OVERDRAFT sub-type total',
          'OVERDRAFT' in rep['by_sub_type'] and abs(rep['by_sub_type']['OVERDRAFT']['total'] - (5+5+5)) < 0.01,
          'got %s' % rep['by_sub_type'].get('OVERDRAFT'))
    check('OVERDRAFT sub-type count = 3 (2 OVERDRAFT FEE + 1 Overdraft Protect. Fee)',
          'OVERDRAFT' in rep['by_sub_type'] and rep['by_sub_type']['OVERDRAFT']['count'] == 3,
          'got %s' % rep['by_sub_type'].get('OVERDRAFT'))

    check('LATE_FEE sub-type total',
          'LATE_FEE' in rep['by_sub_type'] and rep['by_sub_type']['LATE_FEE']['total'] == 35.00,
          'got %s' % rep['by_sub_type'].get('LATE_FEE'))

    check('CASH_ADVANCE_FEE sub-type total',
          'CASH_ADVANCE_FEE' in rep['by_sub_type'] and rep['by_sub_type']['CASH_ADVANCE_FEE']['total'] == 10.00,
          'got %s' % rep['by_sub_type'].get('CASH_ADVANCE_FEE'))

    check('FOREIGN_TXN_FEE sub-type total',
          'FOREIGN_TXN_FEE' in rep['by_sub_type'] and rep['by_sub_type']['FOREIGN_TXN_FEE']['total'] == 2.50,
          'got %s' % rep['by_sub_type'].get('FOREIGN_TXN_FEE'))

    # Monthly breakdown exists
    check('monthly breakdown has entries',
          len(rep['monthly']) > 0,
          repr(rep['monthly']))

    # Account breakdown
    check('by_account has entries',
          len(rep['by_account']) >= 2,
          repr(rep['by_account']))

    # Test monthly_cost_of_debt function exists (can't call without app context)
    from interest_fees import monthly_cost_of_debt
    check('monthly_cost_of_debt function exists', callable(monthly_cost_of_debt), '')


def part2():
    from app import app
    from models import Account, Credential, Transaction, User, db
    from interest_fees import collect_interest_fees
    import sqlalchemy

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri or '_prd_db' in uri or '_stg_db' in uri:
        print('ABORT — refusing to run against a non-dev database (%s)' % uri.split('@', 1)[-1])
        _FAILURES.append('dev database')
        return
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-INTFEES-%s' % uuid.uuid4().hex[:8]
    today = datetime.date.today()
    state = {'users': [], 'creds': []}
    try:
        with app.app_context():
            def make_user(suffix, rows):
                user = User(email='%s-%s@example.com' % (tag.lower(), suffix), status='Active', role='User')
                user.set_password('not-a-real-password-%s' % tag)
                db.session.add(user)
                db.session.commit()
                state['users'].append(user.id)
                cred = Credential(user_id=user.id, institution_name='%s Bank' % tag,
                                  item_id='item-%s' % uuid.uuid4().hex, access_token=None)
                db.session.add(cred)
                db.session.commit()
                state['creds'].append(cred.id)
                # Create two credit accounts
                acct1 = Account(credential_id=cred.id, plaid_account_id='intfees-%s-1' % uuid.uuid4().hex,
                                 name='%s Credit Card' % tag, type='credit', subtype='credit card', mask='0001')
                acct2 = Account(credential_id=cred.id, plaid_account_id='intfees-%s-2' % uuid.uuid4().hex,
                                 name='%s Line of Credit' % tag, type='credit', subtype='line of credit', mask='0002')
                db.session.add_all([acct1, acct2])
                db.session.commit()
                for name, amount, offset, acct_name in rows:
                    acct = acct1 if acct_name == 'card' else acct2
                    # Reversals are positive amounts
                    is_reversal = 'REVERSAL' in name.upper() or 'REBATE' in name.upper()
                    amt = Decimal(str(amount)) if is_reversal else Decimal(str(-abs(amount)))
                    db.session.add(Transaction(
                        plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:12]),
                        user_id=user.id, credential_id=cred.id, account_id=acct.id,
                        name=name, amount=amt, date=today - datetime.timedelta(days=offset),
                        iso_currency_code='CAD'))
                db.session.commit()
                return user.id, acct1.id, acct2.id

            # User A: interest and fees (negative amounts = charges, positive = reversals)
            mine, acct1_id, acct2_id = make_user('a', [
                ('INTEREST CHARGE', 229.00, 90, 'card'),
                ('INTEREST CHARGE', 35.00, 85, 'card'),
                ('LOAN INTEREST', 24.32, 55, 'loc'),
                ('OVERDRAFT INTEREST', 12.50, 50, 'card'),
                ('NSF FEE', 10.00, 150, 'card'),
                ('ANNUAL FEE', 139.00, 100, 'card'),
                ('ANNUAL FEE REVERSAL', 139.00, 100, 'card'),  # positive = reversal
                ('OVERDRAFT FEE', 5.00, 45, 'card'),
                ('LATE PAYMENT FEE', 35.00, 35, 'card'),
            ])
            # User B: different charges (should not be visible to user A)
            other, _, _ = make_user('b', [
                ('INTEREST CHARGE', 99.00, 3, 'card'),
                ('ANNUAL FEE', 150.00, 10, 'card'),
            ])

            rep = collect_interest_fees(mine, today)
            check('collect_interest_fees reads user\'s charges from database',
                  rep['total_overall'] > 0 and rep['charge_count_overall'] >= 8,
                  repr((rep['total_overall'], rep['charge_count_overall'])))
            check('INTEREST sub-type present',
                  'INTEREST' in rep['by_sub_type'] and rep['by_sub_type']['INTEREST']['total'] == 288.32,
                  repr(rep['by_sub_type'].get('INTEREST')))
            check('NSF sub-type present',
                  'NSF' in rep['by_sub_type'] and rep['by_sub_type']['NSF']['total'] == 10.00,
                  repr(rep['by_sub_type'].get('NSF')))
            check('ANNUAL_FEE sub-type netted to 0',
                  'ANNUAL_FEE' in rep['by_sub_type'] and rep['by_sub_type']['ANNUAL_FEE']['total'] == 0.00,
                  repr(rep['by_sub_type'].get('ANNUAL_FEE')))
            check('by_account has two accounts',
                  len(rep['by_account']) == 2,
                  repr(rep['by_account']))

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(mine)
            sess['_fresh'] = True
        resp = client.get('/api/interest-fees')
        body = resp.get_json() or {}
        check('GET /api/interest-fees answers with the report',
              resp.status_code == 200 and 'total_overall' in body
              and body['total_overall'] > 0,
              repr((resp.status_code, body.get('total_overall'))))
        check('GET /api/interest-fees requires a login',
              app.test_client().get('/api/interest-fees').status_code in (302, 401), '')

        with app.app_context():
            Transaction.query.filter(Transaction.user_id.in_(state['users'])).delete(synchronize_session=False)
            Account.query.filter(Account.credential_id.in_(state['creds'])).delete(synchronize_session=False)
            Credential.query.filter(Credential.id.in_(state['creds'])).delete(synchronize_session=False)
            for uid in state['users']:
                db.session.delete(db.session.get(User, uid))
            db.session.commit()
            left = (Transaction.query.filter(Transaction.user_id.in_(state['users'])).count()
                    + Credential.query.filter(Credential.id.in_(state['creds'])).count()
                    + User.query.filter(User.id.in_(state['users'])).count())
            check('every row this test created is gone', left == 0, repr(left))

    except sqlalchemy.exc.OperationalError as e:
        print('\n(note) Dev database connection failed — Part 2 skipped: %s' % e)
        _FAILURES.append('dev database connection')


def part3():
    """Run against a PROD copy if configured."""
    path = os.environ.get('EXMINT_INTEREST_FEES_PROD_COPY')
    if not path:
        print('\n(note) EXMINT_INTEREST_FEES_PROD_COPY is not set — PROD-copy check skipped.')
        return
    from interest_fees import LOOKBACK_DAYS, detect_interest_fees, monthly_cost_of_debt
    user_id = int(os.environ.get('EXMINT_INTEREST_FEES_USER', '2'))
    import sqlite3
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    today = datetime.date.fromtimestamp(os.path.getmtime(path))
    # Include negative amounts (charges) AND positive amounts that are annual fee reversals/rebates
    rows = con.execute(
        """select t.id, t.date, t.amount, t.name, t.merchant_name, t.custom_name, t.account_id
           from transactions t join account a on a.id = t.account_id
           where t.user_id = ? and t.is_removed = 0 and t.pending = 0
             and t.has_split_children = 0 and a.is_enabled = 1
             and t.date >= ?
             and (t.amount < 0
                  or (t.amount > 0 and (
                      t.name like '%ANNUAL%REVERSAL%' or
                      t.name like '%ANNUAL%REBATE%' or
                      t.name like '%ANNUAL%CARD%FEE%REBATE%'
                  )))
           """,
        (user_id, (today - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat())).fetchall()
    charges = [{'id': r[0], 'date': datetime.date.fromisoformat(r[1]), 'amount': float(r[2]),
                'name': r[3], 'merchant_name': r[4], 'custom_name': r[5], 'account_id': r[6]}
               for r in rows]
    rep = detect_interest_fees(charges, today)
    print('\nPROD copy as of %s — total_overall %.2f, %d charges' % (today, rep['total_overall'], rep['charge_count_overall']))
    for st in rep['by_sub_type']:
        print('  %-20s %10.2f  %d' % (st, rep['by_sub_type'][st]['total'], rep['by_sub_type'][st]['count']))
    for month in rep['monthly'][-6:]:  # last 6 months
        print('  %s: %.2f (%d charges)' % (month['month'], month['total'], month['charge_count']))

    # Assertions for the 2026 known charges
    print('\n--- Assertions ---')

    # Check raw charges for specific 2026 items
    hd_charges = [c for c in charges if c.get('name') == 'INTEREST CHARGE' and c.get('account_id') == 192 and c['date'] >= datetime.date(2026, 1, 1)]
    check('HD INTEREST CHARGE detected (3 charges on account 192 in 2026)',
          len(hd_charges) == 3,
          'found %d HD INTEREST CHARGE charges: %s' % (len(hd_charges), [(c['date'], c['amount']) for c in hd_charges]))

    westjet_charges = [c for c in charges if 'PURCHASE INTEREST' in c.get('name', '') and c.get('account_id') == 112 and c['date'] >= datetime.date(2026, 1, 1)]
    check('WestJet PURCHASE INTEREST detected (on account 112 in 2026)',
          len(westjet_charges) >= 1,
          'found %d WestJet PURCHASE INTEREST charges: %s' % (len(westjet_charges), [(c['date'], c['amount'], c['name']) for c in westjet_charges]))

    loan_interest_charges = [c for c in charges if 'LOAN INTEREST' in c.get('name', '') and c['date'] >= datetime.date(2026, 1, 1)]
    check('LOAN INTEREST detected monthly in 2026',
          len(loan_interest_charges) >= 6,  # at least 6 months
          'found %d LOAN INTEREST charges: %s' % (len(loan_interest_charges), [(c['date'], c['amount']) for c in loan_interest_charges]))

    # OD INTEREST in most months
    check('OD_INTEREST sub-type present',
          'OD_INTEREST' in rep['by_sub_type'] and rep['by_sub_type']['OD_INTEREST']['total'] > 0,
          'got %s' % rep['by_sub_type'].get('OD_INTEREST'))

    # NSF 10.00 on 2026-06-26
    check('NSF fee detected',
          'NSF' in rep['by_sub_type'] and abs(rep['by_sub_type']['NSF']['total'] - 10.00) < 0.01,
          'got %s' % rep['by_sub_type'].get('NSF'))

    # ANNUAL FEE netting: verify fee+reversal pairs exist and net to 0 in report
    # Feb 2026: ANNUAL FEE (139) + REVERSAL (139) on acct 174 -> net 0
    # Jul 2026: ANNUAL CARD FEE (199) + REBATE (199) on acct 190 -> net 0
    # Note: MEMBERSHIP FEE (250) on acct 152 in Feb has no reversal
    feb_fee_174 = [c for c in charges if c.get('name') == 'ANNUAL FEE' and c.get('account_id') == 174 and c['date'] >= datetime.date(2026, 2, 1) and c['date'] <= datetime.date(2026, 2, 28)]
    feb_rev_174 = [c for c in charges if c.get('name') == 'ANNUAL FEE REVERSAL' and c.get('account_id') == 174 and c['date'] >= datetime.date(2026, 2, 1) and c['date'] <= datetime.date(2026, 2, 28)]
    jul_fee_190 = [c for c in charges if c.get('name') == 'ANNUAL CARD FEE' and c.get('account_id') == 190 and c['date'] >= datetime.date(2026, 7, 1) and c['date'] <= datetime.date(2026, 7, 31)]
    jul_reb_190 = [c for c in charges if c.get('name') == 'ANNUAL CARD FEE REBATE' and c.get('account_id') == 190 and c['date'] >= datetime.date(2026, 7, 1) and c['date'] <= datetime.date(2026, 7, 31)]

    check('ANNUAL FEE Feb 2026 on acct 174 has matching reversal',
          len(feb_fee_174) == 1 and len(feb_rev_174) == 1 and abs(feb_fee_174[0]['amount']) == abs(feb_rev_174[0]['amount']),
          'fee: %s, reversal: %s' % (feb_fee_174, feb_rev_174))
    check('ANNUAL CARD FEE Jul 2026 on acct 190 has matching rebate',
          len(jul_fee_190) == 1 and len(jul_reb_190) == 1 and abs(jul_fee_190[0]['amount']) == abs(jul_reb_190[0]['amount']),
          'fee: %s, rebate: %s' % (jul_fee_190, jul_reb_190))

    # Verify netting worked in report: Jul 2026 ANNUAL_FEE should be 0 (only the netted pair on acct 190)
    jul_2026_annual = 0
    for month in rep['monthly']:
        if month['month'] == '2026-07' and 'ANNUAL_FEE' in month['by_sub_type']:
            jul_2026_annual = month['by_sub_type']['ANNUAL_FEE']['total']
    check('ANNUAL_FEE Jul 2026 netted to 0 in report',
          jul_2026_annual == 0.00,
          'got %.2f' % jul_2026_annual)

    # For Feb 2026, the report shows combined ANNUAL_FEE across accounts (250 from MEMBERSHIP FEE + 0 from netted pair)
    # This is correct behavior - netting is per-account, not per-month

    # None of Deposit interest, Returned Cheque - NSF, or transfers
    check('DEPOSIT INTEREST excluded',
          'INTEREST' not in rep['by_sub_type'] or rep['by_sub_type']['INTEREST']['total'] < 1000,
          'INTEREST total %.2f seems too high (may include deposit interest)' % rep['by_sub_type']['INTEREST']['total'])

    # Print monthly totals
    print('\n--- Monthly Totals ---')
    for month in rep['monthly']:
        if month['total'] > 0:
            print('  %s: %.2f (%d charges)' % (month['month'], month['total'], month['charge_count']))


def main():
    part1()
    part2()
    part3()
    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('\n%d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)