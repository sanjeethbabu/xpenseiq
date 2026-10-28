"""Store approval to process same-name invoices in another format.

Revision ID: 0004_approved_duplicate_invoices
Revises: 0003_document_file_fingerprints
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_approved_duplicate_invoices"
down_revision = "0003_document_file_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "allow_duplicate_invoice" not in columns:
        op.add_column(
            "documents",
            sa.Column("allow_duplicate_invoice", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "allow_duplicate_invoice" in columns:
        op.drop_column("documents", "allow_duplicate_invoice")
