#!/usr/bin/env python3
"""
Undo the damage a CSV "Account Type" column did to categories.

A bank export carries account labels in its own columns — "Account Type",
"Account Type Description", "Product Name" — and their values are things like
Chequing or Royal Credit Line. Until those columns were blocked from feeding the
category field, an import could store them as the category of a purchase: the row
gains a category the user never created, and the category list fills up with bank
account names.

This script finds that leftover state and puts it back:

  * rows whose stored category is an account label (it reads as a bank account
    type, or it is the row's own account name / mask / type / institution) — the
    category is cleared, which makes the row Uncategorized;
  * categories that are themselves an account label — unlinked from the rows that
    point at them (including manual overrides), and deleted when nothing still
    uses them;
  * saved CSV templates that still map an account-describing column to Category —
    rewritten with the same rule the importer now applies, so the next import of
    that file cannot reintroduce the problem.

Dry run by default: nothing is written and the script prints what it would change.
Pass --apply to write.  It refuses to run against anything but the dev database,
so a production fix goes through the API instead, after Manuel says go.

    ./venv/bin/python fix_csv_category_columns.py            # report only
    ./venv/bin/python fix_csv_category_columns.py --apply    # actually fix
"""
import argparse
import json
import sys


def _is_account_label_text(text, account=None, credential_name=None):
    """True when a stored category value is really an account label.

    Either it reads as a bank account type (Chequing, Savings, Royal Credit Line,
    Visa...) — the same patterns the importer uses to type an account — or it is
    simply the row's own account named a different way.
    """
    from core_views import _csv_account_type_from_text

    cleaned = (text or '').strip()
    if not cleaned:
        return False
    if _csv_account_type_from_text(cleaned)[0] is not None:
        return True
    if account is None:
        return False
    own = {account.name, account.mask, account.type, account.subtype, credential_name}
    own = {(v or '').strip().lower() for v in own if v}
    return cleaned.lower() in own


def _csv_stored_category(raw):
    """True when ``Transaction.category`` holds one plain CSV string.

    Plaid writes a JSON list ('["Food and Drink","Restaurants"]') or 'null'; a CSV
    import writes the cell verbatim. Only the plain string can be an account label
    that came out of a column, so anything JSON-shaped is left alone.
    """
    if raw is None:
        return False
    if isinstance(raw, list):
        return False
    text = str(raw).strip()
    if not text or text in ('null', 'None') or text.startswith('['):
        return False
    return True


def _csv_fingerprint(txn):
    """True when the row looks like it was written by a CSV import.

    A synced row carries a JSON list in ``category`` and a real Plaid id; a CSV row
    carries the cell verbatim and a ``csv_`` id. Only those are cleanup candidates:
    a row a category rule placed deliberately is never touched, even when its
    category happens to be named like a bank account.
    """
    if _csv_stored_category(txn.category):
        return True
    return (txn.plaid_transaction_id or '').startswith('csv_')


def _candidate_rows(db, Transaction, Account, Credential):
    """Rows whose category is an account label stored by a CSV import."""
    rows = (
        db.session.query(Transaction, Account, Credential)
        .join(Account, Transaction.account_id == Account.id)
        .outerjoin(Credential, Account.credential_id == Credential.id)
        .filter(Transaction.is_removed.is_(False), Transaction.category.isnot(None))
        .all()
    )
    found = []
    for txn, account, credential in rows:
        if not _csv_stored_category(txn.category):
            continue
        institution_name = credential.institution_name if credential else None
        if _is_account_label_text(txn.category, account, institution_name):
            found.append((txn, account, str(txn.category).strip()))
    return found


def _account_label_categories(db, CustomCategory):
    """Categories whose own name is a bank account label."""
    from core_views import _csv_account_type_from_text

    out = []
    for category in CustomCategory.query.all():
        name = (category.name or '').strip()
        if not name:
            continue
        if _csv_account_type_from_text(name)[0] is not None:
            out.append(category)
    return out


def _unused_category_ids(db, CustomCategory, Transaction, CategoryRule,
                         TransactionCategoryOverride, keep):
    """Categories of ``keep`` that no rule, row or override still points at.

    A category with a rule is never listed: the rule is proof the user created it
    on purpose, even when its name reads like a bank account.
    """
    ids = [c.id for c in keep]
    if not ids:
        return []
    used = set()
    for model, column in ((CategoryRule, CategoryRule.category_id),
                          (Transaction, Transaction.custom_category_id),
                          (TransactionCategoryOverride, TransactionCategoryOverride.custom_category_id)):
        used.update(row[0] for row in db.session.query(column).filter(
            column.in_(ids)).all())
    return [i for i in ids if i not in used]


def _leftover_damage_categories(db, CustomCategory, Transaction, CategoryRule,
                                TransactionCategoryOverride):
    """Account-label categories still sitting on CSV-written rows.

    A category with a rule behind it is not leftover damage: the rule is proof the
    user named it on purpose, and counting it here would call clean data a failure.
    """
    out = []
    for category in _account_label_categories(db, CustomCategory):
        if CategoryRule.query.filter_by(category_id=category.id).count():
            continue
        if any(_csv_fingerprint(txn) for txn in
               Transaction.query.filter_by(custom_category_id=category.id).all()):
            out.append(category)
    return out


def _templates_needing_fix(db, CsvImportTemplate, guard_category_mapping):
    """Saved templates whose mapping still sends an account column to Category."""
    broken = []
    for template in CsvImportTemplate.query.all():
        try:
            mappings = json.loads(template.mappings)
        except (TypeError, ValueError):
            continue
        if not isinstance(mappings, dict):
            continue
        fixed, notes = guard_category_mapping(mappings)
        if notes and fixed != mappings:
            broken.append((template, fixed, notes))
    return broken


def main():
    parser = argparse.ArgumentParser(
        description='Report (or with --apply, undo) account labels stored as categories '
                    'by CSV imports. Dry run unless --apply is given.')
    parser.add_argument('--apply', action='store_true',
                        help='write the fixes; without it the script only reports')
    parser.add_argument('--limit', type=int, default=40,
                        help='how many rows to list individually (default 40)')
    args = parser.parse_args()

    from app import create_app
    from models import (db, Transaction, Account, Credential, CustomCategory,
                        CategoryRule, TransactionCategoryOverride, CsvImportTemplate)
    from csv_import_routing import guard_category_mapping

    app = create_app()
    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('Refusing to run: the configured database is not the dev database (%s).'
              % uri.split('@', 1)[-1], file=sys.stderr)
        print('PROD cleanup goes through the API after Manuel approves it.', file=sys.stderr)
        return 2

    print('Database: %s' % uri.split('@', 1)[-1])
    print('Mode: %s' % ('APPLY — rows will be written' if args.apply else 'dry run — nothing is written'))

    with app.app_context():
        rows = _candidate_rows(db, Transaction, Account, Credential)
        print('\n1) Rows whose category is an account label: %d' % len(rows))
        for txn, account, label in rows[:args.limit]:
            print('   txn #%s  %s  %s  %s  account "%s"%s  category=%r'
                  % (txn.id, txn.date, txn.amount, txn.name, account.name,
                     (' ••••%s' % account.mask) if account.mask else '', label))
        if len(rows) > args.limit:
            print('   … and %d more.' % (len(rows) - args.limit))

        categories = _account_label_categories(db, CustomCategory)
        linked = [c for c in categories
                  if Transaction.query.filter_by(custom_category_id=c.id).count()
                  or TransactionCategoryOverride.query.filter_by(custom_category_id=c.id).count()]
        print('\n2) Categories that are account labels: %d (%d still used by rows/overrides)'
              % (len(categories), len(linked)))
        for category in categories:
            print('   category #%s  %r  (user %s, %d transaction(s))'
                  % (category.id, category.name, category.user_id,
                     Transaction.query.filter_by(custom_category_id=category.id).count()))

        templates = _templates_needing_fix(db, CsvImportTemplate, guard_category_mapping)
        print('\n3) Saved CSV templates mapping an account column to Category: %d' % len(templates))
        for template, _fixed, notes in templates:
            print('   template #%s %r (user %s): %s'
                  % (template.id, template.label, template.user_id, notes[0]))

        if not args.apply:
            print('\nDry run complete. Re-run with --apply to write these fixes.')
            return 0

        cleared = 0
        removed_overrides = 0
        for txn, _account, label in rows:
            txn.category = None
            txn.custom_category_id = None
            override = TransactionCategoryOverride.query.filter_by(transaction_id=txn.id).first()
            if override:
                db.session.delete(override)
                removed_overrides += 1
            cleared += 1

        for category in categories:
            for override in TransactionCategoryOverride.query.filter_by(
                    custom_category_id=category.id).all():
                txn = Transaction.query.get(override.transaction_id)
                if txn is None or not _csv_fingerprint(txn):
                    continue  # a hand-placed override is the user's, not the import's
                db.session.delete(override)
                removed_overrides += 1
            for txn in Transaction.query.filter_by(custom_category_id=category.id).all():
                if not _csv_fingerprint(txn):
                    continue  # a rule placed this row deliberately: leave it alone
                txn.custom_category_id = None
                if _csv_stored_category(txn.category) and _is_account_label_text(
                        txn.category, txn.account,
                        txn.credential.institution_name if txn.credential else None):
                    txn.category = None
                    cleared += 1

        dead = _unused_category_ids(db, CustomCategory, Transaction, CategoryRule,
                                    TransactionCategoryOverride, categories)
        for category in categories:
            if category.id in dead:
                db.session.delete(category)

        for template, fixed, _notes in templates:
            template.mappings = json.dumps(fixed)

        db.session.commit()

        left_rows = len(_candidate_rows(db, Transaction, Account, Credential))
        left_categories = len(_leftover_damage_categories(
            db, CustomCategory, Transaction, CategoryRule, TransactionCategoryOverride))
        left_templates = len(_templates_needing_fix(db, CsvImportTemplate, guard_category_mapping))

        print('\nApplied: %d row(s) cleared to Uncategorized, %d override(s) removed, '
              '%d account-label category(ies) deleted, %d template(s) remapped.'
              % (cleared, removed_overrides, len(dead), len(templates)))
        print('Remaining after the pass: %d row(s), %d category(ies), %d template(s).'
              % (left_rows, left_categories, left_templates))
        if left_rows or left_categories or left_templates:
            print('Not everything could be cleared — review the remaining items by hand.')
            return 1
        print('Clean.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
