"""Add CsvImportTemplate

Revision ID: 7ebeaceee077
Revises: f2a3b4c5d6e7
Create Date: 2026-06-25 21:04:12.339466

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7ebeaceee077'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('csv_import_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('header_hash', sa.String(length=64), nullable=False),
    sa.Column('header_names', sa.Text(), nullable=False),
    sa.Column('mappings', sa.Text(), nullable=False),
    sa.Column('bank_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'label', name='uq_csv_template_user_label')
    )


def downgrade():
    op.drop_table('csv_import_templates')
