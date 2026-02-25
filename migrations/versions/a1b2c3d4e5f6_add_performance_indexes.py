"""Add performance indexes on frequently queried columns

Revision ID: a1b2c3d4e5f6
Revises: 829f0fd09626
Create Date: 2026-02-25

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '829f0fd09626'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.create_index('ix_transactions_user_id', ['user_id'])
        batch_op.create_index('ix_transactions_date', ['date'])
        batch_op.create_index('ix_transactions_user_date', ['user_id', 'date'])
        batch_op.create_index('ix_transactions_is_removed', ['is_removed'])
        batch_op.create_index('ix_transactions_user_is_removed', ['user_id', 'is_removed'])

    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.create_index('ix_category_rules_user_id', ['user_id'])

    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.create_index('ix_credential_user_id', ['user_id'])

    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.create_index('ix_account_credential_id', ['credential_id'])


def downgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_index('ix_account_credential_id')

    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.drop_index('ix_credential_user_id')

    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.drop_index('ix_category_rules_user_id')

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index('ix_transactions_user_is_removed')
        batch_op.drop_index('ix_transactions_is_removed')
        batch_op.drop_index('ix_transactions_user_date')
        batch_op.drop_index('ix_transactions_date')
        batch_op.drop_index('ix_transactions_user_id')
