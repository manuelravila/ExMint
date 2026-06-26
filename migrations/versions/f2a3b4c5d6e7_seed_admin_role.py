"""Set role='Admin' for the user whose email matches ADMIN_EMAIL env var

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-29

"""
import os
from alembic import op
from sqlalchemy import text

revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    admin_email = os.environ.get('ADMIN_EMAIL', '').strip()
    if not admin_email:
        print('ADMIN_EMAIL not set — skipping admin role seed.')
        return
    conn = op.get_bind()
    result = conn.execute(
        text("UPDATE user SET role = 'Admin' WHERE email = :email"),
        {'email': admin_email}
    )
    if result.rowcount:
        print(f'Admin role granted to {admin_email}.')
    else:
        print(f'ADMIN_EMAIL={admin_email!r} not found in user table — role not set. '
              'Create the account first, then re-run flask db upgrade or update manually.')


def downgrade():
    admin_email = os.environ.get('ADMIN_EMAIL', '').strip()
    if not admin_email:
        return
    conn = op.get_bind()
    conn.execute(
        text("UPDATE user SET role = 'User' WHERE email = :email AND role = 'Admin'"),
        {'email': admin_email}
    )
