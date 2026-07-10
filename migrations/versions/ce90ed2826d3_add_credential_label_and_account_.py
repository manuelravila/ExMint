"""Add credential label and account balance columns

Revision ID: ce90ed2826d3
Revises: 3d1a785fd410
Create Date: 2026-07-10 16:40:14.370603

"""
from alembic import op
import sqlalchemy as sa
# revision identifiers, used by Alembic.
revision = 'ce90ed2826d3'
down_revision = '3d1a785fd410'
branch_labels = None
depends_on = None


def upgrade():
    # Add label column to credential
    op.add_column('credential', sa.Column('label', sa.String(length=100), nullable=True))

    # Add balance columns to account
    op.add_column('account', sa.Column('last_known_balance', sa.Numeric(14, 2), nullable=True))
    op.add_column('account', sa.Column('balance_date', sa.Date(), nullable=True))
    op.add_column('account', sa.Column('current_balance', sa.Numeric(14, 2), nullable=True))
    op.add_column('account', sa.Column('available_balance', sa.Numeric(14, 2), nullable=True))


def downgrade():
    op.drop_column('account', 'available_balance')
    op.drop_column('account', 'current_balance')
    op.drop_column('account', 'balance_date')
    op.drop_column('account', 'last_known_balance')
    op.drop_column('credential', 'label')
