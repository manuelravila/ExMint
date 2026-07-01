"""Add monthly_budgets table

Revision ID: 3d1a785fd410
Revises: 7ebeaceee077
Create Date: 2026-06-30 22:32:09.853056

"""
from alembic import op
import sqlalchemy as sa
from datetime import date


# revision identifiers, used by Alembic.
revision = '3d1a785fd410'
down_revision = '7ebeaceee077'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('monthly_budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category_label', sa.String(length=255), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'category_label', 'year', 'month', name='uq_monthly_budget')
    )

    # Migrate existing global budgets to monthly budgets
    # Current month + 24 months forward
    today = date.today()
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT user_id, category_label, amount FROM budgets")
    ).fetchall()

    if rows:
        now = sa.func.now()
        stmt = sa.text(
            """INSERT INTO monthly_budgets
               (user_id, category_label, year, month, amount, created_at, updated_at)
               VALUES (:user_id, :category_label, :year, :month, :amount, NOW(), NOW())"""
        )
        for user_id, category_label, amount in rows:
            for offset in range(0, 25):
                m = today.month + offset
                y = today.year + (m - 1) // 12
                m = ((m - 1) % 12) + 1
                connection.execute(
                    stmt,
                    {
                        "user_id": user_id,
                        "category_label": category_label,
                        "year": y,
                        "month": m,
                        "amount": amount,
                    }
                )


def downgrade():
    op.drop_table('monthly_budgets')
