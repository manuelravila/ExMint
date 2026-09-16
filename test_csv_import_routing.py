#!/usr/bin/env python
"""test_csv_import_routing.py — regression tests for CSV import account routing.

Run from the repository root:

    ./venv/bin/python test_csv_import_routing.py

Part A always runs and needs no application or database: it unit-tests
``csv_import_routing``.

Part B is an opt-in live check against the DEV database. It only runs when
``EXMINT_LIVE_TEST=1`` is set, and hard-aborts if the app's database URI is not
a ``_dev_db`` database. It derives account numbers that are unroutable against
the live active-account masks (rather than hard-coding ones that happen to be
absent from a particular database) and checks the v1.9.0 auto-create contract:

  a. an unmatched number with ``create_missing_accounts=true`` is created under
     the institution inferred from the other rows and the row routes there, not
     to the fallback account;
  b. re-importing the same file creates no second account and dedupes the rows;
  c. with ``create_missing_accounts=false`` the v1.8.2 per-row error still fires
     (no fallback) and a supplied fallback account still routes the unmatched
     row exactly as v1.8.2 did — no account is created either way;
  d. the API v1 route shares the same auto-create code path;
  5. rows spanning two credentials plus an unmatched number create nothing and
     report that the institution could not be inferred (never guess).

Cleanup is mandatory: every transaction and account the tests created is
deleted and the counts are asserted back to zero.

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
    derive_mask,
    build_synthetic_external_id,
    resolve_creation_credential,
    creation_target_unknown_reason,
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

    # ── derive_mask (v1.9.0) ───────────────────────────────────────────────
    check(
        "derive_mask '05992-5006614' -> '6614'",
        derive_mask('05992-5006614') == '6614',
        repr(derive_mask('05992-5006614')),
    )
    check(
        "derive_mask '****6614' -> '6614'",
        derive_mask('****6614') == '6614',
        repr(derive_mask('****6614')),
    )
    check(
        "derive_mask ' 1234 ' -> '1234'",
        derive_mask(' 1234 ') == '1234',
        repr(derive_mask(' 1234 ')),
    )
    check(
        "derive_mask '123456789' -> '6789'",
        derive_mask('123456789') == '6789',
        repr(derive_mask('123456789')),
    )
    check(
        "derive_mask short value '123' -> '123'",
        derive_mask('123') == '123',
        repr(derive_mask('123')),
    )
    check(
        "derive_mask '12' -> '12'",
        derive_mask('12') == '12',
        repr(derive_mask('12')),
    )
    check("derive_mask None -> ''", derive_mask(None) == '', repr(derive_mask(None)))
    check("derive_mask '' -> ''", derive_mask('') == '', repr(derive_mask('')))
    check("derive_mask '   ' -> ''", derive_mask('   ') == '', repr(derive_mask('   ')))
    check(
        'derive_mask never longer than 4 chars',
        len(derive_mask('123456789012345')) == 4,
        repr(derive_mask('123456789012345')),
    )

    # ── build_synthetic_external_id (v1.9.0) ───────────────────────────────
    check(
        'synthetic external id uses csv_acct_ prefix and fits 100 chars',
        build_synthetic_external_id(7, '6614').startswith('csv_acct_7_')
        and len(build_synthetic_external_id(7, '6614')) <= 100,
        repr(build_synthetic_external_id(7, '6614')),
    )
    check(
        'synthetic external id is stable for the same inputs',
        build_synthetic_external_id(7, '6614')
        == build_synthetic_external_id(7, '6614'),
    )
    check(
        'synthetic external id is stable across formatting/whitespace',
        build_synthetic_external_id(7, '05992-5006614')
        == build_synthetic_external_id(7, ' 059925006614 '),
        '%r vs %r' % (
            build_synthetic_external_id(7, '05992-5006614'),
            build_synthetic_external_id(7, ' 059925006614 '),
        ),
    )
    check(
        'synthetic external id differs for a different credential',
        build_synthetic_external_id(7, '6614')
        != build_synthetic_external_id(8, '6614'),
    )
    check(
        'synthetic external id differs for a different number',
        build_synthetic_external_id(7, '6614')
        != build_synthetic_external_id(7, '6615'),
    )

    # ── resolve_creation_credential (never guess) ──────────────────────────
    check(
        'institution inferred when exactly one credential matched',
        resolve_creation_credential({5}, None) == 5,
    )
    check(
        'no institution when rows span two credentials (never guess)',
        resolve_creation_credential({5, 6}, None) is None,
    )
    check(
        'no institution when no row matched',
        resolve_creation_credential(set(), None) is None,
    )
    check(
        'no institution for None matched set',
        resolve_creation_credential(None, None) is None,
    )
    check(
        'explicit institution wins over inference',
        resolve_creation_credential({5}, 9) == 9,
    )
    check(
        'explicit institution wins over ambiguity',
        resolve_creation_credential({5, 6}, 9) == 9,
    )
    check(
        'explicit institution is honoured with no matched rows',
        resolve_creation_credential(set(), 9) == 9,
    )

    # ── creation_target_unknown_reason (never-guess row error) ─────────────
    check(
        'never-guess reason names the number and tells the user what to do',
        creation_target_unknown_reason('8765')
        == "could not determine target account — account number '8765' matches "
           "none of your active accounts, and no institution could be inferred "
           "for new accounts (rows in this file span multiple institutions); "
           "select the institution to create it under",
        repr(creation_target_unknown_reason('8765')),
    )
    check(
        'never-guess reason embeds the raw number',
        '1357' in creation_target_unknown_reason('1357'),
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

    from io import BytesIO

    _TAG = 'EXMINT-LIVE-v190'
    _MAPPING = {
        'Date': 'date',
        'Description': 'description',
        'Amount': 'amount',
        'Account Number': 'account_number',
    }
    ok = True

    def _login(client):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _post(client, csv_text, extra=None):
        data = {
            'file': (BytesIO(csv_text.encode('utf-8')), 'live_v190_check.csv'),
            'mapping': json.dumps(_MAPPING),
            'save_template': 'false',
        }
        if extra:
            data.update(extra)
        return client.post(
            '/api/transactions/import-csv/import',
            data=data,
            content_type='multipart/form-data',
        )

    def _json(resp):
        try:
            payload = resp.get_json()
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None

    def _cleanup(sentinels):
        """Delete every row these tests created; return (txns, accounts)."""
        with app.app_context():
            txns = Transaction.query.filter(
                Transaction.user_id == user_id,
                Transaction.name.like(_TAG + '%'),
            ).all()
            for txn in txns:
                db.session.delete(txn)
            db.session.commit()

            creds = Credential.query.filter_by(user_id=user_id).all()
            synth_ids = [
                build_synthetic_external_id(c.id, s)
                for c in creds for s in sentinels
            ]
            accts = []
            if synth_ids:
                accts = Account.query.filter(
                    Account.plaid_account_id.in_(synth_ids)
                ).all()
            for acct in accts:
                Transaction.query.filter_by(account_id=acct.id).delete(
                    synchronize_session=False
                )
                db.session.delete(acct)
            db.session.commit()
            return len(txns), len(accts)

    with app.app_context():
        user = User.query.first()
        if user is None:
            print('Part B: ABORT — no User rows found in the dev database')
            return False
        user_id = user.id

        _active = Account.query.join(Credential).filter(
            Credential.user_id == user_id,
            Account.status == 'Active',
        ).all()
        if not _active:
            print('Part B: ABORT — user %s has no active accounts' % user_id)
            return False
        _idx = build_mask_index((a.id, a.mask) for a in _active)
        _all_masks = {
            str(a.mask)
            for a in Account.query.join(Credential).filter(
                Credential.user_id == user_id
            ).all()
            if a.mask
        }

        # Derive sentinels that resolve to nothing and whose mask is unused, so
        # the assertions never depend on one database's fixture masks.
        _sentinels = []
        for _cand in (
            '4321', '8765', '1357', '2468', '1122', '3344', '5566', '7788',
            '9900', '0987', '7654', '5432', '2109', '6789', '3456', '7890',
            '2345', '9876', '1234', '5678',
        ):
            if resolve_row_account(_cand, _idx) is None and _cand not in _all_masks:
                _sentinels.append(_cand)
            if len(_sentinels) >= 4:
                break
        if len(_sentinels) < 4:
            print(
                'Part B: ABORT — could not derive 4 unused unroutable sentinels '
                'for this database.'
            )
            return False
        _sent_a, _sent_b, _sent_c, _sent_d = _sentinels[:4]
        print('Part B: sentinels a=%s b=%s c=%s d=%s'
              % (_sent_a, _sent_b, _sent_c, _sent_d))

        # For institution inference we need account numbers that actually
        # resolve through the live mask index. Group the resolved accounts by
        # credential and keep a representative (mask, account) per credential.
        _by_id = {a.id: a for a in _active}
        _reachable = {}  # credential_id -> (mask, resolved account)
        for _a in _active:
            if not _a.mask:
                continue
            _tid = resolve_row_account(_a.mask, _idx)
            _tacct = _by_id.get(_tid) if _tid is not None else None
            if _tacct is not None:
                _reachable.setdefault(_tacct.credential_id, (_a.mask, _tacct))
        if not _reachable:
            print(
                'Part B: ABORT — no active-account mask resolves against the live '
                'mask index, cannot test institution inference.'
            )
            return False
        _win_a_mask, _win_a = next(iter(_reachable.values()))
        # The never-guess case needs two live credentials in one file. In this
        # DB every mask resolves to one credential, but an empty account-number
        # cell routes to the fallback account, which may belong to a different
        # institution. Pick such a fallback for case (5).
        _other = next(
            (a for a in _active if a.credential_id != _win_a.credential_id),
            None,
        )
        if _other is None:
            print(
                'Part B: NOTE — this dev DB has only one active credential, so '
                'the never-guess case (5) cannot be constructed live and is '
                'reported rather than faked.'
            )

    # Start from a clean slate (clears anything a previous failed run left).
    _pre_t, _pre_a = _cleanup(_sentinels)
    if _pre_t or _pre_a:
        print(
            'Part B: pre-clean removed %d leftover transaction(s) and %d '
            'account(s) from an earlier run' % (_pre_t, _pre_a)
        )

    # ── Case a: unmatched number auto-created under the inferred institution ─
    _csv_a = (
        'Date,Description,Amount,Account Number\n'
        '2026-09-15,%s matched,-1.00,%s\n'
        '2026-09-15,%s auto1,-2.00,%s\n'
        % (_TAG, _win_a_mask, _TAG, _sent_a)
    )
    with app.test_client() as client:
        _login(client)
        _resp_a = _post(client, _csv_a, {
            'account_id': str(_win_a.id),
            'create_missing_accounts': 'true',
        })
    _payload_a = _json(_resp_a)
    print('Part B (a): HTTP status = %s' % _resp_a.status_code)
    if _resp_a.status_code != 200 or _payload_a is None:
        print('Part B (a): FAIL — expected HTTP 200 + JSON, got %s' % _resp_a.status_code)
        ok = False
    else:
        print('Part B (a): inserted=%s errors=%s created_accounts=%s'
              % (_payload_a.get('inserted'), _payload_a.get('errors'),
                 _payload_a.get('created_accounts')))
        if _payload_a.get('inserted') != 2:
            print('Part B (a): FAIL — expected inserted == 2')
            ok = False
        if _payload_a.get('errors'):
            print('Part B (a): FAIL — expected no errors')
            ok = False
        _created = _payload_a.get('created_accounts') or []
        if len(_created) != 1:
            print('Part B (a): FAIL — expected exactly 1 created account')
            ok = False
        elif (_created[0].get('mask') != derive_mask(_sent_a)
              or _created[0].get('credential_id') != _win_a.credential_id):
            print('Part B (a): FAIL — created account has wrong mask/credential: %s'
                  % _created[0])
            ok = False

        with app.app_context():
            _synth_a = build_synthetic_external_id(_win_a.credential_id, _sent_a)
            _new_acct = Account.query.filter_by(plaid_account_id=_synth_a).first()
            if _new_acct is None:
                print('Part B (a): FAIL — auto-created account row not found')
                ok = False
            else:
                print('Part B (a): new account id=%s mask=%s credential=%s name=%r'
                      % (_new_acct.id, _new_acct.mask, _new_acct.credential_id,
                         _new_acct.name))
                if _new_acct.mask != derive_mask(_sent_a):
                    print('Part B (a): FAIL — derived mask mismatch')
                    ok = False
                _auto_txn = Transaction.query.filter_by(
                    user_id=user_id, name=_TAG + ' auto1'
                ).first()
                _matched_txn = Transaction.query.filter_by(
                    user_id=user_id, name=_TAG + ' matched'
                ).first()
                if (_auto_txn is None or _auto_txn.account_id != _new_acct.id):
                    print('Part B (a): FAIL — unmatched row not routed to new account')
                    ok = False
                if (_matched_txn is None or _matched_txn.account_id != _win_a.id):
                    print('Part B (a): FAIL — matched row not routed to existing account')
                    ok = False

    # ── Case b: re-import is idempotent ──────────────────────────────────────
    with app.test_client() as client:
        _login(client)
        _resp_b = _post(client, _csv_a, {
            'account_id': str(_win_a.id),
            'create_missing_accounts': 'true',
        })
    _payload_b = _json(_resp_b)
    print('Part B (b): HTTP status = %s' % _resp_b.status_code)
    if _resp_b.status_code != 200 or _payload_b is None:
        print('Part B (b): FAIL — expected HTTP 200 + JSON')
        ok = False
    else:
        print('Part B (b): inserted=%s skipped=%s created_accounts=%s'
              % (_payload_b.get('inserted'), _payload_b.get('skipped'),
                 _payload_b.get('created_accounts')))
        if _payload_b.get('inserted') != 0:
            print('Part B (b): FAIL — second import inserted rows')
            ok = False
        if _payload_b.get('skipped') != 2:
            print('Part B (b): FAIL — expected skipped == 2')
            ok = False
        if _payload_b.get('created_accounts'):
            print('Part B (b): FAIL — second import created an account')
            ok = False
        with app.app_context():
            _count_a = Account.query.filter_by(
                plaid_account_id=build_synthetic_external_id(
                    _win_a.credential_id, _sent_a
                )
            ).count()
            if _count_a != 1:
                print('Part B (b): FAIL — expected exactly one synthetic account, '
                      'got %d' % _count_a)
                ok = False

    # ── Case (api): API v1 route shares the same code path ───────────────────
    _csv_api = (
        'Date,Description,Amount,Account Number\n'
        '2026-09-15,%s api-matched,-7.00,%s\n'
        '2026-09-15,%s api-auto,-8.00,%s\n'
        % (_TAG, _win_a_mask, _TAG, _sent_d)
    )
    with app.test_client() as client:
        _login(client)
        _resp_api = client.post(
            '/api/v1/transactions/import-csv/import',
            json={
                'csv_content': _csv_api,
                'mapping': _MAPPING,
                'account_id': _win_a.id,
                'create_missing_accounts': True,
            },
        )
    _payload_api = _json(_resp_api)
    print('Part B (api): HTTP status = %s' % _resp_api.status_code)
    if _resp_api.status_code != 200 or _payload_api is None:
        print('Part B (api): FAIL — expected HTTP 200 + JSON')
        ok = False
    else:
        _created_api = _payload_api.get('created_accounts') or []
        print('Part B (api): inserted=%s created_accounts=%s'
              % (_payload_api.get('inserted'), _created_api))
        if _payload_api.get('inserted') != 2 or len(_created_api) != 1:
            print('Part B (api): FAIL — expected inserted==2 and 1 created account')
            ok = False
        elif _created_api[0].get('mask') != derive_mask(_sent_d):
            print('Part B (api): FAIL — created account has the wrong mask')
            ok = False
        with app.app_context():
            _new_api = Account.query.filter_by(
                plaid_account_id=build_synthetic_external_id(
                    _win_a.credential_id, _sent_d
                )
            ).first()
            _api_auto = Transaction.query.filter_by(
                user_id=user_id, name=_TAG + ' api-auto'
            ).first()
            if (_new_api is None or _api_auto is None
                    or _api_auto.account_id != _new_api.id):
                print('Part B (api): FAIL — API route did not auto-create/route the row')
                ok = False

    # ── Case c: opt-out keeps the v1.8.2 per-row error ───────────────────────
    _csv_c = (
        'Date,Description,Amount,Account Number\n'
        '2026-09-15,%s unmatched-off,-3.00,%s\n'
        % (_TAG, _sent_c)
    )
    with app.test_client() as client:
        _login(client)
        _resp_c = _post(client, _csv_c, {'create_missing_accounts': 'false'})
    _payload_c = _json(_resp_c)
    print('Part B (c): HTTP status = %s' % _resp_c.status_code)
    if _resp_c.status_code != 200 or _payload_c is None:
        print('Part B (c): FAIL — expected HTTP 200 + JSON')
        ok = False
    else:
        print('Part B (c): inserted=%s errors=%s'
              % (_payload_c.get('inserted'), _payload_c.get('errors')))
        if _payload_c.get('inserted') != 0:
            print('Part B (c): FAIL — opt-out imported a row')
            ok = False
        _errs_c = _payload_c.get('errors') or []
        if not any(_sent_c in str(e) for e in _errs_c):
            print('Part B (c): FAIL — error does not name %s' % _sent_c)
            ok = False
        with app.app_context():
            _leak = Transaction.query.filter_by(
                user_id=user_id, name=_TAG + ' unmatched-off'
            ).count()
            _accts_c = Account.query.join(Credential).filter(
                Credential.user_id == user_id,
                Account.plaid_account_id.like('csv_acct_%'),
                Account.mask == _sent_c,
            ).count()
            if _leak != 0:
                print('Part B (c): FAIL — opt-out row persisted')
                ok = False
            if _accts_c != 0:
                print('Part B (c): FAIL — opt-out created an account')
                ok = False

    # ── Case (c2): opt-out + fallback keeps the v1.8.2 fallback routing ──────
    _csv_c2 = (
        'Date,Description,Amount,Account Number\n'
        '2026-09-15,%s unmatched-fallback,-3.50,%s\n'
        % (_TAG, _sent_c)
    )
    with app.test_client() as client:
        _login(client)
        _resp_c2 = _post(client, _csv_c2, {
            'account_id': str(_win_a.id),
            'create_missing_accounts': 'false',
        })
    _payload_c2 = _json(_resp_c2)
    print('Part B (c2): HTTP status = %s' % _resp_c2.status_code)
    if _resp_c2.status_code != 200 or _payload_c2 is None:
        print('Part B (c2): FAIL — expected HTTP 200 + JSON')
        ok = False
    else:
        print('Part B (c2): inserted=%s errors=%s created_accounts=%s'
              % (_payload_c2.get('inserted'), _payload_c2.get('errors'),
                 _payload_c2.get('created_accounts')))
        if _payload_c2.get('inserted') != 1 or _payload_c2.get('errors'):
            print('Part B (c2): FAIL — expected the unmatched row to import via fallback')
            ok = False
        if _payload_c2.get('created_accounts'):
            print('Part B (c2): FAIL — opt-out created an account')
            ok = False
        with app.app_context():
            _fb = Transaction.query.filter_by(
                user_id=user_id, name=_TAG + ' unmatched-fallback'
            ).first()
            if _fb is None or _fb.account_id != _win_a.id:
                print('Part B (c2): FAIL — fallback routing regressed (v1.8.2)')
                ok = False
            _accts_c2 = Account.query.join(Credential).filter(
                Credential.user_id == user_id,
                Account.plaid_account_id.like('csv_acct_%'),
                Account.mask == _sent_c,
            ).count()
            if _accts_c2 != 0:
                print('Part B (c2): FAIL — opt-out created an account')
                ok = False

    # ── Case 5: never-guess when the file spans two institutions ─────────────
    if _other is not None:
        _csv_e = (
            'Date,Description,Amount,Account Number\n'
            '2026-09-15,%s multi-matched,-4.00,%s\n'
            '2026-09-15,%s multi-fallback,-5.00,\n'
            '2026-09-15,%s unmatched-multi,-6.00,%s\n'
            % (_TAG, _win_a_mask, _TAG, _TAG, _sent_b)
        )
        with app.test_client() as client:
            _login(client)
            _resp_e = _post(client, _csv_e, {
                'account_id': str(_other.id),
                'create_missing_accounts': 'true',
            })
        _payload_e = _json(_resp_e)
        print('Part B (5): HTTP status = %s' % _resp_e.status_code)
        print('Part B (5): matched credential=%s, fallback credential=%s'
              % (_win_a.credential_id, _other.credential_id))
        if _resp_e.status_code != 200 or _payload_e is None:
            print('Part B (5): FAIL — expected HTTP 200 + JSON')
            ok = False
        else:
            print('Part B (5): inserted=%s created_accounts=%s errors=%s'
                  % (_payload_e.get('inserted'),
                     _payload_e.get('created_accounts'), _payload_e.get('errors')))
            if (_win_a.credential_id == _other.credential_id):
                print('Part B (5): FAIL — the two credentials are not distinct')
                ok = False
            if _payload_e.get('created_accounts'):
                print('Part B (5): FAIL — import guessed an institution and '
                      'created an account')
                ok = False
            _errs_e = _payload_e.get('errors') or []
            if not any(_sent_b in str(e) for e in _errs_e):
                print('Part B (5): FAIL — error does not name %s' % _sent_b)
                ok = False
            if not any('inferred' in str(e).lower() for e in _errs_e):
                print('Part B (5): FAIL — error does not explain the missing institution')
                ok = False
            with app.app_context():
                _accts_e = Account.query.join(Credential).filter(
                    Credential.user_id == user_id,
                    Account.plaid_account_id.like('csv_acct_%'),
                    Account.mask == _sent_b,
                ).count()
                if _accts_e != 0:
                    print('Part B (5): FAIL — an account was created despite ambiguity')
                    ok = False
                # The empty-cell fallback row really does route to _other.
                _fb_txn = Transaction.query.filter_by(
                    user_id=user_id, name=_TAG + ' multi-fallback'
                ).first()
                if _fb_txn is None or _fb_txn.account_id != _other.id:
                    print('Part B (5): FAIL — fallback row did not route to _other')
                    ok = False
    else:
        print(
            'Part B (5): SKIP — the dev DB has only one active credential; the '
            'never-guess case cannot be constructed live and is reported rather '
            'than faked. (The never-guess decision itself is covered by the '
            'Part A resolve_creation_credential cases.)'
        )

    # ── Mandatory cleanup ────────────────────────────────────────────────────
    _del_t, _del_a = _cleanup(_sentinels)
    print('Part B: cleanup deleted %d transaction(s) and %d account(s)'
          % (_del_t, _del_a))
    with app.app_context():
        _left_t = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.name.like(_TAG + '%'),
        ).count()
        _creds = Credential.query.filter_by(user_id=user_id).all()
        _synths = [
            build_synthetic_external_id(c.id, s)
            for c in _creds for s in _sentinels
        ]
        _left_a = 0
        if _synths:
            _left_a = Account.query.filter(
                Account.plaid_account_id.in_(_synths)
            ).count()
    print('Part B: leftover test transactions = %d (expected 0)' % _left_t)
    print('Part B: leftover test accounts = %d (expected 0)' % _left_a)
    if _left_t != 0 or _left_a != 0:
        print('Part B: FAIL — cleanup did not restore the dev database')
        ok = False

    if ok:
        print('Part B: PASS (auto-create a, idempotency b, api d, opt-out c/c2, never-guess 5)')
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
