"""Automatic balances: daily snapshots, closed accounts, Plaid fetch time

Adds account_balance_snapshots (one computed balance per account per day, the
debt history EX-01 reads), account.is_closed (a cancelled card keeps its
history but drops out of every total) and account.balance_fetched_at (when
current_balance last came from Plaid).

Revision ID: e7f2a4c6b8d1
Revises: d4f6b8c0e2a3
Create Date: 2026-10-25

"""
import sqlalchemy as sa
from alembic import op

revision = 'e7f2a4c6b8d1'
down_revision = 'd4f6b8c0e2a3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('account')}
    if 'balance_fetched_at' not in columns:
        op.add_column('account', sa.Column('balance_fetched_at', sa.DateTime(), nullable=True))
    if 'is_closed' not in columns:
        op.add_column('account', sa.Column('is_closed', sa.Boolean(), nullable=False,
                                           server_default=sa.text('0')))
        op.execute("UPDATE account SET is_closed = 0 WHERE is_closed IS NULL")

    if 'account_balance_snapshots' not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            'account_balance_snapshots',
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('account_id', sa.Integer(),
                      sa.ForeignKey('account.id', ondelete='CASCADE'), nullable=False),
            sa.Column('snapshot_date', sa.Date(), nullable=False),
            sa.Column('balance', sa.Numeric(14, 2), nullable=False),
            sa.Column('source', sa.String(16), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('account_id', 'snapshot_date', name='uq_account_balance_snapshot'),
        )
        op.create_index('ix_account_balance_snapshots_account_id',
                        'account_balance_snapshots', ['account_id'])
        op.create_index('ix_account_balance_snapshots_snapshot_date',
                        'account_balance_snapshots', ['snapshot_date'])


def downgrade():
    op.drop_index('ix_account_balance_snapshots_snapshot_date', table_name='account_balance_snapshots')
    op.drop_index('ix_account_balance_snapshots_account_id', table_name='account_balance_snapshots')
    op.drop_table('account_balance_snapshots')
    op.drop_column('account', 'is_closed')
    op.drop_column('account', 'balance_fetched_at')
