#!/usr/bin/env python
"""test_recurring.py — EX-06: one list of everything that charges every month.

Run from the repository root (DEV database only):

    ./venv/bin/python test_recurring.py

Part 1 runs the pure rule (``detect_recurring``) over synthetic series with a
fixed ``today``: fixed and slightly-varying monthly bills, a bill whose price
doubled (Fido $30 -> $60 with a $120 month), a biweekly charge, two policies
from the same insurer on the same day (Economical x2), random repeats and a
two-charge merchant that must NOT be detected, a cancelled subscription
(inactive, left out of the total), a brand-new one (``new`` alert), and the
same bill synced through two cards (counted once).

Part 2 writes a few of those series for a throwaway user, reads them back
through ``collect_recurring`` and ``GET /api/recurring``, checks that another
user's charges stay invisible, and deletes everything it created.

To re-check the real bills, point EXMINT_RECURRING_PROD_COPY at the read-only
SQLite copy of PROD (``.qwen/make_prod_copy.py``) and the user id to read:

    EXMINT_RECURRING_PROD_COPY=.qwen/exmint_prodcopy.sqlite EXMINT_RECURRING_USER=2 \\
        ./venv/bin/python test_recurring.py
"""

import datetime
import os
import sqlite3
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


def series(name, amounts, offsets, merchant=None, account_id=1):
    return [{'id': None, 'date': d(o), 'amount': a, 'name': name,
             'merchant_name': merchant, 'custom_name': None, 'account_id': account_id}
            for a, o in zip(amounts, offsets)]


def monthly_offsets(n, last=5, gap=30):
    return [last + gap * i for i in range(n)]


def synthetic():
    charges = []
    charges += series('Amazon.ca Prime Member VANCOUVER BC', [5.64] * 6, monthly_offsets(6, 3))
    charges += series('BELL CANADA (OB) MONTREAL QC', [114.13, 110.0, 118.0, 107.35, 114.13],
                      monthly_offsets(5, 10), merchant='Bell Canada')
    # Fido: $30 for three months, a $120 month, then ~$60 (newest last).
    fido_amounts = [30.51, 30.51, 32.49, 120.91, 64.30, 59.89][::-1]
    charges += series('Fido 020', fido_amounts, monthly_offsets(6, 10), merchant='Fido')
    charges += series('GYM CLUB BIWEEKLY', [20.0] * 6, monthly_offsets(6, 2, 14))
    # Two Economical policies charged the same day, plus RBC life on the same account.
    charges += series('INSURANCE', [323.90] * 4, monthly_offsets(4, 17), merchant='Economical Ins.')
    charges += series('INSURANCE', [101.56] * 4, monthly_offsets(4, 17), merchant='Economical Ins.')
    charges += series('Insurance RBCINS-LIFE', [100.42] * 4, monthly_offsets(4, 17))
    # Noise: three charges at random gaps / random amounts — not a bill.
    charges += series('RANDOM HARDWARE STORE', [40.0, 41.0, 39.0], [3, 13, 63])
    charges += series('TWICE ONLY STREAMING', [9.99, 9.99], [5, 35])
    # Cancelled: last charge 100 days ago.
    charges += series('OLD MAGAZINE SUB', [12.0] * 5, monthly_offsets(5, 100))
    # Brand new: third charge 5 days ago.
    charges += series('NEW MUSIC SERVICE', [11.99] * 3, monthly_offsets(3, 5))
    # The same bill seen through an old and a replacement card.
    charges += series('NETFLIX.COM', [16.49] * 4, monthly_offsets(4, 8), account_id=1)
    charges += series('NETFLIX.COM', [16.49] * 4, monthly_offsets(4, 8), account_id=2)
    # An inflow is never a charge.
    charges += series('PAYROLL DEPOSIT', [-2000.0] * 4, monthly_offsets(4, 1))
    return charges


def part1():
    from recurring import ALERT_NEW, ALERT_PRICE_CHANGE, detect_recurring, merchant_key

    check('merchant keys survive bank noise',
          merchant_key('FIDO MOBILE ******2752 020') == merchant_key('Fido 020') == 'fido'
          and merchant_key('Insurance Economical Ins.') == merchant_key(None, 'INSURANCE', 'Economical Ins.') == 'economical'
          and merchant_key('DLO*Starlink Ciudad de Mex') == 'starlink'
          and merchant_key('AMZN Mktp CA*515QD0730 TORONTO ON') == 'amzn'
          and merchant_key('Miscellaneous Payment NSLSC') == 'nslsc',
          repr([merchant_key('FIDO MOBILE ******2752 020'), merchant_key('Insurance Economical Ins.'),
                merchant_key('DLO*Starlink Ciudad de Mex'), merchant_key('Miscellaneous Payment NSLSC')]))

    rep = detect_recurring(synthetic(), TODAY)
    active = rep['recurring']
    by_key = {}
    for s in active + rep['inactive']:
        by_key.setdefault(s['key'], []).append(s)

    def one(key):
        return (by_key.get(key) or [None])[0]

    prime = one('amazon')
    check('a fixed monthly subscription is detected',
          prime and prime['cadence'] == 'monthly' and prime['last_amount'] == 5.64 and prime['active'],
          repr(prime))
    check('next expected date is the last charge plus the usual gap',
          prime and prime['next_expected'] == (d(3) + datetime.timedelta(days=30)).isoformat(),
          repr(prime and prime['next_expected']))

    bell = one('bell')
    check('a bill varying within 15% is one series, with no price alert',
          bell and bell['charges'] == 5 and not bell['alerts'], repr(bell))

    fido = by_key.get('fido') or []
    check('a bill whose price doubled stays ONE series',
          len(fido) == 1 and fido[0]['charges'] == 6 and fido[0]['active'], repr(fido))
    check('the price change is reported as an alert with old and new amounts',
          fido and any(a['type'] == ALERT_PRICE_CHANGE and a['old_amount'] == 120.91
                       and a['new_amount'] == 64.30 for a in fido[0]['alerts']),
          repr(fido and fido[0]['alerts']))

    gym = one('gym')
    check('a biweekly charge counts 26/12 times per month',
          gym and gym['cadence'] == 'biweekly' and gym['monthly_equivalent'] == round(20.0 * 26 / 12, 2),
          repr(gym))

    eco = sorted(s['last_amount'] for s in by_key.get('economical', []))
    check('two policies from the same insurer on the same day are two series',
          eco == [101.56, 323.90], repr(eco))
    check('RBC life is its own series', one('rbcins') is not None, repr(sorted(by_key)))

    check('random repeats are not a recurring charge', 'random' not in by_key, repr(sorted(by_key)))
    check('two charges are not enough', 'twice' not in by_key, repr(sorted(by_key)))
    check('inflows are never charges', 'payroll' not in by_key, repr(sorted(by_key)))

    old = one('old')
    check('a cancelled subscription is listed as inactive, not active',
          old and not old['active'] and old in rep['inactive'], repr(old))

    new = one('new')
    check('a recurring charge that just appeared raises a "new" alert',
          new and any(a['type'] == ALERT_NEW for a in new['alerts'])
          and any(a['type'] == ALERT_NEW and a['key'] == 'new' for a in rep['alerts']),
          repr(new))
    check('an established bill raises no "new" alert',
          prime and not any(a['type'] == ALERT_NEW for a in prime['alerts']), repr(prime))

    netflix = by_key.get('netflix') or []
    check('a bill synced through two cards is counted once',
          len(netflix) == 1 and netflix[0]['charges'] == 4, repr(netflix))

    expected_total = round(sum(s['monthly_equivalent'] for s in active), 2)
    hand_total = round(5.64 + 114.13 + 59.89 + 20.0 * 26 / 12 + 323.90 + 101.56 + 100.42
                       + 11.99 + 16.49, 2)
    check('total_monthly is the sum of active series at their latest price',
          rep['total_monthly'] == expected_total == hand_total,
          repr((rep['total_monthly'], expected_total, hand_total)))


def part2():
    from app import app
    from models import Account, Credential, Transaction, User, db
    from recurring import collect_recurring

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri or '_prd_db' in uri or '_stg_db' in uri:
        print('ABORT — refusing to run against a non-dev database (%s)' % uri.split('@', 1)[-1])
        _FAILURES.append('dev database')
        return
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-RECUR-%s' % uuid.uuid4().hex[:8]
    today = datetime.date.today()
    state = {'users': [], 'creds': []}
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
            acct = Account(credential_id=cred.id, plaid_account_id='recur-%s' % uuid.uuid4().hex,
                           name='%s card' % tag, type='credit', subtype='credit card', mask='0001')
            db.session.add(acct)
            db.session.commit()
            for name, amount, offset in rows:
                db.session.add(Transaction(
                    plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:12]),
                    user_id=user.id, credential_id=cred.id, account_id=acct.id,
                    name=name, amount=Decimal(str(amount)), date=today - datetime.timedelta(days=offset),
                    iso_currency_code='CAD'))
            db.session.commit()
            return user.id

        mine = make_user('a', [('STREAMCO %s' % tag, -15.99, o) for o in (4, 34, 64, 94)]
                         + [('PHONECO %s' % tag, -50.00, o) for o in (40, 70, 100)]
                         + [('PHONECO %s' % tag, -80.00, 10)]      # this month's bill moved +60%
                         + [('REFUND %s' % tag, 25.00, o) for o in (5, 35, 65)])
        other = make_user('b', [('SECRETCO %s' % tag, -99.00, o) for o in (3, 33, 63, 93)])

        rep = collect_recurring(mine, today)
        keys = {s['key'] for s in rep['recurring']}
        check('collect_recurring reads the user\'s bills from the database',
              {'streamco', 'phoneco'} <= keys, repr(sorted(keys)))
        phone = [s for s in rep['recurring'] if s['key'] == 'phoneco']
        check('a price change on the latest bill is flagged',
              phone and any(a['type'] == 'price_change' for a in phone[0]['alerts']), repr(phone))
        check('another user\'s bills are not visible', 'secretco' not in keys, repr(sorted(keys)))
        check('credits are not charges', 'refund' not in keys, repr(sorted(keys)))

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(mine)
        sess['_fresh'] = True
    resp = client.get('/api/recurring')
    body = resp.get_json() or {}
    check('GET /api/recurring answers with the list and monthly total',
          resp.status_code == 200 and 'total_monthly' in body
          and {s['key'] for s in body.get('recurring', [])} >= {'streamco', 'phoneco'},
          repr((resp.status_code, body.get('total_monthly'))))
    check('GET /api/recurring requires a login',
          app.test_client().get('/api/recurring').status_code in (302, 401), '')

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


def part3():
    path = os.environ.get('EXMINT_RECURRING_PROD_COPY')
    if not path:
        print('\n(note) EXMINT_RECURRING_PROD_COPY is not set — PROD-copy check skipped.')
        return
    from recurring import LOOKBACK_DAYS, detect_recurring
    user_id = int(os.environ.get('EXMINT_RECURRING_USER', '2'))
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    # "today" is the day the copy was taken, not the day the test runs.
    today = datetime.date.fromtimestamp(os.path.getmtime(path))
    rows = con.execute(
        """select t.id, t.date, t.amount, t.name, t.merchant_name, t.custom_name, t.account_id
           from transactions t join account a on a.id = t.account_id
           where t.user_id = ? and t.is_removed = 0 and t.pending = 0
             and t.has_split_children = 0 and t.amount < 0 and a.is_enabled = 1 and t.date >= ?""",
        (user_id, (today - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat())).fetchall()
    charges = [{'id': r[0], 'date': datetime.date.fromisoformat(r[1]), 'amount': -float(r[2]),
                'name': r[3], 'merchant_name': r[4], 'custom_name': r[5], 'account_id': r[6]}
               for r in rows]
    rep = detect_recurring(charges, today)
    print('\nPROD copy as of %s — total_monthly %.2f' % (today, rep['total_monthly']))
    for s in rep['recurring'] + rep['inactive']:
        print('  %-8s %-38s %-8s %8.2f/mo last %s next %s %s' % (
            'active' if s['active'] else 'stopped', s['merchant'][:38], s['cadence'],
            s['monthly_equivalent'], s['last_date'], s['next_expected'],
            ','.join(a['type'] for a in s['alerts'])))
    found = {}
    for s in rep['recurring'] + rep['inactive']:
        found.setdefault(s['key'], []).append(s)
    expected = ['bell', 'freedom', 'fido', 'economical', 'rbcins', 'foresters',
                'starlinksat', 'amazon', 'cineplex', 'nslsc']
    missing = [k for k in expected if k not in found]
    check('PROD copy: every bill from the 2026-10-22 analysis is detected', not missing, repr(missing))
    check('PROD copy: Economical is two policies', len(found.get('economical', [])) == 2,
          repr(found.get('economical')))


def main():
    part1()
    part2()
    part3()
    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('\n%d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)
