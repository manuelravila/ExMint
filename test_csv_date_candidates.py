#!/usr/bin/env python
"""test_csv_date_candidates.py — CSV date-column candidates for analyze.

Run from the repository root:

    ./venv/bin/python test_csv_date_candidates.py

Part A always runs and needs no application or database. Importing
``core_views`` only binds a Blueprint and imports the models/config modules
(no Flask application context is required), so the pure helper can be
unit-tested standalone — the same approach as
``test_csv_preamble_and_mapping.py`` and ``test_csv_amount_sign_and_dedup.py``.
Part A covers:

  * ``_csv_date_candidates`` on a header set carrying both a transaction date
    and a posting date -> both candidates, in column order;
  * a single-date-column file -> exactly one candidate;
  * a file with no date-like column -> an empty list;
  * the existing ``_auto_detect_mapping`` result for the same header set is
    unchanged (the exclusive used-fields rule still leaves only one date).

Part B is an opt-in live check against the DEV database. It only runs when
``EXMINT_LIVE_TEST=1`` is set, and hard-aborts unless the configured database
URI contains ``_dev_db``. It posts the same header set to both analyze routes
(the session UI route and the API v1 route) with an injected login session and
asserts the JSON carries ``date_candidates``. Both routes are read-only, so no
rows are written and no cleanup is required.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import csv
import os
import sys
from io import StringIO

from core_views import _auto_detect_mapping

# The helper under test does not exist on the pre-fix tree. Import it
# defensively so Part A still runs (and reports concrete FAILs) before the fix.
try:
    from core_views import _csv_date_candidates
except ImportError:  # pragma: no cover - only true before the fix
    _csv_date_candidates = None


# The real header shape: two date-ish columns and a single amount column.
_HEADERS = [
    'Item #', 'Card #', 'Transaction Date', 'Posting Date',
    'Transaction Amount', 'Description',
]
_CSV_TEXT = (
    ','.join(_HEADERS) + '\n'
    "1,'1111222233334444',20260105,20260107,13.43,SAMPLE MERCHANT TORONTO ON\n"
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


def _candidates(headers):
    if _csv_date_candidates is None:
        return None
    return _csv_date_candidates(headers)


def _test_date_candidates():
    print('── _csv_date_candidates ──')
    missing = '_csv_date_candidates missing (pre-fix tree)'

    check(
        'two date columns -> both candidates in column order',
        _csv_date_candidates is not None
        and _candidates(_HEADERS) == ['Transaction Date', 'Posting Date'],
        missing if _csv_date_candidates is None else repr(_candidates(_HEADERS)),
    )
    check(
        'single date column -> one candidate',
        _csv_date_candidates is not None
        and _candidates(['Date', 'Description', 'Amount']) == ['Date'],
        missing if _csv_date_candidates is None
        else repr(_candidates(['Date', 'Description', 'Amount'])),
    )
    check(
        "single 'Transaction Date' -> one candidate",
        _csv_date_candidates is not None
        and _candidates(['Transaction Date', 'Amount', 'Description'])
        == ['Transaction Date'],
        missing if _csv_date_candidates is None
        else repr(_candidates(['Transaction Date', 'Amount', 'Description'])),
    )
    check(
        "'Posting Date' only -> one candidate",
        _csv_date_candidates is not None
        and _candidates(['Posting Date', 'Amount', 'Description'])
        == ['Posting Date'],
        missing if _csv_date_candidates is None
        else repr(_candidates(['Posting Date', 'Amount', 'Description'])),
    )
    check(
        'no date-like column -> empty list',
        _csv_date_candidates is not None
        and _candidates(['Item #', 'Description', 'Amount']) == [],
        missing if _csv_date_candidates is None
        else repr(_candidates(['Item #', 'Description', 'Amount'])),
    )
    check(
        'empty header list -> empty list',
        _csv_date_candidates is not None and _candidates([]) == [],
        missing if _csv_date_candidates is None else repr(_candidates([])),
    )


def _test_auto_mapping_unchanged():
    print('── _auto_detect_mapping (no regression) ──')
    mapping = _auto_detect_mapping(_HEADERS)
    expected = {
        'Item #': None,
        'Card #': 'account_number',
        'Transaction Date': 'date',
        'Posting Date': None,
        'Transaction Amount': 'amount',
        'Description': 'description',
    }
    for header, field in expected.items():
        check(
            "auto-map '%s' -> %r" % (header, field),
            mapping.get(header) == field,
            repr(mapping),
        )
    # The exclusive used-fields rule still leaves Posting Date unmapped even
    # though it is a legitimate date candidate.
    check(
        'auto-mapping still yields a single date, candidates yield two',
        mapping.get('Transaction Date') == 'date'
        and mapping.get('Posting Date') is None
        and _csv_date_candidates is not None
        and _candidates(_HEADERS) == ['Transaction Date', 'Posting Date'],
        repr(mapping),
    )


def _test_pipeline_parses_real_header():
    print('── analyze pipeline header parse ──')
    reader = csv.DictReader(StringIO(_CSV_TEXT))
    headers = [h for h in reader.fieldnames if h is not None]
    check('pipeline headers match the real header set',
          headers == _HEADERS, repr(headers))
    check(
        'pipeline date candidates match the real header set',
        _csv_date_candidates is not None
        and _candidates(headers) == ['Transaction Date', 'Posting Date'],
        repr(_candidates(headers)) if _csv_date_candidates is not None
        else '_csv_date_candidates missing (pre-fix tree)',
    )


def part_a():
    print('=== Part A: pure date-candidate / mapping tests ===')
    _test_date_candidates()
    _test_auto_mapping_unchanged()
    _test_pipeline_parses_real_header()
    print('Part A: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    return not _FAILURES


def part_b():
    print('=== Part B: live dev-database analyze check ===')

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
        print('Part B: ABORT — refusing to run against non-dev database (%s)'
              % safe_uri)
        return False
    print('Part B: database target = %s' % uri.split('@', 1)[-1])

    from io import BytesIO

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('Part B: ABORT — no User rows found in the dev database')
            return False
        user_id = user.id

    expected = ['Transaction Date', 'Posting Date']
    ok = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

        # 1. Session UI route (multipart/form-data).
        resp = client.post(
            '/api/transactions/import-csv/analyze',
            data={'file': (BytesIO(_CSV_TEXT.encode('utf-8')), 'statement.csv')},
            content_type='multipart/form-data',
        )
        # 2. API v1 route, JSON branch (its own `_csv_date_candidates` import).
        resp_v1 = client.post(
            '/api/v1/transactions/import-csv/analyze',
            json={'csv_content': _CSV_TEXT},
        )

    for label, response in (('UI route', resp), ('API v1 route', resp_v1)):
        print('Part B: %s HTTP status = %s' % (label, response.status_code))
        payload = response.get_json() if response.status_code == 200 else None
        if payload is None:
            print('Part B: FAIL — %s expected HTTP 200 + JSON' % label)
            ok = False
            continue
        print('Part B: %s date_candidates = %s'
              % (label, payload.get('date_candidates')))
        print('Part B: %s auto_mapping = %s'
              % (label, payload.get('auto_mapping')))
        if payload.get('date_candidates') != expected:
            print('Part B: FAIL — %s date_candidates != %r'
                  % (label, expected))
            ok = False
        mapping = payload.get('auto_mapping') or {}
        if mapping.get('Transaction Date') != 'date':
            print('Part B: FAIL — %s Transaction Date did not map to date'
                  % label)
            ok = False
        if mapping.get('Posting Date') is not None:
            print('Part B: FAIL — %s Posting Date should stay unmapped' % label)
            ok = False

    if ok:
        print('Part B: PASS (both routes report date_candidates)')
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
