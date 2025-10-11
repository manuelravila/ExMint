"""Add transactions table and cursor to credential

Revision ID: 3f6e4ce1a23b
Revises: 1458f4e38d80
Create Date: 2025-02-23 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f6e4ce1a23b'
down_revision = '2726a7f8ddc1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plaid_transaction_id', sa.String(length=100), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('credential_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('iso_currency_code', sa.String(length=10), nullable=True),
        sa.Column('category', sa.Text(), nullable=True),
        sa.Column('merchant_name', sa.String(length=255), nullable=True),
        sa.Column('payment_channel', sa.String(length=50), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('pending', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_removed', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_action', sa.String(length=20), nullable=False, server_default='added'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ),
        sa.ForeignKeyConstraint(['credential_id'], ['credential.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_account_id'), 'transactions', ['account_id'], unique=False)
    op.create_index(op.f('ix_transactions_plaid_transaction_id'), 'transactions', ['plaid_transaction_id'], unique=True)
    op.create_index(op.f('ix_transactions_user_id'), 'transactions', ['user_id'], unique=False)

    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transactions_cursor', sa.String(length=512), nullable=True))


def downgrade():
    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.drop_column('transactions_cursor')

    op.drop_index(op.f('ix_transactions_user_id'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_plaid_transaction_id'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_account_id'), table_name='transactions')
    op.drop_table('transactions')
