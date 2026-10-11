"""Several projects per transaction and per category

transaction_projects / category_projects replace transactions.project_id and
custom_categories.project_id (copied over; the old columns are left in place
and no longer read, so an older release still finds its data).

Revision ID: d4f6b8c0e2a3
Revises: c3e5a7b9d1f2
Create Date: 2026-10-10

"""
import sqlalchemy as sa
from alembic import op

revision = 'd4f6b8c0e2a3'
down_revision = 'c3e5a7b9d1f2'
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'transaction_projects' not in tables:
        op.create_table(
            'transaction_projects',
            sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transactions.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
        )
        op.create_index('ix_transaction_projects_project_id', 'transaction_projects', ['project_id'])
        op.execute('INSERT INTO transaction_projects (transaction_id, project_id) '
                   'SELECT id, project_id FROM transactions WHERE project_id IS NOT NULL')
    if 'category_projects' not in tables:
        op.create_table(
            'category_projects',
            sa.Column('category_id', sa.Integer(), sa.ForeignKey('custom_categories.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
        )
        op.create_index('ix_category_projects_project_id', 'category_projects', ['project_id'])
        op.execute('INSERT INTO category_projects (category_id, project_id) '
                   'SELECT id, project_id FROM custom_categories WHERE project_id IS NOT NULL')


def downgrade():
    # Give the old single-project columns one project back (the smallest id).
    op.execute('UPDATE transactions SET project_id = (SELECT MIN(tp.project_id) FROM transaction_projects tp '
               'WHERE tp.transaction_id = transactions.id)')
    op.execute('UPDATE custom_categories SET project_id = (SELECT MIN(cp.project_id) FROM category_projects cp '
               'WHERE cp.category_id = custom_categories.id)')
    op.drop_index('ix_category_projects_project_id', table_name='category_projects')
    op.drop_table('category_projects')
    op.drop_index('ix_transaction_projects_project_id', table_name='transaction_projects')
    op.drop_table('transaction_projects')
