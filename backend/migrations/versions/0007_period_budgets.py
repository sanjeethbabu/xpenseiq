"""Add period-based spending budgets."""

from alembic import op
import sqlalchemy as sa


revision = "0007_period_budgets"
down_revision = "0006_document_duplicate_filename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("budgets"):
        op.create_table(
            "budgets",
            sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("period_type", sa.String(length=12), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("period_index", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "period_type", "year", "period_index", "currency",
                name="uq_budgets_user_period_currency",
            ),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("budgets")}
    if "ix_budgets_user_id" not in indexes:
        op.create_index("ix_budgets_user_id", "budgets", ["user_id"])
    if "ix_budgets_user_year" not in indexes:
        op.create_index("ix_budgets_user_year", "budgets", ["user_id", "year"])


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("budgets"):
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("budgets")}
    if "ix_budgets_user_year" in indexes:
        op.drop_index("ix_budgets_user_year", table_name="budgets")
    if "ix_budgets_user_id" in indexes:
        op.drop_index("ix_budgets_user_id", table_name="budgets")
    op.drop_table("budgets")
