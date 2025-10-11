"""Add transactions user/date index

Revision ID: 6cf4c3f10b27
Revises: 3f6e4ce1a23b
Create Date: 2025-03-06 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '6cf4c3f10b27'
down_revision = '3f6e4ce1a23b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_transactions_user_date_id',
        'transactions',
        ['user_id', 'date', 'id'],
        unique=False
    )


def downgrade():
    op.drop_index('ix_transactions_user_date_id', table_name='transactions')
