"""Allow document errors to include the matched filename."""

from alembic import op
import sqlalchemy as sa


revision = "0006_document_duplicate_filename"
down_revision = "0005_invoice_item_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "error_message",
        existing_type=sa.String(length=240),
        type_=sa.String(length=512),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "documents",
        "error_message",
        existing_type=sa.String(length=512),
        type_=sa.String(length=240),
        existing_nullable=True,
    )
