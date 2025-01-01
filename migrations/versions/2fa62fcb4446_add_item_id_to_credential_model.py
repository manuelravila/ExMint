from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '2fa62fcb4446'
down_revision = '59affccd63cd'
branch_labels = None
depends_on = None


def upgrade():
    # Check if the item_id column already exists
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('credential')]
    if 'item_id' not in columns:
        with op.batch_alter_table('credential', schema=None) as batch_op:
            batch_op.add_column(sa.Column('item_id', sa.String(length=100), nullable=False))


def downgrade():
    # Safely remove the column if it exists
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('credential')]
    if 'item_id' in columns:
        with op.batch_alter_table('credential', schema=None) as batch_op:
            batch_op.drop_column('item_id')
