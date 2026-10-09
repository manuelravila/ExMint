"""Link a custom category to a project (custom_categories.project_id)

Revision ID: b8d2f0e3c4a5
Revises: a7c1e9d2b3f4
Create Date: 2026-10-09

"""
import sqlalchemy as sa
from alembic import op

revision = 'b8d2f0e3c4a5'
down_revision = 'a7c1e9d2b3f4'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('custom_categories')}
    if 'project_id' not in columns:
        op.add_column('custom_categories', sa.Column('project_id', sa.Integer(), nullable=True))
        op.create_index('ix_custom_categories_project_id', 'custom_categories', ['project_id'])
        op.create_foreign_key('fk_custom_categories_project_id', 'custom_categories', 'projects',
                              ['project_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_custom_categories_project_id', 'custom_categories', type_='foreignkey')
    op.drop_index('ix_custom_categories_project_id', table_name='custom_categories')
    op.drop_column('custom_categories', 'project_id')
