"""Add unique constraint on credential(user_id, item_id) to prevent duplicate bank connections

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18

"""
from alembic import op

revision = 'd4e5f6a7b8c9'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_credential_user_item_id', ['user_id', 'item_id'])


def downgrade():
    with op.batch_alter_table('credential', schema=None) as batch_op:
        batch_op.drop_constraint('uq_credential_user_item_id', type_='unique')
