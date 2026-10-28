import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("employee_id", name="uq_users_employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    employee_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_role: Mapped[str] = mapped_column(String(12), default="user")
    must_change_password: Mapped[bool] = mapped_column(default=False)
    preferred_currency: Mapped[str] = mapped_column(String(3), default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    documents: Mapped[list["Document"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    income_records: Mapped[list["Income"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_status_created", "user_id", "status", "created_at"),
        UniqueConstraint("user_id", "file_sha256", name="uq_documents_user_file_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int]
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allow_duplicate_invoice: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="Upload accepted")
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    temp_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped[User] = relationship(back_populates="documents")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_user_date", "user_id", "invoice_date"),
        Index("ix_invoices_user_category", "user_id", "category"),
        Index("ix_invoices_user_seller_number", "user_id", "seller_name", "invoice_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, unique=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    buyer_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_of_supply: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    discount_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    taxable_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cgst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    sgst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    igst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cess: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    other_charges: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    round_off: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    validation_warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    user: Mapped[User] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (Index("ix_invoice_items_invoice", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hsn_sac_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    discount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    taxable_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    cgst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    sgst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    igst: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cess: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Income(Base):
    __tablename__ = "income"
    __table_args__ = (Index("ix_income_user_date", "user_id", "income_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    income_date: Mapped[date]
    source_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    user: Mapped[User] = relationship(back_populates="income_records")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_type", "year", "period_index", "currency",
            name="uq_budgets_user_period_currency",
        ),
        Index("ix_budgets_user_year", "user_id", "year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period_type: Mapped[str] = mapped_column(String(12))
    year: Mapped[int]
    period_index: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReimbursementTeam(Base):
    __tablename__ = "reimbursement_teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReimbursementMembership(Base):
    __tablename__ = "reimbursement_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_reimbursement_memberships_user"),
        UniqueConstraint("team_id", "user_id", name="uq_reimbursement_memberships_team_user"),
        Index("ix_reimbursement_memberships_team", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursement_teams.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(12), default="employee")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReimbursementCategory(Base):
    __tablename__ = "reimbursement_categories"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_reimbursement_categories_team_name"),
        Index("ix_reimbursement_categories_team", "team_id"),
        Index("ix_reimbursement_categories_active", "team_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursement_teams.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ReimbursementClaim(Base):
    __tablename__ = "reimbursement_claims"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_reimbursement_claims_invoice"),
        Index("ix_reimbursement_claims_team_status", "team_id", "status"),
        Index("ix_reimbursement_claims_employee", "employee_id"),
        Index("ix_reimbursement_claims_category", "category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursement_teams.id", ondelete="CASCADE")
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reimbursement_categories.id", ondelete="SET NULL"), nullable=True
    )
    merchant_name: Mapped[str] = mapped_column(String(255))
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="submitted")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserClaim(Base):
    __tablename__ = "user_claims"
    __table_args__ = (
        Index("ix_user_claims_user_category_period", "user_id", "category_id", "period_start", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursement_categories.id", ondelete="CASCADE")
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reimbursement_claims.id", ondelete="CASCADE")
    )
    period_type: Mapped[str] = mapped_column(String(12))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)