"""Add employee reimbursement teams and claim tracking."""

from alembic import op
import sqlalchemy as sa


revision = "0008_reimbursements"
down_revision = "0007_period_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "reimbursement_teams" not in tables:
        op.create_table(
            "reimbursement_teams",
            sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("invite_code_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("invite_code_hash"),
        )
    if "reimbursement_memberships" not in tables:
        op.create_table(
            "reimbursement_memberships",
            sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("team_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=12), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["reimbursement_teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "user_id", name="uq_reimbursement_memberships_team_user"),
            sa.UniqueConstraint("user_id", name="uq_reimbursement_memberships_user"),
        )
    if "reimbursement_claims" not in tables:
        op.create_table(
            "reimbursement_claims",
            sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("team_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("employee_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("invoice_id", sa.Uuid(as_uuid=True), nullable=True),
            sa.Column("merchant_name", sa.String(length=255), nullable=False),
            sa.Column("expense_date", sa.Date(), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=True),
            sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=12), nullable=False),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewer_id", sa.Uuid(as_uuid=True), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["team_id"], ["reimbursement_teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("invoice_id", name="uq_reimbursement_claims_invoice"),
        )
    indexes = {
        table: {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        for table in ("reimbursement_memberships", "reimbursement_claims")
    }
    if "ix_reimbursement_memberships_team" not in indexes["reimbursement_memberships"]:
        op.create_index(
            "ix_reimbursement_memberships_team",
            "reimbursement_memberships",
            ["team_id"],
        )
    if "ix_reimbursement_memberships_user_id" not in indexes["reimbursement_memberships"]:
        op.create_index(
            "ix_reimbursement_memberships_user_id",
            "reimbursement_memberships",
            ["user_id"],
        )
    if "ix_reimbursement_claims_employee" not in indexes["reimbursement_claims"]:
        op.create_index(
            "ix_reimbursement_claims_employee",
            "reimbursement_claims",
            ["employee_id"],
        )
    if "ix_reimbursement_claims_team_status" not in indexes["reimbursement_claims"]:
        op.create_index(
            "ix_reimbursement_claims_team_status",
            "reimbursement_claims",
            ["team_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("reimbursement_claims"):
        indexes = {index["name"] for index in inspector.get_indexes("reimbursement_claims")}
        if "ix_reimbursement_claims_team_status" in indexes:
            op.drop_index("ix_reimbursement_claims_team_status", table_name="reimbursement_claims")
        if "ix_reimbursement_claims_employee" in indexes:
            op.drop_index("ix_reimbursement_claims_employee", table_name="reimbursement_claims")
        op.drop_table("reimbursement_claims")
    if inspector.has_table("reimbursement_memberships"):
        indexes = {index["name"] for index in inspector.get_indexes("reimbursement_memberships")}
        if "ix_reimbursement_memberships_user_id" in indexes:
            op.drop_index("ix_reimbursement_memberships_user_id", table_name="reimbursement_memberships")
        if "ix_reimbursement_memberships_team" in indexes:
            op.drop_index("ix_reimbursement_memberships_team", table_name="reimbursement_memberships")
        op.drop_table("reimbursement_memberships")
    if inspector.has_table("reimbursement_teams"):
        op.drop_table("reimbursement_teams")
