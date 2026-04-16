# Bug: Multiple Credentials for the Same Institution — Account & Sync Issues

**Reported:** 2026-04-15
**Environment:** Production
**Severity:** Medium (data integrity risk post-reconnection)
**Status:** Partially fixed (v1.3.4)

---

## Symptom

User has two separate Plaid credentials for Scotiabank. The second credential is flagged
with a "Reconnect" button. After syncing, the first credential (not flagged) reports
0 new transactions. The second credential can never meaningfully sync.

---

## Root Cause

ExMint's account setup logic assumes **one Plaid item per institution per user**. When a
second credential is added for the same institution:

### 1. Accounts are de-duplicated at the institution level (`core_views.py:1722–1737`)

During `POST /api/plaid/set_access_token`, when accounts are linked for the new credential,
a secondary match runs:

```python
existing_account = (
    Account.query.join(Credential)
    .filter(
        Credential.user_id == current_user.id,
        Credential.institution_name == credential.institution_name,
        Account.mask == mask,
        Account.name == name,
    ).first()
)
if existing_account and existing_account.status == 'Active':
    logger.warning('Skipping duplicate active account ...')
```

If the physical accounts at the bank are the same (same mask + name at same institution),
**no Account rows are created for the second credential**. The second credential ends up
with zero accounts in its `credential.accounts` relationship.

### 2. Sync cross-assigns transactions (`core_views.py:1868–1882`)

In `_persist_transactions_from_payload()`:

```python
account_map = {account.plaid_account_id: account for account in credential.accounts}
# ... credential.accounts is EMPTY for second credential ...

missing_account_ids = incoming_account_ids.difference(account_map.keys())
if missing_account_ids:
    fetched_accounts = Account.query.filter(
        Account.plaid_account_id.in_(missing_account_ids)
    ).all()   # <-- No credential/user filter — finds first credential's accounts
    account_map.update(...)
```

When the second credential syncs after reconnection, all Plaid account IDs appear
"missing", the query finds the **first credential's Account rows** (same `plaid_account_id`),
and transactions are persisted with `credential_id` = second credential but
`account_id` = first credential's accounts. This is a cross-credential FK mismatch.

---

## Observed Behavior vs Expected

| Behavior | Observed | Expected |
|---|---|---|
| Reconnect button | Correct — shown only on second credential | ✓ |
| 0 transactions from first credential | Correct — cursor is current | ✓ |
| Second credential has no accounts | Yes — skipped as duplicates | Accounts should be linked or shared |
| Transactions after reconnect | Cross-assigned to first credential's accounts | Should be properly associated |

---

## Impact

- The second credential is effectively non-functional for syncing until reconnected.
- After reconnection, transactions will persist with mismatched `credential_id` /
  `account_id` FKs. In practice, transactions may still appear correctly in the UI
  (because `account_id` points to a valid account the user owns), but the data model
  is inconsistent.
- This affects any user with two Plaid connections to the same institution where the
  underlying accounts share the same mask + name.

---

## Affected Files

| File | Lines | Issue |
|---|---|---|
| `core_views.py` | 1722–1737 | Account de-dup skips accounts for second credential |
| `core_views.py` | 1868–1882 | `missing_account_ids` lookup has no credential scope |

---

## Possible Fix Approaches

**Option A (minimal):** In `_persist_transactions_from_payload`, add
`Credential.user_id == user.id` to the fallback account query. This prevents
cross-user contamination but doesn't fix the same-user cross-credential FK mismatch.

**Option B (proper):** When a second credential at the same institution is added,
re-parent the existing Account rows to the new credential (or introduce a
many-to-many between Account and Credential). This is a larger model change.

**Option C (UX guard):** When the duplicate guard fires during account linking, return
a 409 to the UI and inform the user that these accounts are already connected via
another credential, preventing the second credential from being saved at all.

---

## v1.3.4 Partial Fix

Two issues were fixed that made this bug worse in practice:

1. **Recurring duplicates after dedup (fixed):** `_persist_transactions_from_payload`
   previously set `is_removed = False` unconditionally for every `added`/`modified`
   payload. This meant any transaction removed by the dedup tool would be silently
   revived the next time Plaid sent a `modified` update for it (e.g. pending→posted).
   Fixed by skipping transactions whose `last_action` is `maintenance_dedup` or
   `maintenance_dedup_cascade`.

2. **Fallback account query not user-scoped (fixed):** The fallback query that resolves
   unknown Plaid account IDs now joins through `Credential` and filters by `user_id`.

The underlying account-mapping and FK-mismatch issue (Options A/B/C) is still open.

---

## Notes

- The reconnect flag (`requires_update`) is tracked correctly per-credential — this is
  not a bug.  If `requires_update=True` clears after a manual sync, it means Plaid's
  token is actually valid again (the auth issue was transient on Plaid's side).
- The 0 transactions shown on the first connection is expected (cursor is current).
- The true risk window is: second credential reconnected → sync runs → data mismatch
  written to DB. Monitor logs for the warning:
  `'Skipping duplicate active account mask=...'`
