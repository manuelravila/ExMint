"""Add app_settings table for admin-controlled feature flags

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-03-29

"""
import sqlalchemy as sa
from alembic import op

revision = 'e1f2a3b4c5d6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.String(500), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    # Seed default: registration is open
    op.execute("INSERT INTO app_settings (key, value) VALUES ('registration_open', 'true')")


def downgrade():
    op.drop_table('app_settings')
