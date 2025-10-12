"""Add transaction category override table

Revision ID: 8f1b4ad8f6e1
Revises: 7a8b8c4f9acd
Create Date: 2025-05-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f1b4ad8f6e1'
down_revision = '7a8b8c4f9acd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'transaction_category_override',
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('transaction_id')
    )


def downgrade():
    op.drop_table('transaction_category_override')
