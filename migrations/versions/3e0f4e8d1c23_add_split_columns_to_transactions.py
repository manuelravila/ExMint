"""add split columns to transactions

Revision ID: 3e0f4e8d1c23
Revises: 8f1b4ad8f6e1
Create Date: 2025-01-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e0f4e8d1c23'
down_revision = '8f1b4ad8f6e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('parent_transaction_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('is_split_child', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.add_column('transactions', sa.Column('has_split_children', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.create_index(
        'ix_transactions_parent_transaction_id',
        'transactions',
        ['parent_transaction_id']
    )
    op.create_foreign_key(
        'fk_transactions_parent_transaction',
        'transactions',
        'transactions',
        ['parent_transaction_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.alter_column('transactions', 'is_split_child', server_default=None)
    op.alter_column('transactions', 'has_split_children', server_default=None)


def downgrade():
    op.drop_constraint('fk_transactions_parent_transaction', 'transactions', type_='foreignkey')
    op.drop_index('ix_transactions_parent_transaction_id', table_name='transactions')
    op.drop_column('transactions', 'has_split_children')
    op.drop_column('transactions', 'is_split_child')
    op.drop_column('transactions', 'parent_transaction_id')
