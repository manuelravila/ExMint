# Bug: CSV Import 500 on a Row Whose Account Number Matches No Account

**Reported:** 2026-09-15
**Environment:** Production
**Severity:** High (whole import fails; user sees a JSON parse error)
**Status:** Fixed

---

## Symptom

Importing a CSV with an **Account Number** column mapped aborts with HTTP 500 as
soon as one row's account number matches none of the user's accounts. The browser
shows:

```
Unexpected token '<', "<!doctype "... is not valid JSON
```

because `static/js/vuePlaid.js` calls `await resp.json()` on the HTML error page.
The other, perfectly valid rows in the same CSV are never imported.

Production traceback:

```
File "/app/core_views.py", line 5396, in csv_import_execute
    db.session.commit()
sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush. Original exception was: (raised as a result of Query-invoked autoflush)
(pymysql.err.IntegrityError) (1048, "Column 'credential_id' cannot be null")
[SQL: INSERT INTO transactions (... credential_id, account_id, ...) VALUES (...)]
[parameters: {... 'account_id': None, 'credential_id': None, 'name': 'BMO MOSAIK MASTERCARD 24087118', 'amount': Decimal('-4580.00'), 'date': datetime.date(2026, 8, 28) ...}]
```

---

## Root Cause

Two defects in the row loop of `csv_import_execute` (`core_views.py`), mirrored
in the API route `api_csv_import_execute` (`api_views.py`):

### 1. No guard for an unroutable row

When `account_number` is mapped, the loop initializes the row target from the
form's `account_id` (absent when the CSV is expected to self-route) and the
default account's `credential_id` (absent when there is no default account):

```python
row_account_id = account_id
row_credential_id = credential_id
```

If the row's account number matches no account, `row_account_id` and
`row_credential_id` stay `None`, yet the loop still builds
`Transaction(account_id=None, credential_id=None)`. `transactions.credential_id`
is `NOT NULL`, so MySQL rejects the insert:

```
(pymysql.err.IntegrityError) (1048, "Column 'credential_id' cannot be null")
```

### 2. No session rollback in the per-row `except`

The per-row handler appended the error but did not roll the session back:

```python
except Exception as e:
    errors.append(f'Row {row_idx + 2}: {str(e)}')
    continue
```

A failed flush leaves the SQLAlchemy session in a "rollback pending" state, so
every later row fails and the final `db.session.commit()` raises
`PendingRollbackError`. This is why the traceback points at the final commit
(line 5396) instead of the offending row.

---

## Impact

- One bad row aborts the entire import (all-or-nothing failure visible to the user).
- The response is an HTML error page, not JSON, so the Vue UI reports a confusing
  `Unexpected token '<'` parse error rather than the real cause.
- The API v1 route (`api_csv_import_execute`) had a related credential leak: the
  `credential_id` variable was mutated per row and could carry over to a later row
  that fell back to `default_account`.

---

## Affected Files

Pre-fix line numbers (branch `dev`, version 1.8.1):

| File | Lines | Issue |
|---|---|---|
| `core_views.py` | 5197–5221 | `credential_id` default and inline mask index build |
| `core_views.py` | 5296–5316 | Inline lookup chain; no guard for an unmatched account |
| `core_views.py` | 5387–5389 | Per-row `except` appends error without `db.session.rollback()` |
| `core_views.py` | 5391 | Final `db.session.commit()` raises `PendingRollbackError` |
| `api_views.py` | 1437–1455 | `credential_id` default and inline mask index build |
| `api_views.py` | 1512–1537 | Inline lookup chain and unroutable guard |
| `api_views.py` | 1594–1596 | Per-row `except` without `db.session.rollback()` |
| `static/js/vuePlaid.js` | 3708–3712 | `await resp.json()` on a possible HTML error page |
| `templates/dashboard.html` | 1805–1827 | Fallback account selector hidden when `account_number` is mapped |
| `static/js/vuePlaid.js` | 3695–3701 | `account_id` only sent when `account_number` is not mapped |

---

## Fix applied

1. **New module `csv_import_routing.py`** — pure-stdlib routing helpers shared by
   both routes:
   - `normalize_account_key(value)` — whitespace/dash/asterisk normalization.
   - `build_mask_index(pairs)` — account-mask lookup index (raw, lstrip-zero,
     normalized variants).
   - `resolve_row_account(raw_account_number, mask_index)` — exact, last-4 and
     last-4-without-leading-zeros matching; returns `None` when unroutable.
   - `unroutable_reason(raw_account_number)` — a user-facing reason sentence.

2. **`core_views.py`** — the inline mask index/lookup was replaced with the shared
   helpers, and two guards were added before the dedup queries and insert:
   - `if not row_account_id:` → per-row error
     `"could not determine target account — account number 'X' matches none of your active accounts"` (or `"no account number in the row"`), then `continue`.
   - `if not row_credential_id:` → per-row error
     `"target account is not linked to a bank connection; row skipped"`, then `continue`.
   The per-row `except` now calls `db.session.rollback()` **before** appending the
   error, so a bad row can no longer poison the rest of the import or the final
   commit. The response shape (`inserted/skipped/updated/errors/total_errors`) is
   unchanged.

3. **`api_views.py`** — same shared helpers, the unroutable guard now uses
   `unroutable_reason()`, a per-row `row_credential_id` replaces the leaking
   variable, and `db.session.rollback()` was added to the per-row `except`. The
   `errors` list-of-dicts shape is unchanged.

4. **`static/js/vuePlaid.js`** — `executeCsvImport` parses the response body in a
   `try/catch`, checks `resp.ok` and shows a readable error (including the server's
   `data.error` when present) instead of throwing on an HTML body. `account_id` is
   now always sent when a fallback account is selected.

5. **`templates/dashboard.html`** — the destination-account selector is always
   shown; when an Account Number column is mapped it is labelled as an optional
   fallback ("Fallback account (used for rows whose account number doesn't
   match)").

6. **Regression test `test_csv_import_routing.py`** — Part A unit-tests the routing
   module (including the production `24087118` / `6845` mismatch). Part B is an
   opt-in live check (`EXMINT_LIVE_TEST=1`) that refuses to run against a
   non-`_dev_db` database and asserts the route returns HTTP 200, inserts 0 rows
   and reports a non-empty error list for an unmatched account number.

---

## Verification

- `./venv/bin/python test_csv_import_routing.py` — all Part A cases pass.
- `./venv/bin/python -m py_compile csv_import_routing.py core_views.py api_views.py` — clean.
- `node --check static/js/vuePlaid.js` — clean.
- `EXMINT_LIVE_TEST=1 FLASK_ENV=dev ./venv/bin/python test_csv_import_routing.py` —
  Part B reports HTTP 200 / 0 inserted / non-empty errors against the DEV database.

---

## Notes

- Unroutable rows are **rejected**, never imported under a wrong account. This is
  deliberate: an account number that matches no account must not silently land in
  the fallback account unless the user picked one.
- The fallback account remains optional. In v1.8.2, if the user selected one, an
  unmatched row routed there instead of erroring; see the follow-up below for how
  v1.9.0 auto-creation supersedes that for non-empty unmatched numbers.

---

## Follow-up (v1.9.0)

Unroutable rows can now be **auto-created** instead of only being rejected. When
the caller opts in (`create_missing_accounts=true`, exposed as the "Create
accounts that don't exist yet" checkbox in the CSV import dialog), a row whose
account number matches no active account creates a new `Account` under either:

- the institution explicitly chosen in the dialog (`new_account_credential_id`), or
- the one institution inferred from the other matched rows in the file.

If the file's matched rows span more than one institution and no institution was
chosen, the row is still reported as an error (the import never guesses). When
the caller does **not** opt in, the v1.8.2 behaviour is unchanged: an unmatched
row uses the selected fallback account when one was supplied, and is reported
only when no fallback was selected. A row with an empty account-number cell
continues to use the fallback account, and is never auto-created. Auto-created
accounts use the stable id `csv_acct_{credential_id}_{normalized number}` and a
secondary `(credential, mask)` lookup, so a second import of the same file
reuses the account rather than duplicating it. Plaid linking was also extended
to recognise a CSV-created account (same institution + mask with a `csv_acct_`
`plaid_account_id`) and re-parent it to the real Plaid account instead of
creating a duplicate.

