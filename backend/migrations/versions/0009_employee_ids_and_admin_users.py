"""Add employee IDs, first-login password changes, and remove join codes."""

from alembic import op
import sqlalchemy as sa


revision = "0009_employee_users"
down_revision = "0008_reimbursements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    user_columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "employee_id" not in user_columns:
        op.add_column("users", sa.Column("employee_id", sa.String(length=16), nullable=True))
    if "must_change_password" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    user_constraints = {
        constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("users")
    }
    if "uq_users_employee_id" not in user_constraints:
        op.create_unique_constraint("uq_users_employee_id", "users", ["employee_id"])
    op.execute("CREATE SEQUENCE IF NOT EXISTS employee_id_seq START WITH 1")

    if sa.inspect(bind).has_table("reimbursement_teams"):
        team_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("reimbursement_teams")
        }
        if "invite_code_hash" in team_columns:
            op.drop_column("reimbursement_teams", "invite_code_hash")


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("reimbursement_teams"):
        team_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("reimbursement_teams")
        }
        if "invite_code_hash" not in team_columns:
            op.add_column(
                "reimbursement_teams",
                sa.Column("invite_code_hash", sa.String(length=64), nullable=True),
            )

    if sa.inspect(bind).has_table("users"):
        user_columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
        user_constraints = {
            constraint["name"]
            for constraint in sa.inspect(bind).get_unique_constraints("users")
        }
        if "uq_users_employee_id" in user_constraints:
            op.drop_constraint("uq_users_employee_id", "users", type_="unique")
        if "must_change_password" in user_columns:
            op.drop_column("users", "must_change_password")
        if "employee_id" in user_columns:
            op.drop_column("users", "employee_id")
    op.execute("DROP SEQUENCE IF EXISTS employee_id_seq")
