#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

from plaid import ApiException
from plaid.model.item_remove_request import ItemRemoveRequest

from app import create_app
from models import Credential


def load_csv_tokens(csv_path: Path) -> set[str]:
    with csv_path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        return {row['access_token'].strip() for row in reader if row.get('access_token')}


def main() -> None:
    parser = argparse.ArgumentParser(description='Deactivate unused Plaid tokens from CSV.')
    parser.add_argument('--csv', type=Path, default=Path('tokens.csv'), help='Path to tokens CSV.')
    args = parser.parse_args()

    csv_tokens = load_csv_tokens(args.csv)
    if not csv_tokens:
        print('No tokens found in CSV.')
        return

    app = create_app()
    plaid_client = app.plaid_client

    with app.app_context():
        active_tokens = {
            cred.access_token
            for cred in Credential.query.filter_by(status='Active').all()
            if cred.access_token
        }

    stale_tokens = sorted(csv_tokens - active_tokens)
    if not stale_tokens:
        print('All CSV tokens are active in PROD. Nothing to do.')
        return

    print(f'Found {len(stale_tokens)} token(s) not active in PROD.')
    for token in stale_tokens:
        choice = input(f'Remove token "{token}"? [y/N]: ').strip().lower()
        if choice != 'y':
            print('Skipped.')
            continue

        try:
            request = ItemRemoveRequest(access_token=token)
            response = plaid_client.item_remove(request)
            request_id = response.to_dict().get('request_id')
            print(f'Removed token "{token}". request_id={request_id}')
        except ApiException as exc:
            print(f'Plaid error removing "{token}": {exc}')
        except Exception as exc:
            print(f'Unexpected error removing "{token}": {exc}')


if __name__ == '__main__':
    main()