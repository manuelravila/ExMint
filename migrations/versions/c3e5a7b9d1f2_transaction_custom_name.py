"""User description on a transaction (transactions.custom_name)

The bank's description stays in ``name``; ``custom_name`` is what the user typed
and is shown instead of it. Category rules and duplicate checks keep reading
``name``.

Revision ID: c3e5a7b9d1f2
Revises: b8d2f0e3c4a5
Create Date: 2026-10-10

"""
import sqlalchemy as sa
from alembic import op

revision = 'c3e5a7b9d1f2'
down_revision = 'b8d2f0e3c4a5'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('transactions')}
    if 'custom_name' not in columns:
        op.add_column('transactions', sa.Column('custom_name', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('transactions', 'custom_name')
