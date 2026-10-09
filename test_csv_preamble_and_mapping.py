#!/usr/bin/env python
"""test_csv_preamble_and_mapping.py — CSV preamble detection + auto-mapping.

Run from the repository root:

    ./venv/bin/python test_csv_preamble_and_mapping.py

Part A always runs and needs no application or database. Importing
``core_views`` only binds a Blueprint and imports the models/config modules
(no Flask application context is required), so the mapping helpers can be
unit-tested standalone — the same approach as ``test_csv_import_routing.py``
and ``test_plaid_cursor_lifecycle.py``. Part A covers:

  * ``csv_import_routing.find_header_line`` preamble detection: the exact BMO
    metadata preamble, no preamble, a blank first line, a preamble that exceeds
    25 lines (fallback to line 1) and a preamble line that contains commas but
    no known alias;
  * the BMO header auto-mapping (``Transaction Amount`` -> ``amount``,
    ``Description`` -> ``description``, ...) and the no-regression cases;
  * quote stripping in ``normalize_account_key`` / ``resolve_row_account`` /
    ``derive_mask``.

Part B is an opt-in live check against the DEV database. It only runs when
``EXMINT_LIVE_TEST=1`` is set, and hard-aborts unless the configured database
URI contains ``_dev_db``. It posts the real BMO export to the analyze endpoint
and asserts the metadata line was skipped, so the reported ``headers`` and
``row_count`` are those of the real table. The analyze endpoint is read-only,
so no cleanup is required.

No pytest is used (the venv does not have it); this is a plain-Python script
that exits non-zero on any failure.
"""

import csv
import os
import sys
from io import StringIO

from csv_import_routing import (
    build_mask_index,
    derive_mask,
    normalize_account_key,
    resolve_row_account,
)

# The two names below do not exist on the pre-fix tree. Importing them is done
# defensively so Part A still runs (and reports concrete FAILs) before the fix.
try:
    from csv_import_routing import find_header_line
except ImportError:  # pragma: no cover - only true before the fix
    find_header_line = None

try:
    from core_views import _auto_detect_mapping, _csv_content_without_preamble
except ImportError:  # pragma: no cover - only true before the fix
    from core_views import _auto_detect_mapping
    _csv_content_without_preamble = None


_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


# ── Fixtures: the real BMO export shape (metadata line, blank line, header) ──
_BMO_PREAMBLE = 'Following data is valid as of 20261008181629:'
_BMO_HEADER = ('Item #,Card #,Transaction Date,Posting Date,'
               'Transaction Amount,Description')
_BMO_ROW = ("1,'5439250703566845',20261005,20261007,13.43,"
            'VALUE VILLAGE # 2078 TORONTO ON')
_BMO_FILE = '%s\n\n%s\n%s\n' % (_BMO_PREAMBLE, _BMO_HEADER, _BMO_ROW)
_BMO_HEADERS = [
    'Item #', 'Card #', 'Transaction Date', 'Posting Date',
    'Transaction Amount', 'Description',
]

# An independent alias set used to unit-test the pure helper in isolation.
_ALIASES = {
    'date', 'transaction date', 'posting date', 'description',
    'transaction amount', 'amount', 'card #', 'account number',
}


def _find(content, max_scan_lines=25):
    return find_header_line(content, _ALIASES, max_scan_lines=max_scan_lines)


def _test_preamble_detection():
    print('── find_header_line (preamble detection) ──')
    missing = 'find_header_line missing (pre-fix tree)'

    check(
        'BMO metadata preamble -> header is line 3',
        find_header_line is not None and _find(_BMO_FILE) == 3,
        missing if find_header_line is None else repr(_find(_BMO_FILE)),
    )
    check(
        'no preamble -> header is line 1',
        find_header_line is not None
        and _find(_BMO_HEADER + '\n' + _BMO_ROW + '\n') == 1,
        missing,
    )
    check(
        'blank first line -> header is line 2',
        find_header_line is not None
        and _find('\n' + _BMO_HEADER + '\n' + _BMO_ROW + '\n') == 2,
        missing,
    )
    check(
        'comma-bearing preamble with no alias is skipped',
        find_header_line is not None
        and _find('Prepared for: Smith, John\n\n' + _BMO_HEADER + '\n') == 3,
        missing,
    )
    check(
        'preamble of 24 lines -> header is line 25 (boundary)',
        find_header_line is not None
        and _find(''.join('meta %d\n' % i for i in range(24))
                  + _BMO_HEADER + '\n') == 25,
        missing,
    )
    check(
        'preamble beyond 25 lines -> falls back to line 1',
        find_header_line is not None
        and _find(''.join('meta line %d\n' % i for i in range(26))
                  + _BMO_HEADER + '\n' + _BMO_ROW + '\n') == 1,
        missing,
    )


def _test_bmo_analyze_integration():
    print('── BMO analyze pipeline (preamble + headers + mapping) ──')
    if _csv_content_without_preamble is None:
        check(
            'analyze starts at the real BMO header line',
            False,
            '_csv_content_without_preamble missing (pre-fix tree)',
        )
        return

    content = _csv_content_without_preamble(_BMO_FILE)
    reader = csv.DictReader(StringIO(content))
    headers = [h for h in reader.fieldnames if h is not None]
    rows = list(reader)

    check(
        'analyze headers are the real table header',
        headers == _BMO_HEADERS,
        repr(headers),
    )
    check('analyze row_count == 1', len(rows) == 1, repr(len(rows)))
    if rows:
        check(
            'analyze row parsed into all seven columns',
            rows[0].get('Transaction Amount') == '13.43'
            and rows[0].get('Description') == 'VALUE VILLAGE # 2078 TORONTO ON',
            repr(rows[0]),
        )

    mapping = _auto_detect_mapping(headers)
    check(
        'integration: Transaction Amount -> amount',
        mapping.get('Transaction Amount') == 'amount',
        repr(mapping),
    )
    check(
        'integration: Description -> description',
        mapping.get('Description') == 'description',
        repr(mapping),
    )


def _test_auto_mapping():
    print('── _auto_detect_mapping ──')
    mapping = _auto_detect_mapping(_BMO_HEADERS)
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
            "BMO '%s' -> %r" % (header, field),
            mapping.get(header) == field,
            repr(mapping),
        )

    # No-regression: description aliases keep working.
    mapping = _auto_detect_mapping(['Transaction Description', 'Amount'])
    check(
        "'Transaction Description' -> description",
        mapping.get('Transaction Description') == 'description',
        repr(mapping),
    )
    mapping = _auto_detect_mapping(['Transaction Details', 'Amount'])
    check(
        "'Transaction Details' -> description",
        mapping.get('Transaction Details') == 'description',
        repr(mapping),
    )

    # No-regression: Posting Date maps to date when Transaction Date is absent.
    mapping = _auto_detect_mapping(['Posting Date', 'Description', 'Amount'])
    check(
        "'Posting Date' (no Transaction Date) -> date",
        mapping.get('Posting Date') == 'date',
        repr(mapping),
    )

    # No-regression: account_number aliases keep working.
    for header in ('Card #', 'Card Number', 'Account Number', 'Account #'):
        mapping = _auto_detect_mapping([header, 'Date', 'Amount'])
        check(
            "'%s' -> account_number" % header,
            mapping.get(header) == 'account_number',
            repr(mapping),
        )

    # The generic amount aliases land on the amount field.
    for header in ('Amount', 'Transaction Amount', 'Amt', 'Amount ($)',
                   'Value'):
        mapping = _auto_detect_mapping([header, 'Date', 'Description'])
        check(
            "'%s' -> amount" % header,
            mapping.get(header) == 'amount',
            repr(mapping),
        )


def _test_quote_stripping():
    print('── normalize_account_key / resolve_row_account / derive_mask ──')
    idx = build_mask_index([(190, '6845')])

    check(
        "normalize \"'5439250703566845'\" strips single quotes",
        normalize_account_key("'5439250703566845'") == '5439250703566845',
        repr(normalize_account_key("'5439250703566845'")),
    )
    check(
        'normalize double quotes',
        normalize_account_key('"5439250703566845"') == '5439250703566845',
        repr(normalize_account_key('"5439250703566845"')),
    )
    check(
        "resolve quoted card number against mask '6845'",
        resolve_row_account("'5439250703566845'", idx) == 190,
        repr(resolve_row_account("'5439250703566845'", idx)),
    )
    check(
        "derive_mask quoted card number -> '6845'",
        derive_mask("'5439250703566845'") == '6845',
        repr(derive_mask("'5439250703566845'")),
    )

    # Unchanged behaviour for the pre-existing contract.
    check(
        "normalize ' 05992-5006614 ' unchanged",
        normalize_account_key(' 05992-5006614 ') == '059925006614',
        repr(normalize_account_key(' 05992-5006614 ')),
    )
    check(
        "normalize '****6614' unchanged",
        normalize_account_key('****6614') == '6614',
        repr(normalize_account_key('****6614')),
    )
    check("normalize None -> ''", normalize_account_key(None) == '')
    check("normalize '' -> ''", normalize_account_key('') == '')
    check(
        "resolve plain '6845' still works",
        resolve_row_account('6845', idx) == 190,
    )
    check("derive_mask plain '6845' -> '6845'", derive_mask('6845') == '6845')


def part_a():
    print('=== Part A: pure preamble / mapping / quote tests ===')
    _test_preamble_detection()
    _test_bmo_analyze_integration()
    _test_auto_mapping()
    _test_quote_stripping()
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

    ok = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        resp = client.post(
            '/api/transactions/import-csv/analyze',
            data={'file': (BytesIO(_BMO_FILE.encode('utf-8')), 'bmo.csv')},
            content_type='multipart/form-data',
        )

    print('Part B: HTTP status = %s' % resp.status_code)
    payload = resp.get_json() if resp.status_code == 200 else None
    if payload is None:
        print('Part B: FAIL — expected HTTP 200 + JSON')
        return False

    print('Part B: headers = %s' % (payload.get('headers'),))
    print('Part B: row_count = %s' % (payload.get('row_count'),))
    print('Part B: auto_mapping = %s' % (payload.get('auto_mapping'),))
    if payload.get('headers') != _BMO_HEADERS:
        print('Part B: FAIL — headers do not start at the real header line')
        ok = False
    if payload.get('row_count') != 1:
        print('Part B: FAIL — expected row_count == 1')
        ok = False
    mapping = payload.get('auto_mapping') or {}
    if mapping.get('Transaction Amount') != 'amount':
        print('Part B: FAIL — Transaction Amount did not map to amount')
        ok = False
    if mapping.get('Description') != 'description':
        print('Part B: FAIL — Description did not map to description')
        ok = False

    if ok:
        print('Part B: PASS (live analyze skipped the preamble)')
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
