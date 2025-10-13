"""create budgets table

Revision ID: 8c9b1b58e3cf
Revises: 3e0f4e8d1c23
Create Date: 2025-01-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c9b1b58e3cf'
down_revision = '3e0f4e8d1c23'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category_label', sa.String(length=255), nullable=False),
        sa.Column('frequency', sa.String(length=32), nullable=False, server_default='monthly'),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_budgets_user_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_budgets_user_id', 'budgets', ['user_id'])
    op.alter_column('budgets', 'frequency', server_default=None)


def downgrade():
    op.drop_index('ix_budgets_user_id', table_name='budgets')
    op.drop_table('budgets')
