"""Add projects table and transactions.project_id

Revision ID: a7c1e9d2b3f4
Revises: 3bd3f299d244
Create Date: 2026-10-09

"""
import sqlalchemy as sa
from alembic import op

revision = 'a7c1e9d2b3f4'
down_revision = '3bd3f299d244'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Idempotent: a partial earlier run may have created either part already.
    if not inspector.has_table('projects'):
        op.create_table(
            'projects',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('color', sa.String(7), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'name', name='uq_projects_user_name'),
        )
        op.create_index('ix_projects_user_id', 'projects', ['user_id'])

    columns = {c['name'] for c in inspector.get_columns('transactions')}
    if 'project_id' not in columns:
        op.add_column('transactions', sa.Column('project_id', sa.Integer(), nullable=True))
        op.create_index('ix_transactions_project_id', 'transactions', ['project_id'])
        op.create_foreign_key('fk_transactions_project_id', 'transactions', 'projects',
                              ['project_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_transactions_project_id', 'transactions', type_='foreignkey')
    op.drop_index('ix_transactions_project_id', table_name='transactions')
    op.drop_column('transactions', 'project_id')
    op.drop_index('ix_projects_user_id', table_name='projects')
    op.drop_table('projects')
