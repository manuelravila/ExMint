#!/usr/bin/env python3
"""
Daily balance snapshot.

Stores one row per account per day in account_balance_snapshots: the balance the
dashboard would show today (anchor + transactions since the anchor, else the
cached Plaid balance, else the transaction sum) and which of those it came from.
These rows are the debt history the balances card can chart over time.

Runs as a cron job in the Docker cron container, and is safe to run by hand —
re-running it on the same day refreshes that day's rows instead of duplicating
them.
"""
import sys


def main():
    from app import create_app
    from models import db, User
    from core_views import _record_balance_snapshots

    app = create_app()

    with app.app_context():
        users = User.query.filter(User.status == 'Active').all()
        if not users:
            print('No active users — nothing to snapshot.')
            return 0

        total = 0
        for user in users:
            try:
                written = _record_balance_snapshots(user.id)
                total += written
                print(f'Snapshot for user {user.id}: {written} account(s)')
            except Exception as exc:
                db.session.rollback()
                print(f'  Warning: snapshot failed for user {user.id}: {exc}', file=sys.stderr)
        print(f'Balance snapshots written for {total} account(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
