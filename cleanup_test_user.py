#!/usr/bin/env python3
"""
Nightly cleanup of the STAG test user.

Revokes all active Plaid connections and wipes transaction/account/credential
data for the account configured in TEST_USER_EMAIL, leaving the user row itself
intact so the account can be reused the next day.

Designed to run as a cron job inside the Docker cron container on STAG.
Set TEST_USER_EMAIL in the environment (or .env.stag) to enable cleanup.
"""
import os
import sys


TEST_USER_EMAIL = os.getenv('TEST_USER_EMAIL', '')


def main():
    if not TEST_USER_EMAIL:
        print('TEST_USER_EMAIL not set — nothing to do.')
        sys.exit(0)

    from app import create_app
    from models import (db, User, Credential, Account, Transaction,
                        TransactionCategoryOverride, Budget,
                        CustomCategory, CategoryRule)
    from plaid.model.item_remove_request import ItemRemoveRequest

    app = create_app()
    plaid_client = app.plaid_client

    with app.app_context():
        user = User.query.filter_by(email=TEST_USER_EMAIL).first()
        if not user:
            print(f'User {TEST_USER_EMAIL!r} not found — nothing to do.')
            sys.exit(0)

        user_id = user.id
        print(f'Cleaning up test user: {TEST_USER_EMAIL} (id={user_id})')

        # --- Revoke active Plaid items ---
        active_creds = Credential.query.filter_by(user_id=user_id, status='Active').all()
        for cred in active_creds:
            if not cred.access_token:
                continue
            try:
                plaid_client.item_remove(ItemRemoveRequest(access_token=cred.access_token))
                print(f'  Revoked Plaid item {cred.item_id!r}')
            except Exception as exc:
                print(f'  Warning: could not revoke item {cred.item_id!r}: {exc}', file=sys.stderr)

        # --- Wipe user data in FK-safe order ---

        # 1. TransactionCategoryOverride (FK → transactions, custom_categories)
        TransactionCategoryOverride.query.filter(
            TransactionCategoryOverride.transaction_id.in_(
                db.session.query(Transaction.id).filter_by(user_id=user_id)
            )
        ).delete(synchronize_session=False)

        # 2. Clear split-child self-references to avoid FK cycle on deletion
        Transaction.query.filter_by(user_id=user_id).update(
            {'parent_transaction_id': None}, synchronize_session=False
        )

        # 3. Transactions (FK → account, credential, custom_category)
        Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 4. Accounts (FK → credential)
        Account.query.filter(
            Account.credential_id.in_(
                db.session.query(Credential.id).filter_by(user_id=user_id)
            )
        ).delete(synchronize_session=False)

        # 5. Credentials
        Credential.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 6. Budgets
        Budget.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 7. Category rules (FK → custom_categories)
        CategoryRule.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 8. Custom categories
        CustomCategory.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        db.session.commit()
        print(f'Cleanup complete for {TEST_USER_EMAIL}.')


if __name__ == '__main__':
    main()
