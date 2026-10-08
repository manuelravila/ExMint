#!/usr/bin/env python
"""test_plaid_cursor_lifecycle.py — regression tests for Plaid cursor/Item lifecycles.

Run from the repository root:

    ./venv/bin/python test_plaid_cursor_lifecycle.py

Part A always runs and needs no application or database: it unit-tests
``core_views._cursor_valid_for_item``.  In this codebase importing core_views
does NOT require a Flask application context (module import only binds a
Blueprint and imports the models/config modules), so ``from core_views import
_cursor_valid_for_item`` works standalone — verified before Part A was written.

Part B is an opt-in live check against the DEV database.  It only runs when
``EXMINT_LIVE_TEST=1`` is set, and it hard-aborts unless the app's configured
database URI contains ``_dev_db`` (never run against staging/production).  It
creates a throwaway credential + account, then drives
``POST /handle_token_and_accounts`` with the Plaid client monkeypatched so that
``item_public_token_exchange`` returns a NEW Item id + token and ``accounts_get``
returns the throwaway account.  It asserts the stored ``transactions_cursor`` is
discarded because a Plaid cursor is valid only for the Item that produced it.
It then exercises the same-Item ``is_refresh`` path and asserts the cursor is
preserved.  Every row it created is deleted and the cleanup is asserted.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import os
import sys
import uuid

from core_views import _cursor_valid_for_item

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
    print('=== Part A: _cursor_valid_for_item unit tests ===')

    check(
        'same non-empty Item keeps the stored cursor string',
        _cursor_valid_for_item('item-1', 'item-1', 'cursor-abc') == 'cursor-abc',
        repr(_cursor_valid_for_item('item-1', 'item-1', 'cursor-abc')),
    )
    check(
        'different Item drops the stored cursor',
        _cursor_valid_for_item('item-1', 'item-2', 'cursor-abc') is None,
        repr(_cursor_valid_for_item('item-1', 'item-2', 'cursor-abc')),
    )
    check(
        'stored cursor None stays None when the Item matches',
        _cursor_valid_for_item('item-1', 'item-1', None) is None,
    )
    check(
        'stored Item id None with a cursor returns None',
        _cursor_valid_for_item(None, 'item-1', 'cursor-abc') is None,
        repr(_cursor_valid_for_item(None, 'item-1', 'cursor-abc')),
    )
    check(
        'empty stored Item id with a cursor returns None',
        _cursor_valid_for_item('', 'item-1', 'cursor-abc') is None,
        repr(_cursor_valid_for_item('', 'item-1', 'cursor-abc')),
    )
    check(
        'new Item id None returns None',
        _cursor_valid_for_item('item-1', None, 'cursor-abc') is None,
        repr(_cursor_valid_for_item('item-1', None, 'cursor-abc')),
    )
    check(
        'empty new Item id returns None',
        _cursor_valid_for_item('item-1', '', 'cursor-abc') is None,
        repr(_cursor_valid_for_item('item-1', '', 'cursor-abc')),
    )
    check(
        'helper is pure and repeatable',
        _cursor_valid_for_item('item-1', 'item-1', 'cursor-abc') == 'cursor-abc'
        and _cursor_valid_for_item('item-1', 'item-1', 'cursor-abc') == 'cursor-abc',
    )

    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database cursor/Item lifecycle check ===')

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

    _TAG = 'EXMINT-LIVE-CURSOR'
    _suffix = uuid.uuid4().hex[:12]
    _institution = '%s-%s' % (_TAG, _suffix)
    _old_item_id = 'old-item-%s' % _suffix
    _new_item_id = 'new-item-%s' % _suffix
    _old_cursor = 'cursor-old-%s' % _suffix
    _same_item_cursor = 'cursor-same-%s' % _suffix
    _new_token = 'access-token-%s' % _suffix
    _plaid_account_id = 'plaid-account-%s' % _suffix
    _account_fixture = {
        'account_id': _plaid_account_id,
        'name': 'Live Cursor Test Checking',
        'type': 'depository',
        'subtype': 'checking',
        'mask': '0001',
        'is_enabled': True,
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
                {'account_id': _plaid_account_id,
                 'balances': {'current': 10.5, 'available': 10.5}}
            ]})

        def transactions_sync(self, payload):
            self.calls.append('transactions_sync')
            return _FakeResponse({
                'added': [], 'modified': [], 'removed': [],
                'has_more': False, 'next_cursor': None,
            })

        def item_webhook_update(self, request):
            self.calls.append('item_webhook_update')
            return _FakeResponse({'item': {'item_id': _new_item_id}})

    state = {'user_id': None, 'cred_id': None, 'acct_id': None}
    ok = True

    # ── Setup: throwaway credential + account ───────────────────────────────
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
            access_token=None,
            soft_disconnected=True,
            requires_update=False,
            transactions_cursor=_old_cursor,
        )
        db.session.add(cred)
        db.session.commit()
        state['cred_id'] = cred.id

        acct = Account(
            status='Active',
            credential_id=cred.id,
            plaid_account_id=_plaid_account_id,
            name=_account_fixture['name'],
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
        # ── Case 1: reconnect with a NEW Item must drop the old cursor ───────
        resp = _post({
            'credential_id': state['cred_id'],
            'public_token': 'public-sandbox-fake',
            'institution_name': _institution,
            'is_refresh': False,
        })
        payload = resp.get_json() if resp.is_json else None
        print('Part B (reconnect): HTTP status = %s' % resp.status_code)
        if resp.status_code != 200 or not isinstance(payload, dict):
            print('Part B (reconnect): FAIL — expected HTTP 200 + JSON, got %s / %r'
                  % (resp.status_code, payload))
            ok = False

        with app.app_context():
            cred = db.session.get(Credential, state['cred_id'])
            print('Part B (reconnect): stored item_id=%s cursor=%r '
                  'soft_disconnected=%s access_token=%r'
                  % (cred.item_id, cred.transactions_cursor, cred.soft_disconnected,
                     cred.access_token))
            if cred.transactions_cursor is not None:
                print('Part B (reconnect): FAIL — stale cursor survived the Item change')
                ok = False
            if cred.item_id != _new_item_id:
                print('Part B (reconnect): FAIL — new item_id was not stored')
                ok = False
            if cred.access_token != _new_token:
                print('Part B (reconnect): FAIL — new access token was not stored')
                ok = False
            if cred.soft_disconnected:
                print('Part B (reconnect): FAIL — credential is still soft_disconnected')
                ok = False

        # ── Case 2: is_refresh (same Item) must PRESERVE the cursor ──────────
        with app.app_context():
            cred = db.session.get(Credential, state['cred_id'])
            cred.transactions_cursor = _same_item_cursor
            db.session.commit()

        resp2 = _post({
            'credential_id': state['cred_id'],
            'public_token': 'public-sandbox-fake',
            'is_refresh': True,
        })
        payload2 = resp2.get_json() if resp2.is_json else None
        print('Part B (is_refresh same Item): HTTP status = %s' % resp2.status_code)
        if resp2.status_code != 200 or not isinstance(payload2, dict):
            print('Part B (is_refresh same Item): FAIL — expected HTTP 200 + JSON, '
                  'got %s / %r' % (resp2.status_code, payload2))
            ok = False

        with app.app_context():
            cred = db.session.get(Credential, state['cred_id'])
            print('Part B (is_refresh same Item): item_id=%s cursor=%r'
                  % (cred.item_id, cred.transactions_cursor))
            if cred.item_id != _new_item_id:
                print('Part B (is_refresh same Item): FAIL — Item changed unexpectedly')
                ok = False
            if cred.transactions_cursor != _same_item_cursor:
                print('Part B (is_refresh same Item): FAIL — cursor was not preserved')
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
