"""csv_import_routing.py — Pure-stdlib helpers for routing CSV import rows.

When a CSV contains an account-number column, each row must be routed to one
of the user's active accounts before a transaction can be built. The routing
contract is:

  * The CSV account number is normalized (whitespace, dashes and asterisks
    removed) and looked up against an index of the user's active account
    masks. Exact matches win; then the last four digits; then the last four
    digits without leading zeros.
  * A row whose account number matches no account is *unroutable*. Such a row
    MUST be rejected (reported as a per-row error) rather than imported with a
    ``NULL`` account. ``transactions.credential_id`` is NOT NULL in the
    database, so inserting an unroutable row would fail at flush time and, with
    no rollback, poison the whole import session.

This module deliberately has no Flask/SQLAlchemy imports so its matching
semantics can be unit-tested without an application or database.
"""


def normalize_account_key(value) -> str:
    """Normalize an account number/mask for lookup.

    Strips surrounding whitespace, then removes spaces, dashes (``-``) and
    asterisks (``*``). Returns ``''`` for ``None`` or an empty value.
    """
    if value is None:
        return ''
    return (
        str(value)
        .strip()
        .replace(' ', '')
        .replace('-', '')
        .replace('*', '')
    )


def build_mask_index(pairs) -> dict:
    """Build a ``{key: account_id}`` index from ``(account_id, mask)`` pairs.

    Empty/``None`` masks are skipped. For each mask the following keys are
    added: the raw mask, ``mask.lstrip('0')``, the normalized mask and
    ``normalize_account_key(mask).lstrip('0')``. Empty keys are skipped.
    Later entries win on collision (matching the legacy dict build).
    """
    index = {}
    for account_id, mask in pairs:
        if mask is None or mask == '':
            continue
        mask = str(mask)
        normalized = normalize_account_key(mask)
        for key in (
            mask,
            mask.lstrip('0'),
            normalized,
            normalized.lstrip('0'),
        ):
            if key:
                index[key] = account_id
    return index


def resolve_row_account(raw_account_number, mask_index) -> int:
    """Resolve a CSV account number to an account id, or ``None``.

    Normalizes the value, tries an exact lookup, then (only when the key is at
    least 4 characters) the last 4 characters, then those last 4 characters
    with leading zeros stripped. This mirrors the legacy inline matching
    semantics exactly — no fuzzy matching is invented.
    """
    key = normalize_account_key(raw_account_number)
    if not key:
        return None

    matched = mask_index.get(key)
    if matched is not None:
        return matched

    if len(key) >= 4:
        last4 = key[-4:]
        matched = mask_index.get(last4)
        if matched is not None:
            return matched
        matched = mask_index.get(last4.lstrip('0'))
        if matched is not None:
            return matched

    return None


def unroutable_reason(raw_account_number) -> str:
    """Return the human-readable reason a row could not be routed.

    The returned sentence has no ``Row N`` prefix; callers add that. When a
    value is present it is named so the user can find the offending row.
    """
    if raw_account_number is None or str(raw_account_number).strip() == '':
        return 'no account number in the row'
    return "account number '%s' matches none of your active accounts" % raw_account_number


def derive_mask(raw_account_number) -> str:
    """Return the account mask (last 4 digits) of a normalized account number.

    ``'05992-5006614'`` and ``'****6614'`` both yield ``'6614'``. Returns
    ``''`` for ``None``/empty values and the whole normalized value when it is
    shorter than four characters.
    """
    key = normalize_account_key(raw_account_number)
    if not key:
        return ''
    return key[-4:]


def build_synthetic_external_id(credential_id, raw_account_number) -> str:
    """Build the stable synthetic ``plaid_account_id`` for a CSV-created account.

    Format: ``csv_acct_{credential_id}_{normalized account number}``. The same
    inputs always produce the same id, so re-importing a file (or importing a
    differently formatted version of the same number) reuses the account rather
    than creating a duplicate.
    """
    return 'csv_acct_%s_%s' % (credential_id, normalize_account_key(raw_account_number))


def resolve_creation_credential(matched_credential_ids, explicit_credential_id):
    """Decide which credential a new account should be created under.

    An explicit selection always wins. Otherwise, when every matched row
    belongs to exactly one credential, that credential is inferred. In every
    other case (no matched rows, or rows spanning several credentials) this
    returns ``None`` — the import must ask the user, never guess.
    """
    if explicit_credential_id is not None:
        return explicit_credential_id
    unique = set(matched_credential_ids or [])
    if len(unique) == 1:
        return next(iter(unique))
    return None


def creation_target_unknown_reason(raw_account_number) -> str:
    """Row error when auto-create is on but no institution could be determined.

    The sentence has no ``Row N`` prefix; callers add that. It deliberately
    explains *why* nothing was created and what the user must do next, so the
    never-guess rule is visible in the UI.
    """
    return (
        "could not determine target account — account number '%s' matches none "
        "of your active accounts, and no institution could be inferred for new "
        "accounts (rows in this file span multiple institutions); select the "
        "institution to create it under" % raw_account_number
    )
