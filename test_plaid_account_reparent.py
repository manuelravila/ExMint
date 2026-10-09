#!/usr/bin/env python
"""test_plaid_account_reparent.py — regression tests for Plaid account re-parenting.

Run from the repository root:

    ./venv/bin/python test_plaid_account_reparent.py

Part A always runs and needs no application or database: it unit-tests
``core_views._account_needs_reparent`` with a lightweight
``types.SimpleNamespace`` stand-in for an ``Account`` row.  Importing
``core_views`` does not require a Flask application context (module import only
binds a Blueprint and imports the models/config modules), so the direct import
works standalone — the same approach as ``test_plaid_cursor_lifecycle.py``.

Part B is an opt-in live check against the DEV database.  It only runs when
``EXMINT_LIVE_TEST=1`` is set, and it hard-aborts unless the app's configured
database URI contains ``_dev_db`` (never run against staging/production).  It
creates a throwaway soft-disconnected (paused) credential plus one Active
account row, then re-links the credential through
``POST /handle_token_and_accounts`` with the Plaid client monkeypatched so that
``item_public_token_exchange`` returns a NEW Item id + token and ``accounts_get``
returns the same physical account under a BRAND NEW ``account_id``.  It asserts
the existing row adopted the new id (while keeping its credential and Active
status) and that an incoming transaction carrying the new id was persisted
rather than silently dropped.  Every row it created is deleted and the cleanup
is asserted.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import os
import sys
import uuid
from types import SimpleNamespace

from core_views import _account_needs_reparent

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
    print('=== Part A: _account_needs_reparent unit tests ===')

    def row(credential_id=1, plaid_account_id='plaid-old'):
        return SimpleNamespace(credential_id=credential_id,
                               plaid_account_id=plaid_account_id)

    check(
        'same credential with a different incoming id needs re-parenting',
        _account_needs_reparent(row(), 1, 'plaid-new') is True,
        repr(_account_needs_reparent(row(), 1, 'plaid-new')),
    )
    check(
        'same credential with the same id does not need re-parenting',
        _account_needs_reparent(row(plaid_account_id='plaid-new'), 1, 'plaid-new') is False,
        repr(_account_needs_reparent(row(plaid_account_id='plaid-new'), 1, 'plaid-new')),
    )
    check(
        'a row owned by a different credential is left alone',
        _account_needs_reparent(row(credential_id=2), 1, 'plaid-new') is False,
        repr(_account_needs_reparent(row(credential_id=2), 1, 'plaid-new')),
    )
    check(
        'a csv_acct_ synthetic id is left to the CSV branch',
        _account_needs_reparent(row(plaid_account_id='csv_acct_abc'), 1, 'plaid-new') is False,
        repr(_account_needs_reparent(row(plaid_account_id='csv_acct_abc'), 1, 'plaid-new')),
    )
    check(
        'incoming id None does not need re-parenting',
        _account_needs_reparent(row(), 1, None) is False,
        repr(_account_needs_reparent(row(), 1, None)),
    )
    check(
        'incoming empty-string id does not need re-parenting',
        _account_needs_reparent(row(), 1, '') is False,
        repr(_account_needs_reparent(row(), 1, '')),
    )
    check(
        'existing_account None does not need re-parenting',
        _account_needs_reparent(None, 1, 'plaid-new') is False,
        repr(_account_needs_reparent(None, 1, 'plaid-new')),
    )
    check(
        'a falsy stored id does not need re-parenting',
        _account_needs_reparent(row(plaid_account_id=None), 1, 'plaid-new') is False,
        repr(_account_needs_reparent(row(plaid_account_id=None), 1, 'plaid-new')),
    )
    check(
        'helper is pure and repeatable',
        _account_needs_reparent(row(), 1, 'plaid-new') is True
        and _account_needs_reparent(row(), 1, 'plaid-new') is True,
    )

    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database account re-parenting check ===')

    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    try:
        from app import app
        from models import User, Account, Credential, Transaction, db
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not import the Flask app: %r' % (exc,))
        return False

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        safe_uri = uri.split('@', 1)[-1]
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % safe_uri)
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    _TAG = 'EXMINT-LIVE-REPARENT'
    _suffix = uuid.uuid4().hex[:12]
    _institution = '%s-%s' % (_TAG, _suffix)
    _old_item_id = 'old-item-%s' % _suffix
    _new_item_id = 'new-item-%s' % _suffix
    _new_token = 'access-token-%s' % _suffix
    _old_plaid_account_id = 'plaid-old-%s' % _suffix
    _new_plaid_account_id = 'plaid-new-%s' % _suffix
    _plaid_transaction_id = 'plaid-txn-%s' % _suffix
    _account_name = 'Live Reparent Test Checking'
    _account_fixture = {
        'account_id': _new_plaid_account_id,
        'name': _account_name,
        'type': 'depository',
        'subtype': 'checking',
        'mask': '0002',
        'is_enabled': True,
    }
    _transaction_fixture = {
        'transaction_id': _plaid_transaction_id,
        'account_id': _new_plaid_account_id,
        'name': 'Live Reparent Test Transaction',
        'amount': 12.34,
        'iso_currency_code': 'CAD',
        'category': ['Shopping'],
        'merchant_name': 'Live Test Merchant',
        'payment_channel': 'online',
        'date': '2024-01-02',
        'pending': False,
    }

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return self._payload

        def __getitem__(self, key):
            return self._payload[key]

    class _FakePlaidClient:
        def __init__(self):
            self.calls = []

        def item_public_token_exchange(self, request):
            self.calls.append('item_public_token_exchange')
            return _FakeResponse({'access_token': _new_token, 'item_id': _new_item_id})

        def accounts_get(self, request):
            self.calls.append('accounts_get')
            return _FakeResponse({'accounts': [_account_fixture]})

        def accounts_balance_get(self, request):
            self.calls.append('accounts_balance_get')
            return _FakeResponse({'accounts': [
                {'account_id': _new_plaid_account_id,
                 'balances': {'current': 12.34, 'available': 12.34}}
            ]})

        def transactions_sync(self, payload):
            self.calls.append('transactions_sync')
            return _FakeResponse({
                'added': [_transaction_fixture], 'modified': [], 'removed': [],
                'has_more': False, 'next_cursor': None,
            })

        def item_webhook_update(self, request):
            self.calls.append('item_webhook_update')
            return _FakeResponse({'item': {'item_id': _new_item_id}})

    state = {'user_id': None, 'cred_id': None, 'acct_id': None}
    ok = True

    # ── Setup: throwaway paused credential + Active account (old Item) ──────
    with app.app_context():
        user = User.query.first()
        if user is None:
            print('Part B: ABORT — no User rows found in the dev database')
            return False
        state['user_id'] = user.id

        cred = Credential(
            user_id=user.id,
            item_id=_old_item_id,
            institution_name=_institution,
            access_token=_new_token,
            soft_disconnected=True,
            requires_update=False,
        )
        db.session.add(cred)
        db.session.commit()
        state['cred_id'] = cred.id

        acct = Account(
            status='Active',
            credential_id=cred.id,
            plaid_account_id=_old_plaid_account_id,
            name=_account_name,
            type=_account_fixture['type'],
            subtype=_account_fixture['subtype'],
            mask=_account_fixture['mask'],
            is_enabled=True,
        )
        db.session.add(acct)
        db.session.commit()
        state['acct_id'] = acct.id

    print('Part B: created credential id=%s account id=%s institution=%s'
          % (state['cred_id'], state['acct_id'], _institution))

    def _post(json_payload):
        fake = _FakePlaidClient()
        original = app.plaid_client
        app.plaid_client = fake
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(state['user_id'])
                    sess['_fresh'] = True
                return client.post('/handle_token_and_accounts', json=json_payload)
        finally:
            app.plaid_client = original

    def _cleanup():
        with app.app_context():
            deleted_txns = Transaction.query.filter_by(
                account_id=state['acct_id']
            ).delete(synchronize_session=False)
            acct = db.session.get(Account, state['acct_id'])
            if acct is not None:
                db.session.delete(acct)
            cred = db.session.get(Credential, state['cred_id'])
            if cred is not None:
                db.session.delete(cred)
            db.session.commit()
            return deleted_txns

    try:
        # ── Re-link the paused credential; Plaid issues a new account_id ─────
        resp = _post({
            'credential_id': state['cred_id'],
            'public_token': 'public-sandbox-fake',
            'institution_name': _institution,
            'is_refresh': False,
        })
        payload = resp.get_json() if resp.is_json else None
        print('Part B (re-link): HTTP status = %s' % resp.status_code)
        if resp.status_code != 200 or not isinstance(payload, dict):
            print('Part B (re-link): FAIL — expected HTTP 200 + JSON, got %s / %r'
                  % (resp.status_code, payload))
            ok = False

        with app.app_context():
            acct = db.session.get(Account, state['acct_id'])
            print('Part B (re-link): stored plaid_account_id=%s credential_id=%s status=%s'
                  % (acct.plaid_account_id, acct.credential_id, acct.status))
            if acct.plaid_account_id != _new_plaid_account_id:
                print('Part B (re-link): FAIL — stale plaid_account_id survived the re-link')
                ok = False
            if acct.credential_id != state['cred_id']:
                print('Part B (re-link): FAIL — credential_id was changed unexpectedly')
                ok = False
            if acct.status != 'Active':
                print('Part B (re-link): FAIL — status was changed unexpectedly')
                ok = False

        # Downstream: a transaction carrying the new id must be persisted
        if isinstance(payload, dict):
            added = (payload.get('sync_summary') or {}).get('added')
            print('Part B (re-link): sync_summary.added = %s' % added)
            if added != 1:
                print('Part B (re-link): FAIL — expected 1 persisted transaction, got %s' % added)
                ok = False

        with app.app_context():
            stored_txn = Transaction.query.filter_by(
                plaid_transaction_id=_plaid_transaction_id
            ).first()
            print('Part B (re-link): stored transaction = %s' % (stored_txn,))
            if stored_txn is None or stored_txn.account_id != state['acct_id']:
                print('Part B (re-link): FAIL — transaction was dropped or linked elsewhere')
                ok = False
    finally:
        deleted_txns = _cleanup()
        with app.app_context():
            left_cred = db.session.get(Credential, state['cred_id'])
            left_acct = db.session.get(Account, state['acct_id'])
        print('Part B: cleanup deleted %d transaction(s); leftover credential=%s '
              'account=%s' % (deleted_txns, left_cred, left_acct))
        if left_cred is not None or left_acct is not None:
            print('Part B: FAIL — cleanup did not restore the dev database')
            ok = False

    return ok


def main():
    ok_a = part_a()
    print('')
    ok_b = part_b()
    print('')
    if ok_a and ok_b:
        print('RESULT: PASS')
        return 0
    print('RESULT: FAIL (%d unit failures)' % len(_FAILURES))
    return 1


if __name__ == '__main__':
    sys.exit(main())
