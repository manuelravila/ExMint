#!/usr/bin/env python
"""test_csv_amount_sign_and_dedup.py — CSV amount sign + count-aware dedup.

Run from the repository root:

    ./venv/bin/python test_csv_amount_sign_and_dedup.py

Part A always runs and needs no application or database. Importing
``core_views`` only binds a Blueprint and imports the models/config modules (no
Flask application context required), so the pure helpers can be unit-tested
standalone — the same approach as ``test_csv_import_routing.py`` and
``test_csv_preamble_and_mapping.py``. Part A covers:

  * ``core_views._apply_amount_sign`` for ``as_is`` / ``invert`` / ``None`` /
    ``''`` and the unknown-value ``ValueError``;
  * the count-aware dedup bookkeeping (``core_views._CsvDedupTracker``):
    multiplicity of an identical K1 row, re-import of the same content, and the
    K2 Plaid-overlap budget.

Part B is an opt-in live check against the DEV database. It only runs when
``EXMINT_LIVE_TEST=1`` is set, and hard-aborts unless the configured database URI
contains ``_dev_db``. To avoid touching any real account, Part B creates its own
throw-away ``User`` + ``Credential`` + ``Account`` and deletes them (and every
row it created) in a ``finally`` block. It exercises the real
``/api/transactions/import-csv/import`` and ``/api/v1/transactions/import-csv/import``
endpoints for: an inverted purchase stored negative, an as-is purchase stored
positive, rejection of an unknown ``amount_sign``, two identical rows both
stored, a re-import inserting zero, and the K2 budget case.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import json
import os
import sys
from decimal import Decimal

# The two names below do not exist on the pre-fix tree. Importing them is done
# defensively so Part A still runs (and reports concrete FAILs) before the fix.
try:
    from core_views import _apply_amount_sign, _CsvDedupTracker
except ImportError:  # pragma: no cover - only true before the fix
    _apply_amount_sign = None
    _CsvDedupTracker = None


_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


# ── Part A: _apply_amount_sign ───────────────────────────────────────────────

def _test_apply_amount_sign():
    print('── _apply_amount_sign ──')
    missing = '_apply_amount_sign missing (pre-fix tree)'
    if _apply_amount_sign is None:
        check('as_is leaves the amount unchanged', False, missing)
        check('None leaves the amount unchanged', False, missing)
        check("'' leaves the amount unchanged", False, missing)
        check('invert negates the amount', False, missing)
        check('unknown value raises ValueError', False, missing)
        return

    amount = Decimal('13.43')
    check(
        "'as_is' leaves a positive purchase positive",
        _apply_amount_sign(amount, 'as_is') == Decimal('13.43'),
        repr(_apply_amount_sign(amount, 'as_is')),
    )
    check(
        'None defaults to as_is',
        _apply_amount_sign(amount, None) == Decimal('13.43'),
        repr(_apply_amount_sign(amount, None)),
    )
    check(
        "'' defaults to as_is",
        _apply_amount_sign(amount, '') == Decimal('13.43'),
        repr(_apply_amount_sign(amount, '')),
    )
    check(
        "'invert' turns an owe-style purchase into money out",
        _apply_amount_sign(amount, 'invert') == Decimal('-13.43'),
        repr(_apply_amount_sign(amount, 'invert')),
    )
    check(
        "'invert' turns a negative payment positive",
        _apply_amount_sign(Decimal('-50.00'), 'invert') == Decimal('50.00'),
        repr(_apply_amount_sign(Decimal('-50.00'), 'invert')),
    )
    check(
        'zero negates to zero',
        _apply_amount_sign(Decimal('0.00'), 'invert') == Decimal('0.00'),
    )

    raised = False
    try:
        _apply_amount_sign(amount, 'sideways')
    except ValueError:
        raised = True
    check('unknown value raises ValueError', raised)

    raised = False
    try:
        _apply_amount_sign(amount, 'AS_IS')
    except ValueError:
        raised = True
    check('case-sensitive unknown value raises ValueError', raised)


# ── Part A: count-aware dedup bookkeeping ────────────────────────────────────

def _test_dedup_tracker():
    print('── _CsvDedupTracker (count-aware K1/K2) ──')
    missing = '_CsvDedupTracker missing (pre-fix tree)'
    if _CsvDedupTracker is None:
        check('two identical rows in an empty account -> 2 inserts', False, missing)
        check('re-import of two existing rows -> 0 inserts', False, missing)
        check('1 pending existing + 2 file rows -> 1 update + 1 insert', False, missing)
        check('K2 budget of 1 consumed once then inserts', False, missing)
        return

    # K1 multiplicity: nothing existing, two identical occurrences -> two inserts.
    tracker = _CsvDedupTracker()
    key = ('acct', '2026-10-10', Decimal('5.00'), 'dup')
    occ1 = tracker.next_k1(key, [])
    occ2 = tracker.next_k1(key, [])
    check(
        'two identical rows in an empty account -> 2 inserts',
        occ1 is None and occ2 is None,
        'occ1=%r occ2=%r' % (occ1, occ2),
    )

    # Re-import of the same content: two pre-existing rows absorb both occurrences.
    existing = [{'id': 1, 'pending': False}, {'id': 2, 'pending': False}]
    tracker = _CsvDedupTracker()
    occ1 = tracker.next_k1(key, existing)
    occ2 = tracker.next_k1(key, existing)
    check(
        're-import of two existing rows -> 0 inserts',
        occ1 is existing[0] and occ2 is existing[1],
        'occ1=%r occ2=%r' % (occ1, occ2),
    )
    check(
        're-import of two non-pending rows -> both skip',
        occ1 is not None and not occ1['pending']
        and occ2 is not None and not occ2['pending'],
    )

    # One existing pending row plus one extra occurrence: the first occurrence
    # updates the pending row, the second falls through to insert.
    pending = [{'id': 7, 'pending': True}]
    tracker = _CsvDedupTracker()
    occ1 = tracker.next_k1(key, pending)
    occ2 = tracker.next_k1(key, pending)
    actions = []
    if occ1 is not None:
        actions.append('update' if occ1['pending'] else 'skip')
    else:
        actions.append('insert')
    if occ2 is not None:
        actions.append('update' if occ2['pending'] else 'skip')
    else:
        actions.append('insert')
    check(
        '1 pending existing + 2 file rows -> 1 update + 1 insert',
        actions == ['update', 'insert'],
        repr(actions),
    )

    # K2 budget: one existing Plaid row means the first overlapping CSV row is
    # skipped and the next identical row is a genuine extra occurrence.
    tracker = _CsvDedupTracker()
    k2 = ('acct', '2026-10-09', Decimal('-7.00'))
    first = tracker.is_plaid_duplicate(k2, 1)
    second = tracker.is_plaid_duplicate(k2, 1)
    check(
        'K2 budget of 1 consumed once then inserts',
        first is True and second is False,
        'first=%r second=%r' % (first, second),
    )

    # K2 budget of 2 against 3 file rows -> exactly 1 insert.
    tracker = _CsvDedupTracker()
    decisions = [tracker.is_plaid_duplicate(k2, 2) for _ in range(3)]
    check(
        'K2 budget of 2 against 3 rows -> 2 skips + 1 insert',
        decisions == [True, True, False],
        repr(decisions),
    )


def part_a():
    print('=== Part A: pure amount-sign / dedup tests ===')
    _test_apply_amount_sign()
    _test_dedup_tracker()
    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


# ── Part B: live dev-database integration ────────────────────────────────────

def part_b():
    print('=== Part B: live dev-database amount-sign / dedup check ===')

    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    try:
        from app import app
        from models import (
            User, Credential, Account, Transaction,
            MonthlyBudget, Budget, CsvImportTemplate, db,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not import the Flask app: %r' % (exc,))
        return False

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        safe_uri = uri.split('@', 1)[-1]
        print('Part B: ABORT — refusing to run against non-dev database (%s)'
              % safe_uri)
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    from datetime import date
    from io import BytesIO
    from uuid import uuid4

    _TAG = 'EXMINT-LIVE-sign-dedup'
    _MAPPING = {'Date': 'date', 'Description': 'description', 'Amount': 'amount'}

    # Create a completely isolated test user so no real account is touched.
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

            acct = Account(status='Active', credential_id=cred_id,
                           plaid_account_id='live_test_%s' % uuid4().hex,
                           name='Live Test Card', type='credit',
                           subtype='credit card', mask='4242')
            db.session.add(acct)
            db.session.flush()
            acct_id = acct.id

            # A Plaid-synced row for the K2 budget case.
            db.session.add(Transaction(
                plaid_transaction_id='live_synced_%s' % uuid4().hex,
                user_id=user_id, credential_id=cred_id, account_id=acct_id,
                name=_TAG + ' synced', amount=Decimal('-7.00'),
                date=date(2026, 10, 9), pending=False, is_removed=False,
                last_action='added',
            ))
            db.session.commit()
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not create isolated test user: %r' % (exc,))
        return False

    print('Part B: isolated user=%s account=%s' % (user_id, acct_id))
    ok = True

    def _login(client):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _post_core(client, csv_text, extra=None):
        data = {
            'file': (BytesIO(csv_text.encode('utf-8')), 'live.csv'),
            'mapping': json.dumps(_MAPPING),
            'save_template': 'false',
            'account_id': str(acct_id),
        }
        if extra:
            data.update(extra)
        return client.post('/api/transactions/import-csv/import',
                           data=data, content_type='multipart/form-data')

    def _post_api(client, csv_text, extra=None):
        body = {'csv_content': csv_text, 'mapping': _MAPPING,
                'account_id': acct_id}
        if extra:
            body.update(extra)
        return client.post('/api/v1/transactions/import-csv/import', json=body)

    def _json(resp):
        try:
            payload = resp.get_json()
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None

    def _stored_amount(name):
        with app.app_context():
            txn = Transaction.query.filter_by(user_id=user_id, name=name).first()
            return None if txn is None else txn.amount

    def _stored_count(name):
        with app.app_context():
            return Transaction.query.filter_by(user_id=user_id, name=name).count()

    try:
        # ── Fix 1: core import honours amount_sign=invert ───────────────────
        _csv_inv = ('Date,Description,Amount\n'
                    '2026-10-08,%s invert,13.43\n' % _TAG)
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_inv, {'amount_sign': 'invert'})
        _payload = _json(_resp)
        print('Part B (invert): HTTP=%s inserted=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None))
        if _payload is None or _payload.get('inserted') != 1:
            print('Part B (invert): FAIL — expected inserted == 1')
            ok = False
        _amt = _stored_amount(_TAG + ' invert')
        if _amt != Decimal('-13.43'):
            print('Part B (invert): FAIL — stored amount is %r, expected -13.43'
                  % (_amt,))
            ok = False

        # ── Fix 1: core import as_is keeps the positive value ───────────────
        _csv_asis = ('Date,Description,Amount\n'
                     '2026-10-08,%s asis,13.43\n' % _TAG)
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_asis, {'amount_sign': 'as_is'})
        _payload = _json(_resp)
        print('Part B (as_is): HTTP=%s inserted=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None))
        if _payload is None or _payload.get('inserted') != 1:
            print('Part B (as_is): FAIL — expected inserted == 1')
            ok = False
        _amt = _stored_amount(_TAG + ' asis')
        if _amt != Decimal('13.43'):
            print('Part B (as_is): FAIL — stored amount is %r, expected 13.43'
                  % (_amt,))
            ok = False

        # ── Fix 1: unknown amount_sign is rejected with a 400 ───────────────
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_asis, {'amount_sign': 'sideways'})
        _payload = _json(_resp)
        print('Part B (bad sign): HTTP=%s body=%s' % (_resp.status_code, _payload))
        if _resp.status_code != 400:
            print('Part B (bad sign): FAIL — expected HTTP 400')
            ok = False
        elif _payload is None or 'as_is' not in str(_payload.get('error', '')) \
                or 'invert' not in str(_payload.get('error', '')):
            print('Part B (bad sign): FAIL — error does not name accepted values')
            ok = False

        # ── Fix 1: the API v1 entry point honours amount_sign too ───────────
        _csv_api = ('Date,Description,Amount\n'
                    '2026-10-08,%s api-invert,20.00\n' % _TAG)
        with app.test_client() as client:
            _login(client)
            _resp = _post_api(client, _csv_api, {'amount_sign': 'invert'})
        _payload = _json(_resp)
        print('Part B (api invert): HTTP=%s inserted=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None))
        if _payload is None or _payload.get('inserted') != 1:
            print('Part B (api invert): FAIL — expected inserted == 1')
            ok = False
        _amt = _stored_amount(_TAG + ' api-invert')
        if _amt != Decimal('-20.00'):
            print('Part B (api invert): FAIL — stored amount is %r, expected -20.00'
                  % (_amt,))
            ok = False

        with app.test_client() as client:
            _login(client)
            _resp = _post_api(client, _csv_api, {'amount_sign': 'sideways'})
        print('Part B (api bad sign): HTTP=%s' % _resp.status_code)
        if _resp.status_code != 400:
            print('Part B (api bad sign): FAIL — expected HTTP 400')
            ok = False

        # ── Fix 2: two identical rows in one file are both stored ───────────
        _csv_dup = ('Date,Description,Amount\n'
                    '2026-10-10,%s dup,5.00\n'
                    '2026-10-10,%s dup,5.00\n' % (_TAG, _TAG))
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_dup)
        _payload = _json(_resp)
        print('Part B (dup): HTTP=%s inserted=%s skipped=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None,
               _payload.get('skipped') if _payload else None))
        if _payload is None or _payload.get('inserted') != 2:
            print('Part B (dup): FAIL — expected inserted == 2')
            ok = False
        _count = _stored_count(_TAG + ' dup')
        if _count != 2:
            print('Part B (dup): FAIL — stored %d row(s), expected 2' % _count)
            ok = False

        # ── Fix 2: re-importing the same content inserts zero ───────────────
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_dup)
        _payload = _json(_resp)
        print('Part B (re-import): HTTP=%s inserted=%s skipped=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None,
               _payload.get('skipped') if _payload else None))
        if _payload is None or _payload.get('inserted') != 0:
            print('Part B (re-import): FAIL — expected inserted == 0')
            ok = False
        if _payload is not None and _payload.get('skipped') != 2:
            print('Part B (re-import): FAIL — expected skipped == 2')
            ok = False
        if _stored_count(_TAG + ' dup') != 2:
            print('Part B (re-import): FAIL — stored count changed')
            ok = False

        # ── Fix 2: K2 budget — 1 synced + 2 identical file rows -> 1 insert ─
        _csv_k2 = ('Date,Description,Amount\n'
                   '2026-10-09,%s k2,-7.00\n'
                   '2026-10-09,%s k2,-7.00\n' % (_TAG, _TAG))
        with app.test_client() as client:
            _login(client)
            _resp = _post_core(client, _csv_k2)
        _payload = _json(_resp)
        print('Part B (k2): HTTP=%s inserted=%s skipped=%s' %
              (_resp.status_code, _payload.get('inserted') if _payload else None,
               _payload.get('skipped') if _payload else None))
        if _payload is None or _payload.get('inserted') != 1:
            print('Part B (k2): FAIL — expected inserted == 1')
            ok = False
        if _payload is not None and _payload.get('skipped') != 1:
            print('Part B (k2): FAIL — expected skipped == 1')
            ok = False
        if _stored_count(_TAG + ' k2') != 1:
            print('Part B (k2): FAIL — expected exactly one stored k2 row')
            ok = False
    finally:
        # ── Mandatory cleanup: remove every row created for this test ───────
        try:
            with app.app_context():
                Transaction.query.filter_by(user_id=user_id).delete(
                    synchronize_session=False)
                Account.query.filter_by(credential_id=cred_id).delete(
                    synchronize_session=False)
                Credential.query.filter_by(id=cred_id).delete(
                    synchronize_session=False)
                MonthlyBudget.query.filter_by(user_id=user_id).delete(
                    synchronize_session=False)
                Budget.query.filter_by(user_id=user_id).delete(
                    synchronize_session=False)
                CsvImportTemplate.query.filter_by(user_id=user_id).delete(
                    synchronize_session=False)
                User.query.filter_by(id=user_id).delete(
                    synchronize_session=False)
                db.session.commit()
                left_t = Transaction.query.filter_by(user_id=user_id).count()
                left_a = Account.query.filter_by(credential_id=cred_id).count()
                left_u = User.query.filter_by(id=user_id).count()
            print('Part B: cleanup leftover transactions=%d accounts=%d user=%d'
                  % (left_t, left_a, left_u))
            if left_t != 0 or left_a != 0 or left_u != 0:
                print('Part B: FAIL — cleanup did not remove all test rows')
                ok = False
        except Exception as exc:  # pragma: no cover - environment dependent
            print('Part B: FAIL — cleanup error: %r' % (exc,))
            ok = False

    if ok:
        print('Part B: PASS (invert/as_is, bad-sign 400, multiplicity, re-import, K2 budget)')
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
