"""Add categories table and custom category reference on transactions

Revision ID: 7a8b8c4f9acd
Revises: 6cf4c3f10b27
Create Date: 2025-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '7a8b8c4f9acd'
down_revision = '6cf4c3f10b27'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    created_categories = False
    if 'categories' not in existing_tables:
        op.create_table(
            'categories',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('label', sa.String(length=255), nullable=False),
            sa.Column('text_to_match', sa.String(length=512), nullable=False),
            sa.Column('field_to_match', sa.String(length=50), nullable=False, server_default=text("'description'")),
            sa.Column('transaction_type', sa.String(length=20), nullable=True),
            sa.Column('amount_min', sa.Numeric(14, 2), nullable=True),
            sa.Column('amount_max', sa.Numeric(14, 2), nullable=True),
            sa.Column('color', sa.String(length=7), nullable=False, server_default=text("'#2C6B4F'")),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column(
                'updated_at',
                sa.DateTime(),
                nullable=False,
                server_default=text('CURRENT_TIMESTAMP'),
                server_onupdate=text('CURRENT_TIMESTAMP')
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_categories_user_id', ondelete='CASCADE')
        )
        created_categories = True
    else:
        columns = {column['name'] for column in inspector.get_columns('categories')}
        if 'color' not in columns:
            op.add_column(
                'categories',
                sa.Column('color', sa.String(length=7), nullable=False, server_default=text("'#2C6B4F'"))
            )
            # ensure existing rows have a value and, once set, drop the default for cleanliness
            op.execute(text("UPDATE categories SET color = '#2C6B4F' WHERE color IS NULL OR color = ''"))
        if 'field_to_match' in columns:
            op.execute(text(
                "ALTER TABLE categories MODIFY COLUMN field_to_match VARCHAR(50) NOT NULL DEFAULT 'description'"
            ))

    existing_tables = inspector.get_table_names()
    existing_indexes = {index['name'] for index in inspector.get_indexes('categories')} if 'categories' in existing_tables else set()

    if created_categories or 'ix_categories_user_created' not in existing_indexes:
        op.create_index('ix_categories_user_created', 'categories', ['user_id', 'created_at'], unique=False)
    if created_categories or 'ix_categories_user_label' not in existing_indexes:
        op.create_index('ix_categories_user_label', 'categories', ['user_id', 'label'], unique=False)

    txn_columns = set()
    if 'transactions' in existing_tables:
        txn_columns = {column['name'] for column in inspector.get_columns('transactions')}

    fk_added = False
    if 'custom_category_id' not in txn_columns:
        op.add_column('transactions', sa.Column('custom_category_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_transactions_custom_category_id',
            'transactions',
            'categories',
            ['custom_category_id'],
            ['id'],
            ondelete='SET NULL'
        )
        txn_columns.add('custom_category_id')
        fk_added = True

    fk_names = set()
    if 'transactions' in existing_tables:
        fk_names = {fk['name'] for fk in inspector.get_foreign_keys('transactions')}
    if 'custom_category_id' in txn_columns and 'fk_transactions_custom_category_id' not in fk_names and not fk_added:
        op.create_foreign_key(
            'fk_transactions_custom_category_id',
            'transactions',
            'categories',
            ['custom_category_id'],
            ['id'],
            ondelete='SET NULL'
        )

    txn_indexes = set()
    if 'transactions' in existing_tables:
        txn_indexes = {index['name'] for index in inspector.get_indexes('transactions')}
    if 'ix_transactions_user_custom_category' not in txn_indexes:
        op.create_index(
            'ix_transactions_user_custom_category',
            'transactions',
            ['user_id', 'custom_category_id'],
            unique=False
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'transactions' in existing_tables:
        txn_indexes = {index['name'] for index in inspector.get_indexes('transactions')}
        if 'ix_transactions_user_custom_category' in txn_indexes:
            op.drop_index('ix_transactions_user_custom_category', table_name='transactions')
        fk_names = {fk['name'] for fk in inspector.get_foreign_keys('transactions')}
        if 'fk_transactions_custom_category_id' in fk_names:
            op.drop_constraint('fk_transactions_custom_category_id', 'transactions', type_='foreignkey')
        txn_columns = {column['name'] for column in inspector.get_columns('transactions')}
        if 'custom_category_id' in txn_columns:
            op.drop_column('transactions', 'custom_category_id')

    if 'categories' in existing_tables:
        existing_indexes = {index['name'] for index in inspector.get_indexes('categories')}
        if 'ix_categories_user_label' in existing_indexes:
            op.drop_index('ix_categories_user_label', table_name='categories')
        if 'ix_categories_user_created' in existing_indexes:
            op.drop_index('ix_categories_user_created', table_name='categories')
        columns = {column['name'] for column in inspector.get_columns('categories')}
        if 'color' in columns:
            op.drop_column('categories', 'color')
        op.drop_table('categories')
