"""Placeholder migration for missing revision 2726a7f8ddc1

Revision ID: 2726a7f8ddc1
Revises: 1458f4e38d80
Create Date: 2025-02-23 20:15:00.000000

This migration was reconstructed to bridge environments that have already
applied the original 2726a7f8ddc1 changes but no longer have the script in
source control. The upgrade/downgrade are intentionally left empty.
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = '2726a7f8ddc1'
down_revision = '1458f4e38d80'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
