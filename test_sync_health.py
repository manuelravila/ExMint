#!/usr/bin/env python
"""test_sync_health.py — EX-03: a card that stops syncing has to be named, not inferred.

Run from the repository root (live check against the DEV database only):

    ./venv/bin/python test_sync_health.py

The 2026-10-22 report found four connections that had stopped feeding ExMint
while the dashboard kept showing their old data, so spending read lower than it
was: Scotiabank (#27, requires_update), RBC Royal Bank (soft-disconnected,
nothing after Oct 5), the WestJet card 9669 (silent since Aug 5) and the Amex
card 1008 (revoked since June).  None of them was shown prominently.

A throwaway user is created and given accounts reproducing exactly those four
shapes plus the controls that decide whether the rule is any good — a healthy
card, a genuinely low-cadence account that must NOT be flagged, a card whose
transactions bunch up, a CSV-only institution, a closed account, a disabled
account, an investment account with no transactions and a spending account with
none either.  Under the dev app it then checks, through ``collect_sync_health``
and the three routes that publish it (``GET /api/dashboard``, ``GET /api/banks``
and v1 ``GET /institutions``):

* all four shapes are reported, each for the right reason;
* an account is called silent only past ``max(10 days, 3 x its own usual gap)``,
  so a quarterly account is left alone while a daily card that stopped eight
  weeks ago is not;
* ``expected_tx_per_month`` is the median of the three 30-day buckets of the
  last 90 days, and ``expected_gap_days`` the *mean* gap between transaction
  dates — the span divided by the number of gaps — because a card whose purchase
  and payment land a few days apart is not an every-3-days card;
* a revoked/paused/reconnect-needed connection is reported even when its
  account is otherwise quiet, and a CSV-only institution is not called paused
  just because it has no Plaid connection — but a CSV account nobody has
  imported for two months is still named;
* an account that has never transacted keeps its badge but is not counted as
  "nothing arriving": it is absent from the quiet counts, the institution
  headline and the banner ranking, so it cannot bury a bank that really broke;
* the banner shows at most ``BANNER_INSTITUTION_LIMIT`` institutions and its
  "+N more" line names the ones it cut;
* closed and disabled accounts are left out of the report entirely, and an
  account with no transactions is only reported as missing data when it is a
  spending account (a GIC or a mortgage genuinely produces none);
* the dashboard carries the banner payload and the accounts list carries the
  per-account fields, and the same answers come back through an X-API-Key.

Everything the test creates is deleted at the end and the cleanup is asserted.
No pytest is used (the venv does not have it); exits non-zero on any failure.

To re-run the same rule over the real PROD rows, make a read-only copy of the
three tables it needs and point EXMINT_SYNC_HEALTH_PROD_COPY at it:

    mysqldump -u root --single-transaction --compact --no-create-info \\
        mrar1995_xmnt_prd_db user credential account transactions > /tmp/prd_rows.sql
    # restore that dump into a scratch schema, then:
    EXMINT_SYNC_HEALTH_PROD_COPY=mysql+pymysql://user:pass@127.0.0.1:3306/scratch_db \\
        ./venv/bin/python test_sync_health.py
"""

import datetime
import os
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


def main():
    from app import app
    from models import Account, ApiKey, Credential, Transaction, User, db
    from sync_health import (
        ACTIVITY_WINDOW_DAYS, ALERT_REASONS, ACTIVITY_REASONS,
        BANNER_INSTITUTION_LIMIT, CONNECTION_REASONS, GAP_MULTIPLIER,
        MIN_SILENT_DAYS, REASON_NO_RECENT_ACTIVITY, REASON_NO_TRANSACTIONS,
        REASON_ORDER, REASON_REQUIRES_UPDATE, REASON_REVOKED,
        REASON_SOFT_DISCONNECTED, STATUS_HEALTHY,
        banner_selection, collect_sync_health, summarize_institutions,
        _mean_gap_days, _median_tx_per_month, _silent_after_days, _cadence_phrase,
    )

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if '_dev_db' not in uri or '_prd_db' in uri or '_stg_db' in uri:
        print('ABORT — refusing to run against a non-dev database (%s)'
              % uri.split('@', 1)[-1])
        return False
    print('database target = %s' % uri.split('@', 1)[-1])

    today = datetime.date.today()
    tag = 'EXMINT-SYNCHLTH-%s' % uuid.uuid4().hex[:8]
    state = {}

    # ---------------------------------------------------------------- pure rule
    # The rule itself, checked away from any database.
    daily = [today - datetime.timedelta(days=n) for n in range(0, 60, 3)]
    check('a card that posts every 3 days reports a 3-day usual gap',
          _mean_gap_days(daily) == 3.0, repr(_mean_gap_days(daily)))
    check('a fast account is judged by the 10-day floor, not by 3 x 3 days',
          _silent_after_days(3.0) == MIN_SILENT_DAYS and _silent_after_days(5.0) == GAP_MULTIPLIER * 5,
          repr((_silent_after_days(3.0), _silent_after_days(5.0))))
    check('an account with no cadence to measure still has a floor of %d days'
          % MIN_SILENT_DAYS,
          _silent_after_days(None) == MIN_SILENT_DAYS and _silent_after_days(0.5) == MIN_SILENT_DAYS,
          repr((_silent_after_days(None), _silent_after_days(0.5))))
    check('a quarterly account is allowed a longer silence than a 9-day threshold',
          _silent_after_days(90.0) == 270, repr(_silent_after_days(90.0)))
    check('transactions on the same day collapse into one activity date',
          _mean_gap_days([today, today, today - datetime.timedelta(days=10)]) == 10.0,
          repr(_mean_gap_days([today, today, today - datetime.timedelta(days=10)])))
    # Ringo's repro for the median bug: a purchase and its payment land 3 days
    # apart, each pair 27 days after the one before it.  A median gap reads 3 —
    # an every-3-days card that has to be named after 10 quiet days — while the
    # span says what the card really does: one episode every 12.6 days.
    bunched_dates = [today - datetime.timedelta(days=n) for n in (0, 3, 30, 33, 60, 63)]
    check('transactions that bunch up are measured across the span, not by the median gap',
          _mean_gap_days(bunched_dates) == 12.6, repr(_mean_gap_days(bunched_dates)))
    check('a bunched card is reported after 38 quiet days, not the 10 a median gap would give',
          _silent_after_days(_mean_gap_days(bunched_dates)) == 38
          and _silent_after_days(3.0) == MIN_SILENT_DAYS,
          repr((_mean_gap_days(bunched_dates),
                _silent_after_days(_mean_gap_days(bunched_dates)))))
    check('expected activity is the median of the three 30-day buckets of the last 90 days',
          _median_tx_per_month(daily, today) == 10.0,
          repr(_median_tx_per_month(daily, today)))
    check('a burst in one bucket does not move the median',
          _median_tx_per_month(daily + [today - datetime.timedelta(days=45)] * 40, today) == 10.0,
          repr(_median_tx_per_month(daily + [today - datetime.timedelta(days=45)] * 40, today)))

    # ------------------------------------------------------------------ fixtures
    with app.app_context():
        user = User(email='%s@example.com' % tag.lower(), status='Active', role='User')
        user.set_password('not-a-real-password-%s' % tag)
        db.session.add(user)
        db.session.commit()
        state['user_id'] = user.id

        def cred(institution, **kwargs):
            kwargs.setdefault('item_id', 'item-%s' % uuid.uuid4().hex)
            row = Credential(user_id=user.id, institution_name=institution,
                             label=kwargs.pop('label', None), access_token=None, **kwargs)
            db.session.add(row)
            db.session.commit()
            state.setdefault('cred_ids', []).append(row.id)
            return row

        def account(credential, name, type_, mask=None, subtype=None, **kwargs):
            row = Account(status=kwargs.pop('status', 'Active'), credential_id=credential.id,
                          plaid_account_id='synchlth-%s' % uuid.uuid4().hex,
                          name='%s %s' % (tag, name), type=type_, subtype=subtype, mask=mask,
                          is_enabled=kwargs.pop('is_enabled', True),
                          is_closed=kwargs.pop('is_closed', False), **kwargs)
            db.session.add(row)
            db.session.commit()
            state.setdefault('acct_ids', []).append(row.id)
            return row

        def transactions(acct, credential, start_offset, count, stride):
            """``count`` transactions ``stride`` days apart, newest first, ending
            ``start_offset`` days before today."""
            add_transactions(acct, credential,
                             [start_offset + i * stride for i in range(count)])

        def add_transactions(acct, credential, offsets):
            """Transactions on exactly these day-offsets before today.  Needed for
            a cadence that does not repeat on a fixed stride — see the bunched
            card below.  Amounts are not part of this test; the column just gets
            a plausible figure."""
            for offset in offsets:
                day = today - datetime.timedelta(days=offset)
                db.session.add(Transaction(
                    plaid_transaction_id='%s-%s' % (tag, uuid.uuid4().hex[:10]),
                    user_id=user.id, credential_id=credential.id, account_id=acct.id,
                    name='%s %s %s' % (tag, acct.mask or acct.id, day.isoformat()),
                    amount=Decimal('-10.00'), date=day, iso_currency_code='CAD'))
            db.session.commit()

        # ---- the four connections that failed on 2026-10-22 ----------------
        # Scotiabank #27: Plaid flagged the login, and the bank stopped sending.
        scotia = cred('Scotiabank', requires_update=True, soft_disconnected=False)
        scotia_checking = account(scotia, 'Ultimate Package', 'depository', '6985', 'checking')
        transactions(scotia_checking, scotia, 3, 12, 3)

        # RBC: soft-disconnected, nothing after Oct 5 — 26 days of silence here.
        rbc = cred('RBC Royal Bank', requires_update=False, soft_disconnected=True)
        rbc_staff = account(rbc, 'Staff Banking', 'depository', '6614', 'checking')
        transactions(rbc_staff, rbc, 26, 15, 4)
        rbc_save = account(rbc, 'Find & Save', 'depository', '9102', 'savings')
        transactions(rbc_save, rbc, 146, 12, 15)

        # WestJet 9669: the connection looked fine and simply stopped arriving.
        westjet_cred = cred('WestJet RBC World Elite Mastercard')
        westjet = account(westjet_cred, 'World Elite Mastercard', 'credit', '9669', 'credit card')
        transactions(westjet, westjet_cred, 87, 30, 5)

        # Amex 1008: the credential was revoked in June.
        amex = cred('American Express (CA)', status='Revoked')
        amex_acct = account(amex, 'Cash Plus Card', 'credit', '1008', 'credit card')
        transactions(amex_acct, amex, 120, 20, 6)

        # ---- the controls that decide whether the rule is worth having ------
        # Healthy: posting every 3 days, most recent transaction yesterday.
        healthy_cred = cred('Healthy Bank')
        healthy = account(healthy_cred, 'Everyday Checking', 'depository', '1111', 'checking')
        transactions(healthy, healthy_cred, 1, 25, 3)

        # Low cadence: every 20 days, 55 days since the last one.  3 x 20 = 60,
        # so this account must NOT be flagged.  A flat 30-day window would flag
        # it every time and teach Manuel to ignore the banner.
        slow_cred = cred('Slow Savings')
        slow = account(slow_cred, 'Quarterly Savings', 'depository', '2222', 'savings')
        transactions(slow, slow_cred, 55, 8, 20)

        # Bunched cadence: a purchase and its payment 3 days apart, each pair 27
        # days after the last (15, 18, 45, 48, 75, 78 days before today).  The
        # median gap is 3, which would call this an every-3-days card that
        # belongs on the banner after 10 ordinary days; the span gives 12.6 and a
        # limit of 38, and 15 days is simply this card being itself.
        bunched_cred = cred('Bunched Cadence Bank')
        bunched = account(bunched_cred, 'Purchase and Payment Card', 'credit',
                          '3131', 'credit card')
        add_transactions(bunched, bunched_cred, [15, 18, 45, 48, 75, 78])

        # CSV-only institution: soft_disconnected by construction, so it is not
        # "paused" — but two months without an import is still reported.
        csv_live_cred = cred('Imported Brokerage', soft_disconnected=True,
                             item_id='csv-%s' % uuid.uuid4().hex, transactions_cursor=None)
        csv_live = account(csv_live_cred, 'Imported Account', 'depository', '3333', 'checking')
        transactions(csv_live, csv_live_cred, 2, 20, 6)

        csv_quiet_cred = cred('Imported Card', soft_disconnected=True,
                              item_id='csv-%s' % uuid.uuid4().hex, transactions_cursor=None)
        csv_quiet = account(csv_quiet_cred, 'Imported Card', 'credit', '4444', 'credit card')
        transactions(csv_quiet, csv_quiet_cred, 40, 12, 6)

        # An investment account with no transactions is not a broken feed.
        gic_cred = cred('GIC Institution')
        gic = account(gic_cred, 'GIC', 'investment', '5555', 'gic')

        # A spending account with no transactions is.
        empty_cred = cred('Unused Card')
        empty = account(empty_cred, 'Never Used Card', 'credit', '6666', 'credit card')

        # A bank that was re-connected, which is what left the four 2026-10-22
        # cases hidden: the live credential plus a dead one left behind.  The
        # dead credential is kept only for the card the live one does not show,
        # and the card they share is named once — under the live one.
        reconnected_live = cred('Reconnected Bank')
        reconnected_card = account(reconnected_live, 'Reconnected Card', 'credit',
                                   '9999', 'credit card')
        transactions(reconnected_card, reconnected_live, 4, 20, 4)

        reconnected_dead = cred('Reconnected Bank', status='Revoked')
        shadowed_card = account(reconnected_dead, 'Old Reconnected Card', 'credit',
                                '9999', 'credit card')
        # The card the re-connection dropped keeps the data it last received —
        # that is what the same card looks like in PROD — so its own silence is
        # what gets reported, and it is named under the bank it still belongs to.
        orphan_card = account(reconnected_dead, 'Card Lost On Reconnect', 'credit',
                              '9998', 'credit card')
        transactions(orphan_card, reconnected_dead, 200, 15, 10)

        # A leftover credential whose every card already shows under the live one.
        reconnected_dead_again = cred('Reconnected Bank', status='Revoked')
        duplicate_card = account(reconnected_dead_again, 'Duplicate Row', 'credit',
                                 '9999', 'credit card')

        # A second live credential of the same bank whose login Plaid flagged —
        # the shape Scotiabank had on 2026-10-22: one connection fine, another
        # needing a reconnect.
        reconnected_flagged = cred('Reconnected Bank', requires_update=True, label='Second login')
        flagged_card = account(reconnected_flagged, 'Flagged Card', 'credit',
                               '9997', 'credit card')

        # Left out of the report entirely.
        closed_cred = cred('Cancelled Bank')
        closed = account(closed_cred, 'Cancelled Card', 'credit', '7777', 'credit card',
                         is_closed=True)
        transactions(closed, closed_cred, 90, 10, 5)

        disabled_cred = cred('Unchecked Bank')
        disabled = account(disabled_cred, 'Unchecked Checking', 'depository', '8888', 'checking',
                           is_enabled=False)
        transactions(disabled, disabled_cred, 90, 10, 5)

        # An API key, so the header path is exercised too.
        from api_views import _generate_api_key, _hash_api_key
        full_key, _raw, prefix = _generate_api_key()
        api_key = ApiKey(key_hash=_hash_api_key(full_key), key_prefix=prefix,
                         user_id=user.id, name='%s key' % tag)
        db.session.add(api_key)
        db.session.commit()
        state['key_id'] = api_key.id
        api_headers = {'X-API-Key': full_key}

        report = collect_sync_health(user.id, today=today)
        by_account = {r['account_id']: r for r in report['accounts']}
        inst_by_id = {i['id']: i for i in report['institutions']}

        # ---- the four 2026-10-22 cases are flagged -------------------------
        scotia_rec = by_account[scotia_checking.id]
        check('Scotiabank (requires_update) is flagged',
              scotia_rec['needs_attention']
              and REASON_REQUIRES_UPDATE in scotia_rec['reasons']
              and scotia_rec['status'] == REASON_REQUIRES_UPDATE,
              repr(scotia_rec))
        rbc_rec = by_account[rbc_staff.id]
        check('RBC (soft_disconnected) is flagged for the disconnect and for the silence',
              rbc_rec['needs_attention']
              and REASON_SOFT_DISCONNECTED in rbc_rec['reasons']
              and REASON_NO_RECENT_ACTIVITY in rbc_rec['reasons'],
              repr(rbc_rec))
        westjet_rec = by_account[westjet.id]
        check('WestJet 9669 is flagged although its connection looks healthy',
              westjet_rec['needs_attention'] and westjet_rec['reasons'] == [REASON_NO_RECENT_ACTIVITY]
              and westjet_rec['days_since_last_transaction'] == 87,
              repr(westjet_rec))
        check('WestJet is reported against its own cadence, not a fixed window',
              westjet_rec['expected_gap_days'] == 5.0
              and westjet_rec['silent_after_days'] == GAP_MULTIPLIER * 5
              and westjet_rec['detail'].startswith('no transactions since'),
              repr(westjet_rec))
        amex_rec = by_account[amex_acct.id]
        check('Amex 1008 (revoked credential) is flagged as revoked',
              amex_rec['needs_attention'] and amex_rec['status'] == REASON_REVOKED
              and REASON_REVOKED in amex_rec['reasons'],
              repr(amex_rec))
        check('the four 2026-10-22 cases all reach the alert list',
              {by_account[i]['account_id'] for i in
               (scotia_checking.id, rbc_staff.id, westjet.id, amex_acct.id)}
              <= {a['account_id'] for a in report['alerts']},
              repr([a['account_name'] for a in report['alerts']]))

        # ---- a broken connection is one banner line, not one per account ----
        rbc_inst = inst_by_id[rbc.id]
        check('a disconnected bank is one line naming what is wrong with the connection',
              rbc_inst['headline'].startswith('paused (no new data from the bank)')
              and '2 accounts with nothing arriving' in rbc_inst['headline'],
              repr(rbc_inst['headline']))
        check('and it names only the accounts that actually went quiet',
              rbc_inst['quiet_account_count'] == 2
              and len(rbc_inst['quiet_accounts']) == 2
              and [a['mask'] for a in rbc_inst['quiet_accounts']] == ['9102', '6614']
              and rbc_inst['account_count'] == 2,
              repr(rbc_inst['quiet_accounts']))
        check('an account quiet for its own reason is not filed as a connection fault',
              inst_by_id[westjet_cred.id]['connection_reasons'] == []
              and inst_by_id[amex.id]['connection_reasons'] == [REASON_REVOKED]
              and inst_by_id[scotia.id]['connection_reasons'] == [REASON_REQUIRES_UPDATE],
              repr([(i['institution_name'], i['connection_reasons'])
                    for i in report['institutions']]))
        check('the report counts connections broken and accounts gone quiet, separately',
              report['connection_problem_count'] == 5
              and report['alert_institution_count'] == 7
              and report['quiet_account_count'] == 6,
              repr({k: report.get(k) for k in ('connection_problem_count',
                                               'alert_institution_count', 'quiet_account_count')}))

        # ---- the controls --------------------------------------------------
        check('a card posting every 3 days is not flagged',
              by_account[healthy.id]['needs_attention'] is False
              and by_account[healthy.id]['reasons'] == []
              and by_account[healthy.id]['status'] == 'healthy',
              repr(by_account[healthy.id]))
        check('expected activity counts the three 30-day buckets of the last 90 days',
              by_account[healthy.id]['expected_tx_per_month'] == 10.0,
              repr(by_account[healthy.id]['expected_tx_per_month']))
        slow_rec = by_account[slow.id]
        check('a 20-day account quiet for 55 days is NOT flagged (3 x 20 = 60 days)',
              slow_rec['needs_attention'] is False
              and slow_rec['expected_gap_days'] == 20.0
              and slow_rec['silent_after_days'] == 60
              and slow_rec['days_since_last_transaction'] == 55,
              repr(slow_rec))
        bunched_rec = by_account[bunched.id]
        check('a card whose transactions bunch up is judged on 12.6 days, not on the 3 its median gap shows',
              bunched_rec['expected_gap_days'] == 12.6
              and bunched_rec['silent_after_days'] == 38
              and bunched_rec['days_since_last_transaction'] == 15,
              repr(bunched_rec))
        check('so 15 days of ordinary silence does not put that card on the banner',
              bunched_rec['needs_attention'] is False
              and bunched_rec['reasons'] == []
              and bunched_rec['status'] == STATUS_HEALTHY,
              repr(bunched_rec))
        csv_live_rec = by_account[csv_live.id]
        check('a CSV-only institution is not reported as paused',
              csv_live_rec['csv_only'] is True
              and csv_live_rec['needs_attention'] is False
              and REASON_SOFT_DISCONNECTED not in csv_live_rec['reasons'],
              repr(csv_live_rec))
        csv_quiet_rec = by_account[csv_quiet.id]
        check('a CSV account nobody has imported for 40 days is still named',
              csv_quiet_rec['needs_attention']
              and csv_quiet_rec['reasons'] == [REASON_NO_RECENT_ACTIVITY],
              repr(csv_quiet_rec))
        check('an investment account with no transactions is not treated as a broken feed',
              by_account[gic.id]['needs_attention'] is False
              and by_account[gic.id]['reasons'] == [],
              repr(by_account[gic.id]))
        empty_rec = by_account[empty.id]
        check('a spending account with no transactions at all is reported, but not as an alert',
              empty_rec['reasons'] == [REASON_NO_TRANSACTIONS]
              and empty_rec['needs_attention'] is False
              and empty_rec['last_transaction_date'] is None,
              repr(empty_rec))
        check('an account that has never transacted keeps its reason for the Accounts badge',
              empty_rec['activity_reasons'] == [REASON_NO_TRANSACTIONS]
              and inst_by_id[empty_cred.id]['reasons'] == [REASON_NO_TRANSACTIONS],
              repr([empty_rec['activity_reasons'], inst_by_id[empty_cred.id]['reasons']]))
        check('but it is not counted as an account with nothing arriving',
              inst_by_id[empty_cred.id]['quiet_accounts'] == []
              and inst_by_id[empty_cred.id]['quiet_account_count'] == 0
              and 'nothing arriving' not in inst_by_id[empty_cred.id]['headline'],
              repr(inst_by_id[empty_cred.id]['headline']))
        check('a closed account is out of the report', by_account.get(closed.id) is None,
              repr(by_account.get(closed.id)))
        check('a disabled account is out of the report', by_account.get(disabled.id) is None,
              repr(by_account.get(disabled.id)))
        # Sixteen accounts stay in the report: the four failed connections, the
        # six controls that must be judged healthy/reported-only, the GIC, the
        # unused card and the four cards of the re-connected bank.  Closed,
        # disabled and the fully duplicated credential are out of it.
        check('the report covers every account the user still sees, and no others',
              report['account_count'] == 16, repr(report['account_count']))
        check('the alert list is ordered most urgent first',
              [a['status'] for a in report['alerts']]
              == sorted([a['status'] for a in report['alerts']],
                        key=['revoked', 'requires_update', 'soft_disconnected',
                             'no_recent_activity', 'no_transactions'].index),
              repr([a['status'] for a in report['alerts']]))
        check('an alert says what it will cost: the detail names the cadence and the limit',
              'usually' in westjet_rec['detail'] and 'reported after 15' in westjet_rec['detail'],
              repr(westjet_rec['detail']))
        check('the detail pluralises what it counts',
              '1 transaction a month' in _cadence_phrase(1.0, 7.0)
              and 'one every 1 day' in _cadence_phrase(0.0, 1.0)
              and 'one every 23.5 days' in _cadence_phrase(0.0, 23.5)
              and '0 transactions' not in _cadence_phrase(0.0, 23.5),
              repr([_cadence_phrase(1.0, 7.0), _cadence_phrase(0.0, 1.0),
                    _cadence_phrase(0.0, 23.5)]))

        # ---- a re-connected bank is named once -----------------------------
        alert_ids = {a['account_id'] for a in report['alerts']}
        check('a card left under a dead credential is shadowed by the live one',
              by_account[shadowed_card.id]['shadowed'] is True
              and by_account[orphan_card.id]['shadowed'] is False
              and by_account[reconnected_card.id]['shadowed'] is False,
              repr([by_account[shadowed_card.id]['shadowed'],
                    by_account[orphan_card.id]['shadowed']]))
        check('the shadowed card is not alerted a second time',
              shadowed_card.id not in alert_ids and orphan_card.id in alert_ids,
              repr(sorted(alert_ids)))
        check('the dead credential is kept only for the card the live one lacks',
              inst_by_id[reconnected_dead.id]['status'] == REASON_REVOKED
              and [a['mask'] for a in inst_by_id[reconnected_dead.id]['alert_accounts']] == ['9998']
              and inst_by_id[reconnected_dead.id]['account_count'] == 2
              and inst_by_id[reconnected_dead.id]['alert_account_count'] == 1,
              repr(inst_by_id.get(reconnected_dead.id)))
        check('a credential whose cards all reappear under a live one is dropped',
              inst_by_id.get(reconnected_dead_again.id) is None
              and by_account.get(duplicate_card.id) is None,
              repr([i['institution_name'] for i in report['institutions']]))
        check('counts do not double-count the card under both credentials',
              report['counts'][REASON_REVOKED] == 2, repr(report['counts']))
        check('a second credential of the same bank is judged on its own cards',
              by_account[flagged_card.id]['status'] == REASON_REQUIRES_UPDATE
              and by_account[flagged_card.id]['needs_attention'] is True
              and inst_by_id[reconnected_flagged.id]['status'] == REASON_REQUIRES_UPDATE,
              repr([by_account.get(flagged_card.id),
                    inst_by_id.get(reconnected_flagged.id)]))
        check('the activity window the report is built on is stated in the payload',
              report['activity_window_days'] == ACTIVITY_WINDOW_DAYS
              and report['min_silent_days'] == MIN_SILENT_DAYS
              and report['gap_multiplier'] == GAP_MULTIPLIER, repr(report))

        # ---- institutions roll up -----------------------------------------
        def _rollup_record(institution_name, credential_id, status, quiet_days, sequence=0):
            """One account record, fabricated just far enough for a roll-up.

            The dev fixtures cannot prove the *ordering* on their own: no two of
            them need attention and differ only in urgency.  These isolate each
            element of the sort key — reason, how many accounts went quiet on the
            bank, then how long the longest silence is.
            """
            return {
                'account_id': 900000 + credential_id * 100 + sequence,
                'account_name': '%s account %d' % (institution_name, sequence),
                'mask': '%04d' % sequence,
                'account_type': 'credit',
                'subtype': 'credit card',
                'is_closed': False,
                'credential_id': credential_id,
                'institution_name': institution_name,
                'credential_label': None,
                'csv_only': False,
                'status': status,
                'reasons': [status],
                'connection_reasons': [status] if status in CONNECTION_REASONS else [],
                'activity_reasons': [status] if status in ACTIVITY_REASONS else [],
                'needs_attention': status in ALERT_REASONS,
                'detail': '%s detail' % status,
                'last_transaction_date': quiet_days.isoformat() if quiet_days else None,
                'days_since_last_transaction': (today - quiet_days).days if quiet_days else None,
                'transaction_count': 0,
                'expected_tx_per_month': 0.0,
                'expected_gap_days': None,
                'silent_after_days': MIN_SILENT_DAYS,
                'requires_update': status == REASON_REQUIRES_UPDATE,
                'soft_disconnected': status == REASON_SOFT_DISCONNECTED,
                'revoked': status == REASON_REVOKED,
                'shadowed': False,
            }

        def _quiet_bank(name, credential_id, status, quiet_day_offsets):
            return [_rollup_record(name, credential_id, status,
                                   today - datetime.timedelta(days=offset), sequence)
                    for sequence, offset in enumerate(quiet_day_offsets)]

        crowded = (_quiet_bank('Quiet Eight Bank', 901, REASON_NO_RECENT_ACTIVITY,
                               [40, 31, 22, 20, 19, 15, 12, 11])
                   + _quiet_bank('Quiet Tie Bank', 908, REASON_NO_RECENT_ACTIVITY, [300, 250, 240])
                   + _quiet_bank('Quiet Three Bank', 902, REASON_NO_RECENT_ACTIVITY, [200, 120, 60])
                   + _quiet_bank('Reconnect Bank', 903, REASON_REQUIRES_UPDATE, [7])
                   + _quiet_bank('Revoked Bank', 904, REASON_REVOKED, [500])
                   + _quiet_bank('Paused Bank', 905, REASON_SOFT_DISCONNECTED, [30])
                   + _quiet_bank('Never Used Bank', 906, REASON_NO_TRANSACTIONS, [0])
                   + _quiet_bank('Fine Bank', 907, STATUS_HEALTHY, [1]))
        crowded_rollup = summarize_institutions(crowded)
        crowded_order = [i['institution_name'] for i in crowded_rollup]
        crowded_by_name = {i['institution_name']: i for i in crowded_rollup}

        check('an institution is reported by its most urgent account',
              inst_by_id[amex.id]['status'] == REASON_REVOKED
              and inst_by_id[westjet_cred.id]['status'] == REASON_NO_RECENT_ACTIVITY,
              repr([(i['institution_name'], i['status']) for i in report['institutions']]))
        check('a healthy institution is listed as healthy',
              inst_by_id[healthy_cred.id]['status'] == 'healthy'
              and inst_by_id[healthy_cred.id]['needs_attention'] is False,
              repr(inst_by_id[healthy_cred.id]))
        check('institution freshness is its newest account, and its alerts name the accounts',
              inst_by_id[scotia.id]['last_transaction_date']
              == (today - datetime.timedelta(days=3)).isoformat()
              and inst_by_id[westjet_cred.id]['alert_accounts'][0]['mask'] == '9669',
              repr(inst_by_id[westjet_cred.id]))
        check('institutions needing attention sort first',
              [i['needs_attention'] for i in report['institutions']]
              == sorted([i['needs_attention'] for i in report['institutions']], reverse=True),
              repr([(i['institution_name'], i['needs_attention'])
                    for i in report['institutions']]))
        check('institutions needing attention sort by urgency, not by id',
              [REASON_ORDER.index(i['status']) for i in report['institutions'] if i['needs_attention']]
              == sorted([REASON_ORDER.index(i['status'])
                         for i in report['institutions'] if i['needs_attention']]),
              repr([(i['institution_name'], i['status'])
                    for i in report['institutions'] if i['needs_attention']]))
        check('the roll-up ranks a revoked bank above one needing a reconnect, '
              'that above a paused one, and those above a merely quiet one',
              crowded_order[:3] == ['Revoked Bank', 'Reconnect Bank', 'Paused Bank'],
              repr(crowded_order))
        check('of two quiet banks the one with more accounts gone quiet comes first',
              crowded_order.index('Quiet Eight Bank') < crowded_order.index('Quiet Tie Bank')
              and crowded_order.index('Quiet Tie Bank') < crowded_order.index('Quiet Three Bank'),
              repr(crowded_order))
        check('two banks with the same number of quiet accounts split on the longest silence',
              [i['quiet_account_count'] for i in crowded_rollup
               if i['institution_name'] in ('Quiet Tie Bank', 'Quiet Three Bank')] == [3, 3]
              and [i['days_since_last_transaction'] for i in crowded_rollup
                   if i['institution_name'] in ('Quiet Tie Bank', 'Quiet Three Bank')] == [240, 60],
              repr([(i['institution_name'], i['quiet_account_count'],
                     i['days_since_last_transaction'])
                    for i in crowded_rollup if i['institution_name'].startswith('Quiet')]))
        # Fix 3 consequence, made explicit: a bank whose accounts never
        # transacted has nothing that stopped arriving, so it no longer borrows
        # rank from them — it stays below every broken bank and out of the
        # banner altogether, which is where a bank with no data of its own
        # belongs.
        check('a bank that has never transacted does not outrank one that is actually broken',
              crowded_order.index('Never Used Bank') > crowded_order.index('Paused Bank')
              and crowded_by_name['Never Used Bank']['quiet_account_count'] == 0
              and 'Never Used Bank' not in [i['institution_name'] for i in banner_selection(crowded_rollup)[0]]
              and 'Never Used Bank' not in [i['institution_name'] for i in banner_selection(crowded_rollup)[1]],
              repr(crowded_order))

        # Ringo's shape for fix 3: a bank whose only fault is a revoked login,
        # with four accounts that never had a transaction in ExMint.  Those four
        # say nothing about a feed that stopped, so the headline names the
        # connection and nothing else, and the bank cannot outrank the revoked
        # one next to it that really did lose a feed.
        never_used_revoked = ([_rollup_record('Revoked Never Used Bank', 910, REASON_REVOKED, None)]
                              + [_rollup_record('Revoked Never Used Bank', 910, REASON_NO_TRANSACTIONS,
                                                None, sequence) for sequence in (1, 2, 3, 4)])
        revoked_and_quiet = ([_rollup_record('Revoked Quiet Bank', 911, REASON_REVOKED, None)]
                             + [_rollup_record('Revoked Quiet Bank', 911, REASON_NO_RECENT_ACTIVITY,
                                               today - datetime.timedelta(days=100), 1)])
        never_used_rollup = summarize_institutions(never_used_revoked + revoked_and_quiet)
        never_used_inst = {i['institution_name']: i for i in never_used_rollup}
        check('a revoked bank with four never-transacted accounts says only "connection revoked"',
              never_used_inst['Revoked Never Used Bank']['headline'] == 'connection revoked'
              and never_used_inst['Revoked Never Used Bank']['quiet_accounts'] == []
              and never_used_inst['Revoked Never Used Bank']['quiet_account_count'] == 0,
              repr(never_used_inst['Revoked Never Used Bank']))
        check('and it ranks below the revoked bank that has one account with nothing arriving',
              [i['institution_name'] for i in never_used_rollup]
              == ['Revoked Quiet Bank', 'Revoked Never Used Bank'],
              repr([(i['institution_name'], i['status'], i['quiet_account_count'])
                    for i in never_used_rollup]))
        check('the never-transacted accounts still reach the institution, so the badge survives',
              never_used_inst['Revoked Never Used Bank']['reasons']
              == [REASON_REVOKED, REASON_NO_TRANSACTIONS]
              and never_used_inst['Revoked Never Used Bank']['alert_account_count'] == 1,
              repr(never_used_inst['Revoked Never Used Bank']['reasons']))
        check('the banner shows at most %d institutions' % BANNER_INSTITUTION_LIMIT,
              banner_selection(crowded_rollup)[0] == crowded_rollup[:5]
              and len(banner_selection(crowded_rollup)[0]) == BANNER_INSTITUTION_LIMIT,
              repr([i['institution_name'] for i in crowded_rollup[:6]]))
        check('what the banner cuts is named, not just counted',
              [i['institution_name'] for i in banner_selection(crowded_rollup)[1]] == ['Quiet Three Bank']
              and all(sorted(i) == ['id', 'institution_name', 'label', 'status']
                      for i in banner_selection(crowded_rollup)[1]),
              repr(banner_selection(crowded_rollup)[1]))
        check('the cut institutions keep the banner order they were cut from',
              [i['id'] for i in banner_selection(crowded_rollup)[1]]
              == [i['id'] for i in crowded_rollup if i['needs_attention']][BANNER_INSTITUTION_LIMIT:]
              and banner_selection(crowded_rollup)[0][-1]['institution_name'] == 'Quiet Tie Bank',
              repr([i['institution_name'] for i in crowded_rollup if i['needs_attention']]))
        check('a banner that does not need cutting cuts nothing',
              banner_selection(crowded_rollup[:2]) == (crowded_rollup[:2], []),
              repr([i['institution_name'] for i in crowded_rollup[:2]]))
        check('a bank with nothing to report is never in the banner',
              all(inst['needs_attention'] for inst in banner_selection(crowded_rollup)[0]),
              repr([i['institution_name'] for i in banner_selection(crowded_rollup)[0]]))
        check('summarize_institutions stands on its own (no database needed)',
              summarize_institutions([]) == [], repr(summarize_institutions([])))

    # ------------------------------------------------------------------ routes
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(state['user_id'])
        sess['_fresh'] = True

    dash = client.get('/api/dashboard').get_json() or {}
    health = dash.get('sync_health') or {}
    check('GET /api/dashboard carries the banner payload',
          health.get('alert_count', 0) >= 4 and health.get('alerts'),
          repr({k: health.get(k) for k in ('alert_count', 'account_count', 'counts')}))
    banner_ids = {a['account_id'] for a in health.get('alerts', [])}
    check('the banner payload names the four failed connections',
          {scotia_checking.id, rbc_staff.id, westjet.id, amex_acct.id} <= banner_ids,
          repr(sorted(banner_ids)))
    check('the payload counts each kind of failure for the banner header',
          health.get('counts', {}).get('revoked') == 2
          and health.get('counts', {}).get('requires_update') == 2
          and health.get('counts', {}).get('soft_disconnected') == 2
          and health.get('counts', {}).get('no_recent_activity') == 6
          and health.get('counts', {}).get('no_transactions') == 2,
          repr(health.get('counts')))

    check('GET /api/dashboard hands the banner its capped slice',
          health.get('banner_institution_limit') == BANNER_INSTITUTION_LIMIT
          and len(health.get('banner_institutions', [])) <= BANNER_INSTITUTION_LIMIT,
          repr({k: health.get(k) for k in ('banner_institution_limit',
                                           'alert_institution_count')}))
    check('the banner slice is the head of the urgency-ordered list, not a random cut',
          [i['id'] for i in health.get('banner_institutions', [])]
          == [i['id'] for i in health.get('institutions', [])
              if i['needs_attention']][:BANNER_INSTITUTION_LIMIT],
          repr([(i['institution_name'], i['status'])
                for i in health.get('banner_institutions', [])]))
    check('the institutions the banner left out are counted for the page',
          health.get('banner_omitted_institution_count')
          == max(0, health.get('alert_institution_count', 0) - len(health.get('banner_institutions', [])))
          and health.get('banner_omitted_institution_count')
          == len(health.get('banner_omitted_institutions', [])),
          repr({k: health.get(k) for k in ('alert_institution_count',
                                           'banner_omitted_institution_count')}))
    omitted = health.get('banner_omitted_institutions', [])
    check('the payload names the institutions the banner cut, in the order it cut them',
          omitted == [{'id': i['id'], 'institution_name': i['institution_name'],
                       'label': i['label'], 'status': i['status']}
                      for i in health.get('institutions', [])
                      if i['needs_attention']][BANNER_INSTITUTION_LIMIT:]
          and all(sorted(i) == ['id', 'institution_name', 'label', 'status'] for i in omitted),
          repr([(i['institution_name'], i['label'], i['status']) for i in omitted]))
    check('nothing that needs attention is dropped: shown plus cut is the whole flagged list',
          [i['id'] for i in health.get('banner_institutions', [])] + [i['id'] for i in omitted]
          == [i['id'] for i in health.get('institutions', []) if i['needs_attention']],
          repr((health.get('alert_institution_count'), len(health.get('banner_institutions', [])),
                len(omitted))))

    sync_only = client.get('/api/sync-health').get_json() or {}
    check('GET /api/sync-health answers the same report on its own',
          sync_only.get('account_count') == health.get('account_count')
          and sync_only.get('alert_count') == health.get('alert_count'),
          repr({k: sync_only.get(k) for k in ('account_count', 'alert_count')}))

    banks = (client.get('/api/banks').get_json() or {}).get('banks', [])
    bank_by_id = {b['id']: b for b in banks}
    check('GET /api/banks reports each account last activity and its status',
          all(('last_transaction_date' in a and 'sync_status' in a and 'needs_attention' in a)
              for b in banks for a in b['accounts']),
          repr(banks[:1]))
    check('the accounts pane can name the quiet accounts per institution',
          bank_by_id[westjet_cred.id]['sync_alert_accounts'][0]['mask'] == '9669'
          and bank_by_id[westjet_cred.id]['needs_attention'] is True
          and bank_by_id[healthy_cred.id]['needs_attention'] is False,
          repr(bank_by_id.get(westjet_cred.id)))
    check('a CSV-only institution keeps its accounts listed without being called paused',
          bank_by_id[csv_live_cred.id]['accounts'][0]['sync_status'] == 'healthy',
          repr(bank_by_id.get(csv_live_cred.id)))

    page = client.get('/dashboard')
    check('the dashboard renders with the banner markup on it',
          page.status_code == 200 and b'sync-health-banner' in page.data,
          str(page.status_code))
    check('the banner hands what it cut to the Accounts pane',
          b'sync-health-more' in page.data and b'openAccountsPane' in page.data
          and b'see Accounts' in page.data,
          repr([token for token in (b'sync-health-more', b'openAccountsPane', b'see Accounts')
                if token not in page.data]))
    check('and names the banks it cut instead of leaving them as a number',
          b'syncHealthOmittedNames' in page.data
          and b'more<template v-if="syncHealthOmittedNames.length">: ' in page.data
          and b'\xe2\x80\x94 see Accounts' in page.data,
          repr([token for token in (b'syncHealthOmittedNames',
                                    b'more<template v-if="syncHealthOmittedNames.length">: ',
                                    b'\xe2\x80\x94 see Accounts') if token not in page.data]))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'static', 'js', 'vuePlaid.js')) as script:
        vue_source = script.read()
    check('the dashboard script renders the capped list and counts the rest',
          'banner_institutions' in vue_source and 'syncHealthMoreInstitutions' in vue_source
          and 'openAccountsPane' in vue_source and 'syncHealthInstitutions' in vue_source,
          repr([token for token in ('banner_institutions', 'syncHealthMoreInstitutions',
                                    'openAccountsPane') if token not in vue_source]))
    check('the dashboard script names each cut bank, label and all',
          'banner_omitted_institutions' in vue_source
          and 'syncHealthOmittedInstitutions' in vue_source
          and 'syncHealthOmittedNames' in vue_source
          and "inst.institution_name + ' (' + inst.label + ')'" in vue_source,
          repr([token for token in ('banner_omitted_institutions', 'syncHealthOmittedInstitutions',
                                    'syncHealthOmittedNames',
                                    "inst.institution_name + ' (' + inst.label + ')'")
                if token not in vue_source]))
    check('the accounts pane still badges an account that has never transacted',
          "no_transactions: 'No data'" in vue_source,
          repr([line.strip() for line in vue_source.splitlines() if 'no_transactions' in line]))

    v1 = client.get('/api/v1/institutions').get_json() or {}
    v1_inst = {i['id']: i for i in v1.get('institutions', [])}
    check('v1 GET /institutions keeps the fields it already had',
          v1_inst[amex.id]['revoked'] is True
          and v1_inst[scotia.id]['requires_update'] is True
          and v1_inst[westjet_cred.id]['soft_disconnected'] is False,
          repr(v1_inst.get(westjet_cred.id)))
    check('v1 GET /institutions now carries last activity per institution',
          v1_inst[westjet_cred.id]['last_transaction_date']
          == (today - datetime.timedelta(days=87)).isoformat()
          and v1_inst[westjet_cred.id]['days_since_last_transaction'] == 87
          and v1_inst[westjet_cred.id]['needs_attention'] is True,
          repr({k: v1_inst.get(westjet_cred.id, {}).get(k)
                for k in ('last_transaction_date', 'days_since_last_transaction',
                          'expected_tx_per_month', 'needs_attention')}))
    check('v1 names the silent accounts under a bank, with mask and cadence',
          v1_inst[westjet_cred.id]['silent_accounts'][0]['mask'] == '9669'
          and v1_inst[westjet_cred.id]['silent_accounts'][0]['expected_tx_per_month'] == 0.0,
          repr(v1_inst.get(westjet_cred.id, {}).get('silent_accounts')))
    v1_accounts = {a['id']: a for i in v1.get('institutions', []) for a in i['accounts']}
    check('v1 carries the same fields per account, including the threshold it was judged against',
          v1_accounts[westjet.id]['sync_status'] == REASON_NO_RECENT_ACTIVITY
          and v1_accounts[westjet.id]['silent_after_days'] == 15
          and v1_accounts[healthy.id]['sync_status'] == 'healthy'
          and v1_accounts[healthy.id]['needs_attention'] is False,
          repr(v1_accounts.get(westjet.id)))
    check('v1 reports a CSV-only bank as CSV-only rather than disconnected',
          v1_inst[csv_live_cred.id]['csv_only'] is True
          and v1_inst[csv_live_cred.id]['sync_status'] == 'healthy'
          and v1_inst[csv_quiet_cred.id]['sync_status'] == REASON_NO_RECENT_ACTIVITY,
          repr(v1_inst.get(csv_quiet_cred.id)))
    check('v1 marks a credential left behind by a re-connection as superseded',
          v1_inst[reconnected_dead_again.id]['superseded'] is True
          and v1_inst[reconnected_dead_again.id]['revoked'] is True
          and v1_inst[reconnected_dead.id]['superseded'] is False
          and v1_inst[reconnected_live.id]['superseded'] is False,
          repr([(i['institution_name'], i.get('superseded'))
                for i in v1.get('institutions', []) if 'Reconnected' in i['institution_name']]))
    check('v1 sorts the banks that need attention first',
          [i['needs_attention'] for i in v1.get('institutions', [])]
          == sorted([i['needs_attention'] for i in v1.get('institutions', [])], reverse=True),
          repr([(i['institution_name'], i['needs_attention'])
                for i in v1.get('institutions', [])]))
    check('v1 lists the banks in the same urgency order the banner uses',
          [i['id'] for i in v1.get('institutions', []) if i['id'] in inst_by_id]
          == [i['id'] for i in report['institutions']
              if i['id'] in {inst['id'] for inst in v1.get('institutions', [])}],
          repr([(i['institution_name'], i['sync_status'], i['needs_attention'])
                for i in v1.get('institutions', [])]))
    check('v1 answers the same way through an X-API-Key',
          (client.get('/api/v1/institutions', headers=api_headers).get_json() or {})
          .get('institutions')[0]['id'] == v1['institutions'][0]['id'],
          str((client.get('/api/v1/institutions', headers=api_headers).get_json() or {})
              .get('institutions', [])[:1]))
    check('the daily report gets its counts from v1 too',
          (v1.get('sync_health_summary') or {}).get('alert_count') == health.get('alert_count'),
          repr(v1.get('sync_health_summary')))

    other = client.get('/api/v1/institutions', headers={'X-API-Key': 'exm_not_a_key_at_all'})
    check('a bogus key is still rejected', other.status_code == 401, str(other.status_code))

    # ------------------------------------------- the Hermes daily report
    # The report reads v1 /institutions, so what matters is that it turns this
    # payload into lines that name the card.  Its own functions are fed the
    # payload from above — running the report itself would POST /sync to PROD.
    hermes_path = os.path.expanduser('~/.hermes/scripts/exmint_daily_report.py')
    if os.path.exists(hermes_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location('exmint_daily_report', hermes_path)
        daily = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daily)

        bank_lines, quiet_accounts = daily.bank_connections(v1.get('institutions', []), set())
        rendered = daily.quiet_account_lines(quiet_accounts)
        check('the daily report names the quiet cards that v1 now publishes',
              any('9669' in line for line in rendered)
              and any('reads low' in line for line in rendered),
              repr(rendered))
        check('the daily report still shows a bank that is simply fine',
              any(line.startswith('✅ Healthy Bank') for line in bank_lines), repr(bank_lines))
        check('the leftover credential of a re-connected bank does not call it disconnected',
              not any('❌' in line and 'Reconnected Bank' in line for line in bank_lines)
              and any('Reconnected Bank' in line and 'last data' in line
                      for line in bank_lines),
              repr([line for line in bank_lines if 'Reconnected Bank' in line]))
        check('one fine credential does not hide the sibling that needs a reconnect',
              any(line.startswith('⚠️ needs refresh/connection issue Reconnected Bank')
                  and 'last data' in line for line in bank_lines)
              and sum(1 for line in bank_lines if ' Reconnected Bank' in line) == 1,
              repr([line for line in bank_lines if 'Reconnected Bank' in line]))
        check('a card lost on re-connection is still named under the bank that works',
              any('Card Lost On Reconnect' in line for line in rendered), repr(rendered))
        check('a disconnected bank carries its last data date',
              any(line.startswith('❌ disconnected RBC Royal Bank') and 'last data' in line
                  for line in bank_lines), repr(bank_lines))
        check('a bank with nothing to report adds no quiet lines',
              daily.quiet_account_lines([]) == []
              and daily.connection_freshness({'csv_only': True}) == '',
              repr(daily.quiet_account_lines([])))
    else:
        print('\n(note) %s is not on this machine — the daily-report rendering '
              'check was skipped.' % hermes_path)

    # ------------------------------------------------- the real 2026-10-22 rows
    copy_uri = os.environ.get('EXMINT_SYNC_HEALTH_PROD_COPY')
    if copy_uri:
        if '_prd_db' in copy_uri or 'prd' in copy_uri.split('/')[-1]:
            print('ABORT — EXMINT_SYNC_HEALTH_PROD_COPY must point at a copy, not at PROD')
            return False
        from flask import Flask
        copy_app = Flask('sync_health_prod_copy')
        copy_app.config['SQLALCHEMY_DATABASE_URI'] = copy_uri
        copy_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        copy_app.config['ENCRYPTION_KEY'] = app.config.get('ENCRYPTION_KEY')
        db.init_app(copy_app)
        with copy_app.app_context():
            copy_users = [c.user_id for c in Credential.query.all()]
            copy_reports = {}
            flagged = {}
            for uid in sorted(set(copy_users)):
                copy_report = collect_sync_health(uid)
                copy_reports[uid] = copy_report
                for a in copy_report['alerts']:
                    flagged['%s %s' % (a['institution_name'], a['mask'] or '')] = a
            print('\n--- read-only copy of PROD: %d flagged accounts ---' % len(flagged))
            for key in sorted(flagged):
                rec = flagged[key]
                print('    %-45s %-22s %s (%s days quiet, expected %s/month)'
                      % (rec['institution_name'], rec['account_name'] or '',
                         rec['last_transaction_date'] or 'no data',
                         rec['days_since_last_transaction'], rec['expected_tx_per_month']))

            # What the banner actually shows each reader: the capped lines, then
            # the names it cut.  Printed here because it is the one place the
            # real 2026-10-22 rows exist.
            for uid in sorted(copy_reports):
                report_copy = copy_reports[uid]
                shown = report_copy['banner_institutions']
                cut = report_copy['banner_omitted_institutions']
                if not shown and not cut:
                    continue
                print('\n--- user %d: banner shows %d of %d institutions needing attention '
                      '(limit %d) ---'
                      % (uid, len(shown), report_copy['alert_institution_count'],
                         BANNER_INSTITUTION_LIMIT))
                for rank, inst in enumerate(shown, start=1):
                    print('    banner %d. %s (%s) [%s] — %s'
                          % (rank, inst['institution_name'], inst['label'] or 'no label',
                             inst['status'], inst['headline']))
                for inst in cut:
                    print('    cut:  %s (%s) [%s]'
                          % (inst['institution_name'], inst['label'] or 'no label', inst['status']))

            def _named_on_banner(uid):
                report_copy = copy_reports.get(uid) or {}
                names = [inst['institution_name'] for inst in report_copy.get('banner_institutions', [])]
                names += [inst['institution_name'] for inst in report_copy.get('banner_omitted_institutions', [])]
                return names

            def _named_with_label(uid):
                report_copy = copy_reports.get(uid) or {}
                lines = ['%s (%s)' % (i['institution_name'], i['label'])
                         if i['label'] else i['institution_name']
                         for i in (report_copy.get('banner_institutions', [])
                                   + report_copy.get('banner_omitted_institutions', []))]
                return lines

            for uid in sorted(copy_reports):
                if not copy_reports[uid]['banner_institutions'] and not copy_reports[uid]['banner_omitted_institutions']:
                    continue
                check('PROD copy: user %d gets every flagged institution named by the banner '
                      'or its cut list' % uid,
                      len(_named_on_banner(uid)) == copy_reports[uid]['alert_institution_count'],
                      repr((copy_reports[uid]['alert_institution_count'], _named_on_banner(uid))))
            manuel_report = copy_reports.get(2) or {}
            manuel_named = _named_with_label(2)
            manuel_ids = ([i['id'] for i in manuel_report.get('banner_institutions', [])]
                          + [i['id'] for i in manuel_report.get('banner_omitted_institutions', [])])
            # The card, not just the bank: WestJet 9669 sits under RBC and Amex
            # 1008 under its own revoked credential, so each is named through the
            # institution that answers for it — banner line or cut list.
            def _answer_for(mask):
                return [inst for inst in manuel_report.get('institutions', [])
                        if any(acct['mask'] == mask for acct in inst.get('alert_accounts', []))]
            check('PROD copy (Manuel, user 2): the banks behind all four 2026-10-22 cases are named',
                  all(any(named.startswith(want) for named in manuel_named)
                      for want in ('Scotiabank', 'RBC Royal Bank', 'American Express')),
                  repr(manuel_named))
            check('PROD copy (Manuel, user 2): WestJet 9669 and Amex 1008 are each named by the banner '
                  'or by its cut list',
                  all(any(inst['id'] in manuel_ids for inst in _answer_for(mask))
                      for mask in ('9669', '1008'))
                  and bool(_answer_for('9669')) and bool(_answer_for('1008')),
                  repr({m: [(i['institution_name'], i['label'], i['status'],
                             i['id'] in manuel_ids) for i in _answer_for(m)]
                        for m in ('9669', '1008')}))
            check('PROD copy: Scotiabank is flagged for the reconnect it needs',
                  any(rec['institution_name'] == 'Scotiabank'
                      and REASON_REQUIRES_UPDATE in rec['reasons'] for rec in flagged.values()),
                  repr(sorted(flagged)))
            check('PROD copy: RBC is flagged as disconnected',
                  any(rec['institution_name'] == 'RBC Royal Bank'
                      and REASON_SOFT_DISCONNECTED in rec['reasons'] for rec in flagged.values()),
                  repr(sorted(flagged)))
            check('PROD copy: the WestJet card 9669 is flagged as silent',
                  'WestJet RBC World Elite Mastercard' in flagged
                  or any(rec['mask'] == '9669' for rec in flagged.values()),
                  repr(sorted(flagged)))
            check('PROD copy: the Amex card 1008 is flagged as revoked',
                  any(rec['mask'] == '1008' and REASON_REVOKED in rec['reasons']
                      for rec in flagged.values()),
                  repr(sorted(flagged)))
    else:
        print('\n(note) EXMINT_SYNC_HEALTH_PROD_COPY is not set — the live PROD-copy '
              'check of the four 2026-10-22 rows was skipped.')

    # ----------------------------------------------------------------- cleanup
    with app.app_context():
        Transaction.query.filter(Transaction.user_id == state['user_id']).delete()
        Account.query.filter(Account.credential_id.in_(state['cred_ids'])).delete()
        Credential.query.filter(Credential.id.in_(state['cred_ids'])).delete()
        ApiKey.query.filter_by(id=state['key_id']).delete()
        db.session.delete(db.session.get(User, state['user_id']))
        db.session.commit()

        left = (Transaction.query.filter(Transaction.user_id == state['user_id']).count()
                + Account.query.join(Credential).filter(
                    Credential.user_id == state['user_id']).count()
                + Credential.query.filter(Credential.user_id == state['user_id']).count()
                + ApiKey.query.filter_by(user_id=state['user_id']).count()
                + (1 if db.session.get(User, state['user_id']) else 0))
        check('every row this test created is gone', left == 0, repr(left))

    return not _FAILURES


if __name__ == '__main__':
    ok = main()
    print('\n%d passed, %d failed' % (len(_PASSES), len(_FAILURES)))
    sys.exit(0 if ok else 1)
