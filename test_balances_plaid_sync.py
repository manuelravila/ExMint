#!/usr/bin/env python
"""test_balances_plaid_sync.py — EX-13: Plaid balances arrive with the sync, not from a paid call.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_balances_plaid_sync.py

/accounts/balance/get is a real-time paid product: PROD answered HTTP 429 for
every credential on every sync, so current_balance stayed NULL and no Plaid
account ever showed a balance.  /transactions/sync already carries
accounts[].balances (Plaid's cached, free copy), and /accounts/get is the free
fallback for the accounts a given delta did not mention.

Against the dev database with throwaway rows and a stand-in Plaid client, it
checks that _sync_credential_transactions:

- stores current_balance/available_balance straight from the sync payload;
- stamps balance_fetched_at, which is the date the "as of …" line reports;
- calls /accounts/get only for the accounts the payload left out, and not at all
  when the payload covered them all;
- never calls /accounts/balance/get (the stand-in records it, and the check fails
  if it appears);
- leaves a CSV-only credential's accounts unpolled, and its stale balance unused.

Every row it created is deleted and the cleanup is asserted.  No pytest is used
(the venv does not have it); exits non-zero on any failure.
"""

import sys
import uuid
from decimal import Decimal

_PASSES = []
_FAILURES = []


def check(name, condition, detail=''):
    if condition:
        _PASSES.append(name)
        print('PASS: %s' % name)
    else:
        _FAILURES.append(name)
        print('FAIL: %s%s' % (name, (' — ' + detail) if detail else ''))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class _FakePlaidClient:
    """Answers the two free endpoints and keeps a log of what was asked for."""

    def __init__(self, sync_accounts, accounts_get_accounts):
        self.sync_accounts = sync_accounts
        self.accounts_get_accounts = accounts_get_accounts
        self.calls = []

    def reset(self):
        self.calls = []

    def transactions_sync(self, payload):
        self.calls.append('transactions_sync')
        return _FakeResponse({
            'added': [], 'modified': [], 'removed': [],
            'accounts': self.sync_accounts,
            'has_more': False, 'next_cursor': None,
        })

    def accounts_get(self, request):
        self.calls.append('accounts_get')
        return _FakeResponse({'accounts': self.accounts_get_accounts})

    def accounts_balance_get(self, request):
        # The paid real-time call: PROD 429s on it, so it must not be used.
        self.calls.append('accounts_balance_get')
        raise AssertionError('/accounts/balance/get must never be called during a sync')


def _plaid_account(plaid_id, mask, balances):
    return {'account_id': plaid_id, 'name': 'Plaid Account %s' % mask, 'type': 'depository',
            'subtype': 'checking', 'mask': mask, 'is_enabled': True, 'balances': balances}


def _balances_for_user(user_id, institution):
    from core_views import _collect_balances_summary
    shown = {}
    for group in _collect_balances_summary(user_id)['groups']:
        for inst in group['institutions']:
            if inst['name'] == institution:
                for acct in inst['accounts']:
                    shown[acct['mask']] = acct
    return shown


def main():
    from app import app
    from models import Account, Credential, Transaction, User, db

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri:
        print('ABORT — refusing to run against non-dev database (%s)' % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    tag = 'EXMINT-LIVE-PLAIDBAL-%s' % uuid.uuid4().hex[:8]
    institution = '%s Bank' % tag
    paused_institution = '%s Paused' % tag
    covered_plaid_id = 'covered-%s' % tag
    uncovered_plaid_id = 'uncovered-%s' % tag
    paused_plaid_id = 'paused-%s' % tag

    state = {'user_id': None, 'cred_ids': [], 'acct_ids': []}
    real_client = app.plaid_client

    with app.app_context():
        try:
            user = User.query.first()
            if user is None:
                print('ABORT — no User rows found in the dev database')
                return False
            state['user_id'] = user.id

            live = Credential(user_id=user.id, item_id='item-%s' % tag, institution_name=institution,
                              access_token='token-%s' % tag, soft_disconnected=False, requires_update=False)
            paused_cred = Credential(user_id=user.id, item_id='item-%s-paused' % tag,
                                     institution_name=paused_institution,
                                     access_token=None, soft_disconnected=True, requires_update=False)
            db.session.add_all([live, paused_cred])
            db.session.commit()
            state['cred_ids'] = [live.id, paused_cred.id]

            def new_account(cred, plaid_id, mask, current=None):
                acct = Account(status='Active', credential_id=cred.id, plaid_account_id=plaid_id,
                               name='%sacct %s' % (tag, mask), type='depository', subtype='checking',
                               mask=mask, is_enabled=True,
                               current_balance=Decimal(current) if current is not None else None)
                db.session.add(acct)
                db.session.commit()
                state['acct_ids'].append(acct.id)
                return acct

            covered = new_account(live, covered_plaid_id, '1201')
            uncovered = new_account(live, uncovered_plaid_id, '1202')
            # A CSV-only account holding the balance Plaid reported the day it was
            # paused: nobody polls it and the dashboard must not present it as live.
            paused_acct = new_account(paused_cred, paused_plaid_id, '1203', current='99.99')

            from core_views import _sync_credential_transactions

            # The delta only mentions the account it moved money on, exactly like
            # the real endpoint: the one with no movement needs the free lookup.
            fake_client = _FakePlaidClient(
                [_plaid_account(covered_plaid_id, '1201', {'current': 1234.56, 'available': 1200.00})],
                [_plaid_account(uncovered_plaid_id, '1202', {'current': 77.70, 'available': 70.00}),
                 _plaid_account(covered_plaid_id, '1201', {'current': 1234.56, 'available': 1200.00})],
            )
            app.plaid_client = fake_client

            fake_client.reset()
            _counts, error = _sync_credential_transactions(user, live)
            check('sync ran without a Plaid error', error is None, repr(error))
            check('/accounts/balance/get was never called',
                  'accounts_balance_get' not in fake_client.calls, repr(fake_client.calls))
            db.session.refresh(covered)
            db.session.refresh(uncovered)
            check('the account the sync payload carried got its balance (1,234.56)',
                  covered.current_balance is not None
                  and Decimal(covered.current_balance) == Decimal('1234.56')
                  and Decimal(covered.available_balance) == Decimal('1200.00'),
                  repr((covered.current_balance, covered.available_balance)))
            check('the balance is stamped with when it was read',
                  covered.balance_fetched_at is not None, repr(covered.balance_fetched_at))
            check('an account the delta skipped falls back to /accounts/get (77.70)',
                  'accounts_get' in fake_client.calls
                  and uncovered.current_balance is not None
                  and Decimal(uncovered.current_balance) == Decimal('77.70'),
                  repr((fake_client.calls, uncovered.current_balance)))
            check('what the dashboard shows after one sync is the Plaid figure, dated',
                  _balances_for_user(user.id, institution).get('1201', {}).get('balance_source') == 'plaid'
                  and Decimal(str(_balances_for_user(user.id, institution).get('1201', {}).get('balance')))
                  == Decimal('1234.56'),
                  repr(_balances_for_user(user.id, institution).get('1201')))

            # ── A sync whose payload already covers every account ───────────
            fake_client.sync_accounts = [
                _plaid_account(covered_plaid_id, '1201', {'current': 2000.00, 'available': 1990.00}),
                _plaid_account(uncovered_plaid_id, '1202', {'current': 300.00, 'available': 300.00}),
            ]
            fake_client.reset()
            _sync_credential_transactions(user, live)
            check('a fully covering payload costs no extra Plaid call',
                  fake_client.calls == ['transactions_sync'], repr(fake_client.calls))
            db.session.refresh(covered)
            check('the newer balance replaced the older one (2,000.00)',
                  Decimal(covered.current_balance) == Decimal('2000.00'), repr(covered.current_balance))

            # ── A CSV-only credential is never balance-polled ───────────────
            fake_client.reset()
            _sync_credential_transactions(user, paused_cred)
            check('a CSV-only credential makes no balance call',
                  fake_client.calls == [], repr(fake_client.calls))
            db.session.refresh(paused_acct)
            check('its account keeps the balance it already had',
                  paused_acct.current_balance is not None
                  and Decimal(paused_acct.current_balance) == Decimal('99.99'),
                  repr(paused_acct.current_balance))
            check('and the dashboard does not present that stale figure as a live balance',
                  _balances_for_user(user.id, paused_institution).get('1203', {}).get('balance_source') != 'plaid',
                  repr(_balances_for_user(user.id, paused_institution).get('1203')))

            # ── An anchor still outranks the freshly fetched balance ────────
            covered.last_known_balance = Decimal('1500.00')
            covered.balance_date = covered.balance_fetched_at.date()
            db.session.commit()
            entry = _balances_for_user(user.id, institution).get('1201', {})
            check('a manual anchor outranks the fresh Plaid balance',
                  entry.get('balance_source') == 'anchor+tx'
                  and Decimal(str(entry.get('balance'))) == Decimal('1500.00'),
                  repr(entry))
        finally:
            app.plaid_client = real_client
            Transaction.query.filter(Transaction.credential_id.in_(state['cred_ids'])) \
                .delete(synchronize_session=False)
            Account.query.filter(Account.id.in_(state['acct_ids'])).delete(synchronize_session=False)
            Credential.query.filter(Credential.id.in_(state['cred_ids'])).delete(synchronize_session=False)
            db.session.commit()
            left = (Transaction.query.filter(Transaction.credential_id.in_(state['cred_ids'])).count()
                    + Account.query.filter(Account.id.in_(state['acct_ids'])).count()
                    + Credential.query.filter(Credential.id.in_(state['cred_ids'])).count())
            check('cleanup removed every test row', left == 0, '%d left' % left)

    return not _FAILURES


if __name__ == '__main__':
    result = main()
    print('Total: %d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if result else 1)
