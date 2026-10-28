"""Add AI-assigned expense categories.

Revision ID: 0002_expense_categories
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_expense_categories"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    invoice_columns = {column["name"] for column in sa.inspect(bind).get_columns("invoices")}
    if "category" not in invoice_columns:
        op.add_column("invoices", sa.Column("category", sa.String(length=40), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("invoices")}
    if "ix_invoices_user_category" not in indexes:
        op.create_index("ix_invoices_user_category", "invoices", ["user_id", "category"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("invoices")}
    if "ix_invoices_user_category" in indexes:
        op.drop_index("ix_invoices_user_category", table_name="invoices")
    invoice_columns = {column["name"] for column in sa.inspect(bind).get_columns("invoices")}
    if "category" in invoice_columns:
        op.drop_column("invoices", "category")
