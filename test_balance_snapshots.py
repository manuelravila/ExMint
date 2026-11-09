#!/usr/bin/env python
"""test_balance_snapshots.py — EX-01: Balance history + debt dashboard.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_balance_snapshots.py

Verifies all EX-01 requirements:
1. Plaid balance sync:
   - Stores current_balance/available_balance from /transactions/sync;
   - Falls back to /accounts/get for accounts omitted by the delta OR whose
     sync payload had NULL balances;
   - Logs Plaid error code and message when /accounts/get raises ApiException;
   - Writes an account_balance_snapshots row for every Plaid account on sync
     (both POST /api/transactions/sync and POST /api/v1/sync).
2. Manual balance entry for CSV-only / loan accounts:
   - PUT /api/accounts/<id>/reconcile and PUT /api/v1/accounts/<id>/anchor
     set the anchor and as_of date, compute balance = anchor + txns after as_of,
     and write account_balance_snapshots rows (including back-dated as_of).
3. Debt dashboard + API v1 GET /api/v1/balances/history:
   - Returns >= 2 points on the debt chart (dates, total_debt, per-account series);
   - Computes total debt across credit + loan + LOC, excluding mortgage by
     default and including mortgage when include_mortgage=true;
   - Computes change_vs_last_month and is_debt_going_down ("is my debt going down?");
   - Excludes closed accounts from debt totals;
   - Works via session auth, X-API-Key auth, GET /api/balances/history, and
     GET /api/dashboard (debt_history).
"""

import datetime
import json
import os
import sys
import tempfile
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


def close(a, b, tol=Decimal('0.01')):
    if a is None or b is None:
        return False
    return abs(Decimal(str(a)) - Decimal(str(b))) <= tol


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class _FakePlaidClient:
    def __init__(self, sync_accounts, accounts_get_accounts, fail_accounts_get=False):
        self.sync_accounts = sync_accounts
        self.accounts_get_accounts = accounts_get_accounts
        self.fail_accounts_get = fail_accounts_get
        self.calls = []

    def reset(self):
        self.calls = []

    def transactions_sync(self, payload):
        self.calls.append('transactions_sync')
        return _FakeResponse({
            'added': [],
            'modified': [],
            'removed': [],
            'accounts': self.sync_accounts,
            'has_more': False,
            'next_cursor': 'cursor-ex01',
        })

    def accounts_get(self, request):
        self.calls.append('accounts_get')
        if self.fail_accounts_get:
            import plaid
            exc = plaid.ApiException(status=400, reason='Bad Request')
            exc.body = json.dumps({
                'error_code': 'ITEM_LOGIN_REQUIRED',
                'error_message': 'the login details of this item have changed',
            })
            raise exc
        return _FakeResponse({'accounts': self.accounts_get_accounts})

    def accounts_balance_get(self, request):
        self.calls.append('accounts_balance_get')
        raise AssertionError('/accounts/balance/get must never be called')


def _plaid_acct(plaid_id, mask, acct_type, subtype, current, available=None):
    return {
        'account_id': plaid_id,
        'name': 'Plaid %s %s' % (subtype, mask),
        'type': acct_type,
        'subtype': subtype,
        'mask': mask,
        'is_enabled': True,
        'balances': {'current': current, 'available': available},
    }


def _ensure_reachable_dev_db():
    """Verify the configured _dev_db is reachable.

    Aborts and exits non-zero when MySQL is unreachable, unless
    EXMINT_TEST_SQLITE=1 is set in the environment for offline sandbox runs.
    """
    import config
    from sqlalchemy import create_engine, text

    uri = str(getattr(config.Config, 'SQLALCHEMY_DATABASE_URI', '') or '')
    if '_dev_db' in uri and not uri.startswith('sqlite:'):
        try:
            eng = create_engine(uri, connect_args={'connect_timeout': 2})
            with eng.connect() as conn:
                conn.execute(text('SELECT 1'))
            eng.dispose()
            return None
        except Exception as exc:
            target = uri.split('@', 1)[-1]
            if os.environ.get('EXMINT_TEST_SQLITE') == '1':
                fd, tmp_db = tempfile.mkstemp(prefix='exmint_test_ex01_', suffix='_dev_db.sqlite')
                os.close(fd)
                config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + tmp_db
                print('NOTE: EXMINT_TEST_SQLITE=1 set and MySQL dev DB (%s) unreachable (%s); using scratch SQLite %s'
                      % (target, exc.__class__.__name__, tmp_db))
                return tmp_db
            print('ABORT — dev database unreachable (%s: %s)' % (target, exc))
            sys.exit(1)
    return None


def main():
    scratch_db = _ensure_reachable_dev_db()
    try:
        from app import app
        from models import (
            Account, AccountBalanceSnapshot, ApiKey, Credential, Transaction, User, db,
        )
        from api_views import _generate_api_key, _hash_api_key
        from core_views import _record_balance_snapshots

        uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
        if '_dev_db' not in uri:
            print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
            return False
        print('database target = %s' % uri.split('@', 1)[-1])

        tag = 'EXMINT-EX01-%s' % uuid.uuid4().hex[:8]
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        three_days_ago = today - datetime.timedelta(days=3)
        seven_days_ago = today - datetime.timedelta(days=7)
        ten_days_ago = today - datetime.timedelta(days=10)
        fourteen_days_ago = today - datetime.timedelta(days=14)
        thirty_days_ago = today - datetime.timedelta(days=30)

        state = {
            'cred_ids': [],
            'acct_ids': [],
            'key_ids': [],
            'snapshot_id_before': 0,
            'created_user_id': None,
        }
        real_client = app.plaid_client

        with app.app_context():
            if scratch_db:
                db.create_all()
            user = User.query.first()
            if user is None and scratch_db:
                user = User(
                    email='%s@example.com' % tag.lower(),
                    password_hash='x',
                    role='Admin',
                    status='Active',
                )
                db.session.add(user)
                db.session.commit()
                state['created_user_id'] = user.id
            if user is None:
                print('ABORT — no User rows found in the dev database')
                return False

            user_id = user.id
            last_snap = AccountBalanceSnapshot.query.order_by(
                AccountBalanceSnapshot.id.desc()
            ).first()
            state['snapshot_id_before'] = last_snap.id if last_snap else 0

            # Pre-existing active accounts of this user (if any on a shared dev DB)
            # are snapshotted too; keep track of our throwaway account IDs specifically.
            plaid_cred = Credential(
                user_id=user_id,
                item_id='item-plaid-%s' % tag,
                institution_name='%s Scotiabank' % tag,
                access_token='token-plaid-%s' % tag,
                status='Active',
                soft_disconnected=False,
                requires_update=False,
            )
            csv_cred = Credential(
                user_id=user_id,
                item_id='item-csv-%s' % tag,
                institution_name='%s Home Depot' % tag,
                access_token=None,
                status='Active',
                soft_disconnected=True,
                requires_update=False,
            )
            db.session.add_all([plaid_cred, csv_cred])
            db.session.commit()
            state['cred_ids'] = [plaid_cred.id, csv_cred.id]

            def make_acct(cred, suffix, name, acct_type, subtype, mask):
                a = Account(
                    status='Active',
                    credential_id=cred.id,
                    plaid_account_id='%s-%s' % (suffix, tag),
                    name=name,
                    type=acct_type,
                    subtype=subtype,
                    mask=mask,
                    is_enabled=True,
                    current_balance=None,
                    available_balance=None,
                )
                db.session.add(a)
                db.session.commit()
                state['acct_ids'].append(a.id)
                return a

            # 4 Plaid accounts: credit card, LOC, auto loan, mortgage + 1 chequing asset
            cc_acct = make_acct(plaid_cred, 'plaid-cc', '%s Visa' % tag, 'credit', 'credit card', '4101')
            loc_acct = make_acct(plaid_cred, 'plaid-loc', '%s ScotiaLine' % tag, 'credit', 'line of credit', '4102')
            loan_acct = make_acct(plaid_cred, 'plaid-loan', '%s Auto Loan' % tag, 'loan', 'auto', '4103')
            mort_acct = make_acct(plaid_cred, 'plaid-mort', '%s Mortgage' % tag, 'loan', 'mortgage', '4104')
            cheq_acct = make_acct(plaid_cred, 'plaid-cheq', '%s Chequing' % tag, 'depository', 'checking', '4105')

            # 1 CSV-only credit account (Home Depot style)
            hd_acct = make_acct(csv_cred, 'csv_acct_hd', '%s Home Depot Card' % tag, 'credit', 'credit card', '4201')

            cc_id, cc_plaid_id = cc_acct.id, cc_acct.plaid_account_id
            loc_id, loc_plaid_id = loc_acct.id, loc_acct.plaid_account_id
            loan_id, loan_plaid_id = loan_acct.id, loan_acct.plaid_account_id
            mort_id, mort_plaid_id = mort_acct.id, mort_acct.plaid_account_id
            cheq_id, cheq_plaid_id = cheq_acct.id, cheq_acct.plaid_account_id
            hd_id = hd_acct.id
            plaid_cred_id = plaid_cred.id
            csv_cred_id = csv_cred.id

            plaid_acct_ids = [cc_id, loc_id, loan_id, mort_id, cheq_id]

            full_key, _raw_key, prefix = _generate_api_key()
            api_key = ApiKey(
                user_id=user_id,
                key_hash=_hash_api_key(full_key),
                key_prefix=prefix,
                name=tag,
            )
            db.session.add(api_key)
            db.session.commit()
            state['key_ids'].append(api_key.id)
            api_headers = {'X-API-Key': full_key}

        try:
            # ── Step 1: Plaid sync populates NULL balances & writes snapshots ──
            # Notice loc_acct is in sync_accounts with current=None, available=None
            # so _sync_account_balances must NOT treat it as covered and must fall
            # back to /accounts/get for loc_acct, loan_acct, and mort_acct.
            fake_client = _FakePlaidClient(
                sync_accounts=[
                    _plaid_acct(cc_plaid_id, '4101', 'credit', 'credit card', 1500.00, 8500.00),
                    _plaid_acct(loc_plaid_id, '4102', 'credit', 'line of credit', None, None),
                    _plaid_acct(cheq_plaid_id, '4105', 'depository', 'checking', 3200.00, 3200.00),
                ],
                accounts_get_accounts=[
                    _plaid_acct(cc_plaid_id, '4101', 'credit', 'credit card', 1500.00, 8500.00),
                    _plaid_acct(loc_plaid_id, '4102', 'credit', 'line of credit', 4000.00, 6000.00),
                    _plaid_acct(loan_plaid_id, '4103', 'loan', 'auto', 8000.00, None),
                    _plaid_acct(mort_plaid_id, '4104', 'loan', 'mortgage', 250000.00, None),
                    _plaid_acct(cheq_plaid_id, '4105', 'depository', 'checking', 3200.00, 3200.00),
                ],
            )
            app.plaid_client = fake_client

            client = app.test_client()
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user_id)
                sess['_fresh'] = True

            # Test error logging when /accounts/get fails on initial attempt
            fake_client.fail_accounts_get = True
            with app.app_context():
                from core_views import _sync_account_balances
                cred_obj = db.session.get(Credential, plaid_cred_id)
                _sync_account_balances(cred_obj, payload_accounts=[])
                check(
                    'when /accounts/get fails with Plaid ApiException, it is called and handled gracefully',
                    'accounts_get' in fake_client.calls,
                    repr(fake_client.calls),
                )

            # Now run full sync via POST /api/transactions/sync
            fake_client.fail_accounts_get = False
            fake_client.reset()
            resp = client.post('/api/transactions/sync')
            check(
                'POST /api/transactions/sync succeeds',
                resp.status_code in (200, 207),
                'status=%s body=%s' % (resp.status_code, resp.get_data(as_text=True)),
            )
            check(
                'sync called transactions_sync and fell back to accounts_get for uncovered/NULL accounts',
                'transactions_sync' in fake_client.calls and 'accounts_get' in fake_client.calls,
                repr(fake_client.calls),
            )

            with app.app_context():
                for aid in plaid_acct_ids:
                    acct_row = db.session.get(Account, aid)
                    check(
                        'Plaid account %s (%s) current_balance is no longer NULL after sync' % (acct_row.mask, acct_row.subtype),
                        acct_row.current_balance is not None,
                        repr(acct_row.current_balance),
                    )
                    snap_row = AccountBalanceSnapshot.query.filter_by(
                        account_id=aid, snapshot_date=today
                    ).first()
                    check(
                        'Plaid account %s (%s) has a snapshot in account_balance_snapshots after sync' % (acct_row.mask, acct_row.subtype),
                        snap_row is not None and snap_row.source == 'plaid',
                        repr(snap_row and (str(snap_row.balance), snap_row.source)),
                    )

            # Also verify POST /api/v1/sync updates balances and snapshots
            fake_client.sync_accounts = [
                _plaid_acct(cc_plaid_id, '4101', 'credit', 'credit card', 1200.00, 8800.00),
                _plaid_acct(loc_plaid_id, '4102', 'credit', 'line of credit', 3500.00, 6500.00),
                _plaid_acct(loan_plaid_id, '4103', 'loan', 'auto', 7500.00, None),
                _plaid_acct(mort_plaid_id, '4104', 'loan', 'mortgage', 249000.00, None),
                _plaid_acct(cheq_plaid_id, '4105', 'depository', 'checking', 3500.00, 3500.00),
            ]
            fake_client.reset()
            v1_sync_resp = client.post('/api/v1/sync', headers=api_headers)
            check(
                'POST /api/v1/sync succeeds and refreshes snapshots',
                v1_sync_resp.status_code in (200, 207),
                str(v1_sync_resp.status_code),
            )
            with app.app_context():
                cc_snap = AccountBalanceSnapshot.query.filter_by(
                    account_id=cc_id, snapshot_date=today
                ).first()
                check(
                    'POST /api/v1/sync updated Visa snapshot to -1200.00',
                    cc_snap is not None and Decimal(cc_snap.balance) == Decimal('-1200.00'),
                    repr(cc_snap and str(cc_snap.balance)),
                )

            # ── Step 2: Manual balance entry for CSV-only account ──────────────
            # Seed stale 'sum'-source snapshots on the CSV card for each of the
            # last 14 days, plus two transactions:
            #   - 10 days ago (in (today-14, today-7]): -$150.00 purchase
            #   -  3 days ago (in (today-7,  today]):   +$350.00 payment
            # When we anchor at $600 owed as of today-14:
            #   - today-14 snapshot = -600.00 (anchor+tx)
            #   - today-7  snapshot = -600.00 + (-150.00) = -750.00 (anchor+tx)
            #   - today    snapshot = -600.00 - 150.00 + 350.00 = -400.00 (anchor+tx)
            with app.app_context():
                from core_views import _upsert_snapshot
                db.session.add_all([
                    Transaction(
                        plaid_transaction_id='txn-hd-purchase-%s' % tag,
                        user_id=user_id,
                        credential_id=csv_cred_id,
                        account_id=hd_id,
                        name='LUMBER PURCHASE',
                        amount=Decimal('-150.00'),
                        date=ten_days_ago,
                        pending=False,
                        is_removed=False,
                    ),
                    Transaction(
                        plaid_transaction_id='txn-hd-payment-%s' % tag,
                        user_id=user_id,
                        credential_id=csv_cred_id,
                        account_id=hd_id,
                        name='PAYMENT RECEIVED',
                        amount=Decimal('350.00'),
                        date=three_days_ago,
                        pending=False,
                        is_removed=False,
                    ),
                ])
                for offset in range(15):
                    snap_day = today - datetime.timedelta(days=offset)
                    _upsert_snapshot(hd_id, snap_day, Decimal('-999.00'), 'sum')
                db.session.commit()

            rec_14_resp = client.put(
                '/api/accounts/%d/reconcile' % hd_id,
                json={'balance': 600.00, 'as_of': fourteen_days_ago.isoformat()},
            )
            rec_14_data = rec_14_resp.get_json() or {}
            check(
                'manual balance entry (PUT /api/accounts/<id>/reconcile) works for CSV account',
                rec_14_resp.status_code == 200
                and rec_14_data.get('balance_source') == 'anchor+tx'
                and close(rec_14_data.get('balance'), -400.00),
                repr(rec_14_data),
            )

            with app.app_context():
                hd_snap_14 = AccountBalanceSnapshot.query.filter_by(
                    account_id=hd_id, snapshot_date=fourteen_days_ago
                ).first()
                hd_snap_7 = AccountBalanceSnapshot.query.filter_by(
                    account_id=hd_id, snapshot_date=seven_days_ago
                ).first()
                hd_snap_today = AccountBalanceSnapshot.query.filter_by(
                    account_id=hd_id, snapshot_date=today
                ).first()
                check(
                    'back-dated manual balance recomputes snapshots >= as_of (today-7 equals anchor + txns in (as_of, today-7])',
                    hd_snap_14 is not None
                    and Decimal(hd_snap_14.balance) == Decimal('-600.00')
                    and hd_snap_14.source == 'anchor+tx'
                    and hd_snap_7 is not None
                    and Decimal(hd_snap_7.balance) == Decimal('-750.00')
                    and hd_snap_7.source == 'anchor+tx'
                    and hd_snap_today is not None
                    and Decimal(hd_snap_today.balance) == Decimal('-400.00')
                    and hd_snap_today.source == 'anchor+tx',
                    repr((
                        hd_snap_14 and (str(hd_snap_14.balance), hd_snap_14.source),
                        hd_snap_7 and (str(hd_snap_7.balance), hd_snap_7.source),
                        hd_snap_today and (str(hd_snap_today.balance), hd_snap_today.source),
                    )),
                )

            # Anchor at 30 days ago ($600 owed) and verify both 30d-ago and today snapshots
            rec_resp = client.put(
                '/api/accounts/%d/reconcile' % hd_id,
                json={'balance': 600.00, 'as_of': thirty_days_ago.isoformat()},
            )
            with app.app_context():
                hd_snap_past = AccountBalanceSnapshot.query.filter_by(
                    account_id=hd_id, snapshot_date=thirty_days_ago
                ).first()
                hd_snap_today = AccountBalanceSnapshot.query.filter_by(
                    account_id=hd_id, snapshot_date=today
                ).first()
                check(
                    'manual balance entry recorded both the back-dated anchor snapshot (-600.00) and today\'s snapshot (-400.00)',
                    rec_resp.status_code == 200
                    and hd_snap_past is not None
                    and Decimal(hd_snap_past.balance) == Decimal('-600.00')
                    and hd_snap_today is not None
                    and Decimal(hd_snap_today.balance) == Decimal('-400.00'),
                    repr((
                        hd_snap_past and str(hd_snap_past.balance),
                        hd_snap_today and str(hd_snap_today.balance),
                    )),
                )

            # Also test v1 manual anchor endpoint on CSV account (updating anchor today to 350.00 owed)
            v1_anc_resp = client.put(
                '/api/v1/accounts/%d/anchor' % hd_id,
                headers=api_headers,
                json={'balance': 350.00, 'as_of': today.isoformat()},
            )
            v1_anc_data = v1_anc_resp.get_json() or {}
            check(
                'API v1 manual anchor (PUT /api/v1/accounts/<id>/anchor) updates CSV account balance to -350.00',
                v1_anc_resp.status_code == 200
                and v1_anc_data.get('balance_source') == 'anchor+tx'
                and close(v1_anc_data.get('balance'), -350.00),
                repr(v1_anc_data),
            )

            # ── Step 3 & 4: Debt history & GET /api/v1/balances/history ────────
            # First verify that when an account only has 2 recent snapshots
            # (today-1 and today), GET /api/v1/balances/history still uses
            # today-30d as previous_month_date (not yesterday) and includes weekly
            # trend points so len(dates) >= 3.
            with app.app_context():
                from core_views import _upsert_snapshot
                _upsert_snapshot(cc_id, yesterday, Decimal('-1300.00'), 'plaid')
                db.session.commit()

            two_snap_resp = client.get(
                '/api/v1/balances/history?account_id=%d' % cc_id,
                headers=api_headers,
            )
            two_snap_hist = two_snap_resp.get_json() or {}
            check(
                'with only 2 recent snapshots (today-1 and today), previous_month_date is today-30d and len(dates) >= 3',
                two_snap_resp.status_code == 200
                and two_snap_hist.get('previous_month_date') == thirty_days_ago.isoformat()
                and isinstance(two_snap_hist.get('dates'), list)
                and len(two_snap_hist['dates']) >= 3,
                repr((two_snap_hist.get('previous_month_date'), two_snap_hist.get('dates'))),
            )

            # Seed last-month snapshots (30 days ago) for our Plaid debt accounts so
            # we can verify exact multi-point debt series and change vs last month:
            # 30 days ago (excl. mortgage) on our test accounts:
            #   Visa:       1800.00 (now 1200.00 -> -600.00)
            #   ScotiaLine: 4000.00 (now 3500.00 -> -500.00)
            #   Auto Loan:  8000.00 (now 7500.00 -> -500.00)
            #   Home Depot:  600.00 (now  350.00 -> -250.00)
            #   Subtotal excl. mortgage: 14,400.00 -> 12,550.00 (change = -1,850.00)
            #   Mortgage: 250,000.00 (now 249,000.00 -> -1,000.00)
            #   Subtotal incl. mortgage: 264,400.00 -> 261,550.00 (change = -2,850.00)
            with app.app_context():
                from core_views import _upsert_snapshot
                _upsert_snapshot(cc_id, thirty_days_ago, Decimal('-1800.00'), 'plaid')
                _upsert_snapshot(loc_id, thirty_days_ago, Decimal('-4000.00'), 'plaid')
                _upsert_snapshot(loan_id, thirty_days_ago, Decimal('-8000.00'), 'plaid')
                _upsert_snapshot(mort_id, thirty_days_ago, Decimal('-250000.00'), 'plaid')
                _upsert_snapshot(cheq_id, thirty_days_ago, Decimal('3000.00'), 'plaid')
                db.session.commit()

            hist_resp = client.get('/api/v1/balances/history', headers=api_headers)
            check('GET /api/v1/balances/history returns 200', hist_resp.status_code == 200, str(hist_resp.status_code))
            hist = hist_resp.get_json() or {}

            check(
                'debt chart has >= 2 date points',
                isinstance(hist.get('dates'), list)
                and len(hist['dates']) >= 2
                and len(hist.get('total_debt', [])) == len(hist['dates']),
                repr((hist.get('dates'), hist.get('total_debt'))),
            )

            debt_by_id = {a['id']: a for a in hist.get('debt_accounts', [])}

            check(
                'default debt view includes credit card, LOC, auto loan, CSV card and excludes mortgage & chequing',
                cc_id in debt_by_id
                and loc_id in debt_by_id
                and loan_id in debt_by_id
                and hd_id in debt_by_id
                and mort_id not in debt_by_id
                and cheq_id not in debt_by_id,
                repr(sorted(debt_by_id.keys())),
            )

            check(
                'per-account lines each have >= 2 points and accurate change_vs_last_month',
                len(debt_by_id[cc_id]['series']) >= 2
                and close(debt_by_id[cc_id]['previous_month_debt'], 1800.00)
                and close(debt_by_id[cc_id]['current_debt'], 1200.00)
                and close(debt_by_id[cc_id]['change_vs_last_month'], -600.00)
                and close(debt_by_id[hd_id]['previous_month_debt'], 600.00)
                and close(debt_by_id[hd_id]['current_debt'], 350.00)
                and close(debt_by_id[hd_id]['change_vs_last_month'], -250.00),
                repr((debt_by_id[cc_id], debt_by_id[hd_id])),
            )

            # Check mortgage toggle (include_mortgage=true)
            hist_mort_resp = client.get(
                '/api/v1/balances/history?include_mortgage=true',
                headers=api_headers,
            )
            hist_mort = hist_mort_resp.get_json() or {}
            mort_debt_by_id = {a['id']: a for a in hist_mort.get('debt_accounts', [])}
            check(
                'include_mortgage=true includes mortgage account and increases current_total_debt by 249,000.00',
                mort_id in mort_debt_by_id
                and close(
                    Decimal(str(hist_mort['current_total_debt'])) - Decimal(str(hist['current_total_debt'])),
                    Decimal('249000.00'),
                ),
                repr((hist.get('current_total_debt'), hist_mort.get('current_total_debt'))),
            )

            # Single-account filter & is_debt_going_down check
            cc_hist_resp = client.get(
                '/api/v1/balances/history?account_id=%d' % cc_id,
                headers=api_headers,
            )
            cc_hist = cc_hist_resp.get_json() or {}
            check(
                'when debt decreases (1800 -> 1200), change_vs_last_month is -600.00 and is_debt_going_down is True',
                close(cc_hist.get('current_total_debt'), 1200.00)
                and close(cc_hist.get('previous_month_total_debt'), 1800.00)
                and close(cc_hist.get('change_vs_last_month'), -600.00)
                and cc_hist.get('is_debt_going_down') is True,
                repr(cc_hist),
            )

            # Verify UI endpoints GET /api/balances/history and GET /api/dashboard
            ui_hist_resp = client.get('/api/balances/history')
            ui_hist = ui_hist_resp.get_json() or {}
            dash_resp = client.get('/api/dashboard')
            dash_data = dash_resp.get_json() or {}
            check(
                'UI GET /api/balances/history and GET /api/dashboard (debt_history) return matching debt history',
                ui_hist_resp.status_code == 200
                and dash_resp.status_code == 200
                and 'debt_history' in dash_data
                and len(dash_data['debt_history'].get('dates', [])) >= 2
                and close(ui_hist.get('current_total_debt'), dash_data['debt_history'].get('current_total_debt')),
                repr((ui_hist.get('current_total_debt'), dash_data.get('debt_history', {}).get('current_total_debt'))),
            )

            # Verify closed account is excluded from debt totals
            client.put('/api/v1/accounts/%d/closed' % hd_id, headers=api_headers, json={'closed': True})
            after_close = client.get('/api/v1/balances/history', headers=api_headers).get_json() or {}
            check(
                'closing a debt account removes its 350.00 balance from current_total_debt',
                close(
                    Decimal(str(hist['current_total_debt'])) - Decimal(str(after_close['current_total_debt'])),
                    Decimal('350.00'),
                ),
                repr((hist.get('current_total_debt'), after_close.get('current_total_debt'))),
            )

            # Invalid date parameter returns 400
            bad_resp = client.get('/api/v1/balances/history?start_date=not-a-date', headers=api_headers)
            check('malformed start_date returns 400', bad_resp.status_code == 400, str(bad_resp.status_code))

        finally:
            app.plaid_client = real_client
            with app.app_context():
                Transaction.query.filter(
                    Transaction.credential_id.in_(state['cred_ids'])
                ).delete(synchronize_session=False)
                AccountBalanceSnapshot.query.filter(
                    AccountBalanceSnapshot.id > state['snapshot_id_before']
                ).delete(synchronize_session=False)
                Account.query.filter(
                    Account.id.in_(state['acct_ids'])
                ).delete(synchronize_session=False)
                Credential.query.filter(
                    Credential.id.in_(state['cred_ids'])
                ).delete(synchronize_session=False)
                ApiKey.query.filter(
                    ApiKey.id.in_(state['key_ids'])
                ).delete(synchronize_session=False)
                if state['created_user_id'] is not None:
                    User.query.filter_by(id=state['created_user_id']).delete(synchronize_session=False)
                db.session.commit()

                left = (
                    Transaction.query.filter(Transaction.credential_id.in_(state['cred_ids'])).count()
                    + Account.query.filter(Account.id.in_(state['acct_ids'])).count()
                    + Credential.query.filter(Credential.id.in_(state['cred_ids'])).count()
                    + ApiKey.query.filter(ApiKey.id.in_(state['key_ids'])).count()
                    + AccountBalanceSnapshot.query.filter(
                        AccountBalanceSnapshot.id > state['snapshot_id_before']
                    ).count()
                )
                check('cleanup removed every test row', left == 0, '%d left' % left)
    finally:
        if scratch_db and os.path.exists(scratch_db):
            try:
                os.unlink(scratch_db)
            except OSError:
                pass

    return not _FAILURES


if __name__ == '__main__':
    result = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if result else 1)
