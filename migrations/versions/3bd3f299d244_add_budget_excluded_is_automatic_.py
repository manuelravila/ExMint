"""add budget_excluded is_automatic rollover_amount

Revision ID: 3bd3f299d244
Revises: ce90ed2826d3
Create Date: 2026-07-13 12:43:21.773942

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '3bd3f299d244'
down_revision = 'ce90ed2826d3'
branch_labels = None
depends_on = None


def upgrade():
    # --- custom_categories.budget_excluded ---
    with op.batch_alter_table('custom_categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('budget_excluded', sa.Boolean(), nullable=False, server_default=sa.text('0')))

    # --- monthly_budgets.is_automatic + rollover_amount ---
    with op.batch_alter_table('monthly_budgets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_automatic', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('rollover_amount', sa.Numeric(14, 2), nullable=False, server_default=sa.text('0.00')))


def downgrade():
    with op.batch_alter_table('monthly_budgets', schema=None) as batch_op:
        batch_op.drop_column('rollover_amount')
        batch_op.drop_column('is_automatic')

    with op.batch_alter_table('custom_categories', schema=None) as batch_op:
        batch_op.drop_column('budget_excluded')
