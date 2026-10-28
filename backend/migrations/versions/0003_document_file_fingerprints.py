"""Detect duplicate uploaded files.

Revision ID: 0003_document_file_fingerprints
Revises: 0002_expense_categories
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_document_file_fingerprints"
down_revision = "0002_expense_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "file_sha256" not in columns:
        op.add_column("documents", sa.Column("file_sha256", sa.String(length=64), nullable=True))
    constraints = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("documents")}
    if "uq_documents_user_file_sha256" not in constraints:
        op.create_unique_constraint(
            "uq_documents_user_file_sha256",
            "documents",
            ["user_id", "file_sha256"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    constraints = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("documents")}
    if "uq_documents_user_file_sha256" in constraints:
        op.drop_constraint("uq_documents_user_file_sha256", "documents", type_="unique")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "file_sha256" in columns:
        op.drop_column("documents", "file_sha256")
