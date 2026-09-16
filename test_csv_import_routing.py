#!/usr/bin/env python
"""test_csv_import_routing.py — regression tests for CSV import account routing.

Run from the repository root:

    ./venv/bin/python test_csv_import_routing.py

Part A always runs and needs no application or database: it unit-tests
``csv_import_routing``.

Part B is an opt-in live check against the DEV database. It only runs when
``EXMINT_LIVE_TEST=1`` is set, and hard-aborts if the app's database URI is not
a ``_dev_db`` database. It derives an account number that is unroutable against
the live active-account masks (rather than hard-coding one that happens to be
absent from a particular database) and posts a single row using it, then asserts
the route returns HTTP 200 with zero inserts, a non-empty per-row error list
(the production crash was a 500), and no persisted Transaction row.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import json
import os
import sys

from csv_import_routing import (
    build_mask_index,
    normalize_account_key,
    resolve_row_account,
    unroutable_reason,
)

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
    print('=== Part A: csv_import_routing unit tests ===')

    # ── normalize_account_key ──────────────────────────────────────────────
    check(
        "normalize ' 05992-5006614 ' -> '059925006614'",
        normalize_account_key(' 05992-5006614 ') == '059925006614',
        repr(normalize_account_key(' 05992-5006614 ')),
    )
    check(
        "normalize '****6614' -> '6614'",
        normalize_account_key('****6614') == '6614',
        repr(normalize_account_key('****6614')),
    )
    check("normalize None -> ''", normalize_account_key(None) == '')
    check("normalize '' -> ''", normalize_account_key('') == '')
    check("normalize '   ' -> ''", normalize_account_key('   ') == '')

    # ── build_mask_index ───────────────────────────────────────────────────
    idx = build_mask_index([(190, '6845')])
    check("build_mask_index indexes raw mask", idx.get('6845') == 190, repr(idx))

    idx = build_mask_index([(5, '006845')])
    check(
        "build_mask_index indexes lstrip('0') variant",
        idx.get('6845') == 5,
        repr(idx),
    )

    idx = build_mask_index([(1, None), (2, ''), (3, '6845')])
    check('build_mask_index ignores None mask', 1 not in idx.values(), repr(idx))
    check('build_mask_index ignores empty mask', 2 not in idx.values(), repr(idx))
    check('build_mask_index keeps valid mask', idx.get('6845') == 3, repr(idx))

    idx = build_mask_index([(1, ' 006845 ')])
    check(
        'build_mask_index indexes normalized mask',
        idx.get('006845') == 1 and idx.get('6845') == 1,
        repr(idx),
    )

    # ── resolve_row_account ────────────────────────────────────────────────
    idx = build_mask_index([(190, '6845')])
    check('resolve exact mask match', resolve_row_account('6845', idx) == 190)
    check(
        'resolve long number by last 4',
        resolve_row_account('123456786845', idx) == 190,
    )
    check(
        'resolve dashed/asterisked value',
        resolve_row_account('****-6845', idx) == 190,
    )

    idx = build_mask_index([(7, '006845')])
    check(
        'resolve leading-zero variant',
        resolve_row_account('6845', idx) == 7,
    )

    check(
        "resolve production case '24087118' vs mask '6845' is None",
        resolve_row_account('24087118', build_mask_index([(190, '6845')])) is None,
    )
    idx = build_mask_index([(190, '6845')])
    check('resolve value shorter than 4 chars is None', resolve_row_account('123', idx) is None)
    check('resolve empty value is None', resolve_row_account('', idx) is None)
    check('resolve None value is None', resolve_row_account(None, idx) is None)

    # ── unroutable_reason ──────────────────────────────────────────────────
    check(
        'unroutable_reason names the offending value',
        unroutable_reason('24087118')
        == "account number '24087118' matches none of your active accounts",
        repr(unroutable_reason('24087118')),
    )
    check(
        'unroutable_reason(None) reports absence',
        unroutable_reason(None) == 'no account number in the row',
    )
    check(
        "unroutable_reason('') reports absence",
        unroutable_reason('') == 'no account number in the row',
    )

    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database regression check ===')

    if os.environ.get('EXMINT_LIVE_TEST') != '1':
        print('Part B: SKIP (set EXMINT_LIVE_TEST=1 to run)')
        return True

    try:
        from app import app
        from models import User
    except Exception as exc:  # pragma: no cover - environment dependent
        print('Part B: ABORT — could not import the Flask app: %r' % (exc,))
        return False

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        safe_uri = uri.split('@', 1)[-1]
        print('Part B: ABORT — refusing to run against non-dev database (%s)' % safe_uri)
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('Part B: ABORT — no User rows found in the dev database')
            return False
        user_id = user.id

        # Derive an account number that is unroutable against the live masks.
        # A hard-coded sentinel is unsafe: if any active mask shares its last 4
        # digits the legacy rule routes the row to that account and the row is
        # imported. Pick the first candidate that resolve_row_account() cannot
        # route, then verify that before using it.
        from models import Account, Credential

        _idx = build_mask_index(
            (a.id, a.mask)
            for a in Account.query.join(Credential).filter(
                Credential.user_id == user_id,
                Account.status == 'Active',
            ).all()
        )
        _sentinel = None
        for _candidate in (
            '9999', '8888', '7777', '6666', '5555',
            '4444', '3333', '2222', '1111', '0001',
        ):
            if resolve_row_account(_candidate, _idx) is None:
                _sentinel = _candidate
                break
        if _sentinel is None:
            print(
                'Part B: ABORT — every candidate account number resolves against '
                'the live active-account masks; cannot construct an unroutable '
                'sentinel for this database.'
            )
            return False
        _sentinel_match = resolve_row_account(_sentinel, _idx)
        print('Part B: chosen sentinel %s -> %s' % (_sentinel, _sentinel_match))
        if _sentinel_match is not None:  # defensive: must never happen
            print(
                'Part B: ABORT — chosen sentinel %s unexpectedly resolves to '
                'account %s' % (_sentinel, _sentinel_match)
            )
            return False
        print(
            'Part B: confirmed resolve_row_account(%r, idx) is None' % _sentinel
        )

    from io import BytesIO

    row_description = 'Live routing check (unroutable sentinel)'
    csv_text = (
        'Date,Description,Amount,Account Number\n'
        '2026-09-15,%s,-1.00,%s\n' % (row_description, _sentinel)
    )
    mapping = {
        'Date': 'date',
        'Description': 'description',
        'Amount': 'amount',
        'Account Number': 'account_number',
    }

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        resp = client.post(
            '/api/transactions/import-csv/import',
            data={
                'file': (BytesIO(csv_text.encode('utf-8')), 'live_routing_check.csv'),
                'mapping': json.dumps(mapping),
                'save_template': 'false',
            },
            content_type='multipart/form-data',
        )

    ok = True
    print('Part B: HTTP status = %s' % resp.status_code)
    if resp.status_code != 200:
        print('Part B: FAIL — expected HTTP 200, got %s' % resp.status_code)
        ok = False

    try:
        payload = resp.get_json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        print('Part B: FAIL — response body was not JSON')
        return False

    print('Part B: inserted = %s' % payload.get('inserted'))
    print('Part B: errors = %s' % payload.get('errors'))
    if payload.get('inserted') != 0:
        print('Part B: FAIL — expected inserted == 0, got %s' % payload.get('inserted'))
        ok = False
    if not payload.get('errors'):
        print('Part B: FAIL — expected a non-empty errors list')
        ok = False

    # Direct database check: the unroutable row must not have leaked a row.
    from models import Transaction

    with app.app_context():
        leaked = Transaction.query.filter_by(
            user_id=user_id,
            name=row_description,
        ).count()
    print('Part B: persisted rows named %r = %d (expected 0)' % (row_description, leaked))
    if leaked != 0:
        print(
            'Part B: FAIL — %d Transaction row(s) persisted for an unroutable row'
            % leaked
        )
        ok = False

    if ok:
        print('Part B: PASS (HTTP 200 / 0 inserted / non-empty errors)')
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
