"""split custom categories from rules

Revision ID: b671a97a0ad1
Revises: 15969fc642c3
Create Date: 2025-10-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.sql import func
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'b671a97a0ad1'
down_revision = '15969fc642c3'
branch_labels = None
depends_on = None


DEFAULT_CATEGORY_COLOR = '#2C6B4F'


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    inspector = sa.inspect(bind)

    table_names = inspector.get_table_names()

    if 'category_rules' not in table_names and 'categories' in table_names:
        op.rename_table('categories', 'category_rules')
    elif 'category_rules' not in table_names:
        # Neither table exists; nothing to do.
        return

    if not inspector.has_table('custom_categories'):
        op.create_table(
            'custom_categories',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('color', sa.String(length=7), nullable=False, server_default=sa.text("'#2C6B4F'")),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.UniqueConstraint('user_id', 'name', name='uq_custom_categories_user_name')
        )

    category_rule_columns = {column['name'] for column in inspector.get_columns('category_rules')}

    if 'category_id' not in category_rule_columns:
        with op.batch_alter_table('category_rules', schema=None) as batch_op:
            batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))

    override_columns = {column['name'] for column in inspector.get_columns('transaction_category_override')}
    if 'custom_category_id' not in override_columns:
        with op.batch_alter_table('transaction_category_override', schema=None) as batch_op:
            batch_op.add_column(sa.Column('custom_category_id', sa.Integer(), nullable=True))

    transaction_fk_names = [
        fk['name']
        for fk in inspector.get_foreign_keys('transactions')
        if fk.get('referred_table') in {'categories', 'category_rules'}
    ]
    for fk_name in transaction_fk_names:
        op.drop_constraint(fk_name, 'transactions', type_='foreignkey')
    # defer adding the new foreign key until after data migration

    metadata.reflect(bind=bind, only=[
        'category_rules',
        'custom_categories',
        'transactions',
        'transaction_category_override'
    ])

    category_rules = metadata.tables['category_rules']
    custom_categories = metadata.tables['custom_categories']
    transactions = metadata.tables['transactions']
    overrides = metadata.tables['transaction_category_override']

    category_map = {}
    rule_to_category = {}
    now = datetime.utcnow()

    session = orm.Session(bind=bind)

    existing_categories = session.execute(
        sa.select(
            custom_categories.c.id,
            custom_categories.c.user_id,
            custom_categories.c.name,
            custom_categories.c.color
        )
    ).all()
    for cat in existing_categories:
        key = (cat.user_id, (cat.name or '').strip().lower())
        if key and key[1]:
            category_map[key] = cat.id

    for rule in session.execute(sa.select(
        category_rules.c.id,
        category_rules.c.user_id,
        category_rules.c.label,
        category_rules.c.color
    )):
        label = (rule.label or '').strip()
        if not label:
            label = f'Rule {rule.id}'
        key = (rule.user_id, label.lower())
        category_id = category_map.get(key)
        if category_id is None:
            color_value = rule.color or DEFAULT_CATEGORY_COLOR
            insert_result = session.execute(
                custom_categories.insert().values(
                    user_id=rule.user_id,
                    name=label,
                    color=color_value,
                    created_at=now,
                    updated_at=now
                )
            )
            category_id = insert_result.inserted_primary_key[0]
            category_map[key] = category_id
        rule_to_category[rule.id] = category_id

    for rule_id, category_id in rule_to_category.items():
        session.execute(
            category_rules.update()
            .where(category_rules.c.id == rule_id)
            .values(category_id=category_id)
        )

    for txn in session.execute(sa.select(
        transactions.c.id,
        transactions.c.custom_category_id
    )):
        old_rule_id = txn.custom_category_id
        if old_rule_id is None:
            continue
        new_category_id = rule_to_category.get(old_rule_id)
        session.execute(
            transactions.update()
            .where(transactions.c.id == txn.id)
            .values(custom_category_id=new_category_id)
        )

    override_query = sa.select(
        overrides.c.transaction_id,
        overrides.c.label,
        overrides.c.color,
        transactions.c.user_id
    ).join(transactions, transactions.c.id == overrides.c.transaction_id)

    for override in session.execute(override_query):
        label = (override.label or '').strip()
        if not label:
            session.execute(
                overrides.delete().where(overrides.c.transaction_id == override.transaction_id)
            )
            continue
        key = (override.user_id, label.lower())
        category_id = category_map.get(key)
        if category_id is None:
            color_value = override.color or DEFAULT_CATEGORY_COLOR
            insert_result = session.execute(
                custom_categories.insert().values(
                    user_id=override.user_id,
                    name=label,
                    color=color_value,
                    created_at=now,
                    updated_at=now
                )
            )
            category_id = insert_result.inserted_primary_key[0]
            category_map[key] = category_id
        session.execute(
            overrides.update()
            .where(overrides.c.transaction_id == override.transaction_id)
            .values(custom_category_id=category_id)
        )

    session.flush()

    inspector = sa.inspect(bind)

    override_fk_names = {
        fk['name'] for fk in inspector.get_foreign_keys('transaction_category_override') if fk.get('name')
    }
    with op.batch_alter_table('transaction_category_override', schema=None) as batch_op:
        for column in ('label', 'color'):
            if column in inspector.get_columns('transaction_category_override'):
                batch_op.drop_column(column)
        if 'fk_override_custom_category' in override_fk_names:
            batch_op.drop_constraint('fk_override_custom_category', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_override_custom_category',
            'custom_categories',
            ['custom_category_id'],
            ['id'],
            ondelete='SET NULL'
        )

    rule_fk_names = {
        fk['name'] for fk in inspector.get_foreign_keys('category_rules') if fk.get('name')
    }
    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        for column in ('label', 'color'):
            if column in inspector.get_columns('category_rules'):
                batch_op.drop_column(column)
        batch_op.alter_column('category_id', existing_type=sa.Integer(), nullable=False)
        if 'fk_category_rules_custom_category' in rule_fk_names:
            batch_op.drop_constraint('fk_category_rules_custom_category', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_category_rules_custom_category',
            'custom_categories',
            ['category_id'],
            ['id'],
            ondelete='CASCADE'
        )

    session.commit()
    session.close()

    inspector = sa.inspect(bind)

    existing_transaction_fks = {
        fk['name'] for fk in inspector.get_foreign_keys('transactions') if fk.get('name')
    }
    if 'fk_transactions_custom_category' not in existing_transaction_fks:
        op.create_foreign_key(
            'fk_transactions_custom_category',
            'transactions',
            'custom_categories',
            ['custom_category_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()

    inspector = sa.inspect(bind)

    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('color', sa.String(length=7), nullable=True, server_default=DEFAULT_CATEGORY_COLOR))

    metadata.reflect(bind=bind, only=[
        'category_rules',
        'custom_categories',
        'transactions',
        'transaction_category_override'
    ])

    category_rules = metadata.tables['category_rules']
    custom_categories = metadata.tables['custom_categories']
    transactions = metadata.tables['transactions']
    overrides = metadata.tables['transaction_category_override']

    session = orm.Session(bind=bind)

    for rule in session.execute(sa.select(
        category_rules.c.id,
        category_rules.c.category_id
    )):
        if rule.category_id is None:
            continue
        category = session.execute(
            sa.select(custom_categories.c.name, custom_categories.c.color)
            .where(custom_categories.c.id == rule.category_id)
        ).first()
        if category:
            session.execute(
                category_rules.update()
                .where(category_rules.c.id == rule.id)
                .values(label=category.name, color=category.color)
            )

    rule_category_map = {
        row.id: row.category_id for row in session.execute(
            sa.select(category_rules.c.id, category_rules.c.category_id)
        )
    }
    category_rule_map = {}
    for rule_id, category_id in rule_category_map.items():
        if category_id is not None:
            category_rule_map.setdefault(category_id, []).append(rule_id)

    for txn in session.execute(sa.select(
        transactions.c.id,
        transactions.c.custom_category_id
    )):
        category_id = txn.custom_category_id
        target_rule_id = None
        if category_id is not None:
            rule_ids = category_rule_map.get(category_id)
            if rule_ids:
                target_rule_id = rule_ids[0]
        session.execute(
            transactions.update()
            .where(transactions.c.id == txn.id)
            .values(custom_category_id=target_rule_id)
        )

    with op.batch_alter_table('transaction_category_override', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('color', sa.String(length=7), nullable=True))

    override_query = sa.select(
        overrides.c.transaction_id,
        overrides.c.custom_category_id,
        transactions.c.user_id
    ).join(transactions, transactions.c.id == overrides.c.transaction_id)

    for override in session.execute(override_query):
        category_id = override.custom_category_id
        if category_id is None:
            session.execute(
                overrides.delete().where(overrides.c.transaction_id == override.transaction_id)
            )
            continue
        category = session.execute(
            sa.select(custom_categories.c.name, custom_categories.c.color)
            .where(custom_categories.c.id == category_id)
        ).first()
        if category:
            session.execute(
                overrides.update()
                .where(overrides.c.transaction_id == override.transaction_id)
                .values(label=category.name, color=category.color)
            )

    session.flush()

    override_fk_names = {
        fk['name'] for fk in inspector.get_foreign_keys('transaction_category_override') if fk.get('name')
    }
    with op.batch_alter_table('transaction_category_override', schema=None) as batch_op:
        if 'fk_override_custom_category' in override_fk_names:
            batch_op.drop_constraint('fk_override_custom_category', type_='foreignkey')
        batch_op.drop_column('custom_category_id')

    rule_fk_names = {
        fk['name'] for fk in inspector.get_foreign_keys('category_rules') if fk.get('name')
    }
    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        if 'fk_category_rules_custom_category' in rule_fk_names:
            batch_op.drop_constraint('fk_category_rules_custom_category', type_='foreignkey')
        batch_op.drop_column('category_id')

    session.commit()

    fk_names = [
        fk['name']
        for fk in inspector.get_foreign_keys('transactions')
        if fk.get('referred_table') == 'custom_categories'
    ]
    for fk_name in fk_names:
        op.drop_constraint(fk_name, 'transactions', type_='foreignkey')

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_transactions_category',
            'category_rules',
            ['custom_category_id'],
            ['id'],
            ondelete='SET NULL'
        )

    op.drop_table('custom_categories')

    session.close()

    op.rename_table('category_rules', 'categories')
