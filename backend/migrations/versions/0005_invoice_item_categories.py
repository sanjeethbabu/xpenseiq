"""Add categories to individual invoice items."""

from alembic import op
import sqlalchemy as sa


revision = "0005_invoice_item_categories"
down_revision = "0004_approved_duplicate_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("invoice_items")}
    if "category" not in columns:
        op.add_column("invoice_items", sa.Column("category", sa.String(length=40), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("invoice_items")}
    if "category" in columns:
        op.drop_column("invoice_items", "category")
