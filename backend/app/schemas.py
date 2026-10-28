from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

EXPENSE_CATEGORIES = (
    "Groceries & Dining",
    "Transportation",
    "Shopping & Retail",
    "Bills & Utilities",
    "Housing",
    "Healthcare",
    "Travel",
    "Education",
    "Business",
    "Entertainment",
    "Taxes & Fees",
    "Other",
)
ExpenseCategory = Literal[
    "Groceries & Dining",
    "Transportation",
    "Shopping & Retail",
    "Bills & Utilities",
    "Housing",
    "Healthcare",
    "Travel",
    "Education",
    "Business",
    "Entertainment",
    "Taxes & Fees",
    "Other",
]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class UserLogin(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_login_identifier(cls, value: str) -> str:
        return value.strip()


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str
    employee_id: str | None = None
    user_role: str = "user"
    must_change_password: bool = False
    model_config = ConfigDict(from_attributes=True)


class EmployeeCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_employee_email(cls, value: EmailStr) -> str:
        return str(value).lower()

    @field_validator("display_name")
    @classmethod
    def normalize_employee_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter the employee's name.")
        return normalized


class PasswordChange(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class LineItem(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    category: ExpenseCategory | None
    hsn_sac_code: str | None = None
    quantity: Decimal | None = Field(default=None, max_digits=14, decimal_places=3)
    unit: str | None = None
    unit_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    discount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    taxable_amount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    gst_rate: Decimal | None = Field(default=None, max_digits=6, decimal_places=3)
    cgst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    sgst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    igst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    cess: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    line_total: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)

    @model_validator(mode="before")
    @classmethod
    def allow_legacy_missing_category(cls, value: Any) -> Any:
        if isinstance(value, dict) and "category" not in value:
            return {**value, "category": None}
        return value

    @field_validator("quantity", "unit_price", "discount", "taxable_amount", "gst_rate", "cgst", "sgst", "igst", "cess", "line_total")
    @classmethod
    def nonnegative_when_present(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Financial fields must not be negative.")
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.001" if value.as_tuple().exponent < -2 else "0.01"), rounding=ROUND_HALF_UP)
        return value


class InvoiceExtraction(BaseModel):
    document_type: Literal["invoice", "receipt", "bill", "other"] = "invoice"
    category: ExpenseCategory = "Other"
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    seller_name: str | None = None
    buyer_name: str | None = None
    seller_gstin: str | None = None
    buyer_gstin: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    place_of_supply: str | None = None
    payment_terms: str | None = None
    subtotal: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    discount_total: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    taxable_value: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    cgst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    sgst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    igst: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    cess: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    other_charges: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    round_off: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    total: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    line_items: list[LineItem] = Field(default_factory=list, max_length=300)
    warnings: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("subtotal", "discount_total", "taxable_value", "cgst", "sgst", "igst", "cess", "other_charges", "total")
    @classmethod
    def nonnegative_amount(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Invoice amounts must not be negative.")
        return value

    @model_validator(mode="after")
    def check_date_order(self):
        if self.invoice_date and self.due_date and self.due_date < self.invoice_date:
            self.warnings.append("Due date is earlier than invoice date; please verify.")
        if self.total is not None:
            self.total = self.total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if self.subtotal is not None and self.taxable_value is not None:
            if abs(self.subtotal - self.taxable_value - (self.discount_total or Decimal("0"))) > Decimal("0.05"):
                self.warnings.append("Subtotal, discount, and taxable value do not reconcile.")
        calculated_taxes = sum((v or Decimal("0")) for v in (self.cgst, self.sgst, self.igst, self.cess))
        if self.total is not None and self.taxable_value is not None:
            calculated = self.taxable_value + calculated_taxes + (self.other_charges or Decimal("0")) + (self.round_off or Decimal("0"))
            if abs(calculated - self.total) > Decimal("1.00"):
                self.warnings.append("Taxable value and tax components differ from the invoice total; please verify.")
        for line in self.line_items:
            if line.quantity is not None and line.unit_price is not None and line.line_total is not None:
                expected = (line.quantity * line.unit_price - (line.discount or Decimal("0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if abs(expected - line.line_total) > Decimal("1.00"):
                    self.warnings.append(f"Line total for “{line.description[:80]}” does not match quantity and unit price.")
        return self


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1)
    history: list[AssistantMessage] = Field(default_factory=list, max_length=4)


class WhatIfRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    monthly_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    months: int = Field(default=12, ge=1, le=600)


class IncomeCreate(BaseModel):
    income_date: date
    source_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    amount: Decimal = Field(gt=0)


class BudgetCreate(BaseModel):
    period_type: Literal["quarter", "half_year", "year"]
    year: int = Field(ge=2000, le=2100)
    period_index: int = Field(default=0, ge=0, le=4)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

    @field_validator("currency")
    @classmethod
    def uppercase_budget_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return normalized

    @model_validator(mode="after")
    def validate_period_index(self):
        valid_indexes = {
            "quarter": {1, 2, 3, 4},
            "half_year": {1, 2},
            "year": {0},
        }
        if self.period_index not in valid_indexes[self.period_type]:
            raise ValueError("Choose a valid quarter or half-year period.")
        return self


class ReimbursementTeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_team_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter a team name.")
        return normalized


class ReimbursementCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    max_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @field_validator("name")
    @classmethod
    def normalize_category_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter a category name.")
        return normalized

    @field_validator("currency")
    @classmethod
    def uppercase_category_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha() or len(normalized) != 3:
            raise ValueError("Currency must be a three-letter code.")
        return normalized


class ReimbursementCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    max_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_category_name(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip()
            if not normalized:
                raise ValueError("Enter a category name.")
            return normalized
        return value

    @field_validator("currency")
    @classmethod
    def uppercase_category_currency(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.upper()
            if not normalized.isalpha() or len(normalized) != 3:
                raise ValueError("Currency must be a three-letter code.")
            return normalized
        return value


class ReimbursementCategoryOut(BaseModel):
    id: UUID
    team_id: UUID
    name: str
    description: str | None
    max_amount: Decimal
    currency: str
    is_active: bool
    created_at: date
    created_by: UUID | None
    model_config = ConfigDict(from_attributes=True)


class ReimbursementClaimCreate(BaseModel):
    expense_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    category_id: UUID | None = None
    claim_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    receipt_filename: str | None = None
    receipt_content_type: str | None = None

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Explain why this expense should be reimbursed.")
        return normalized


class ReimbursementDecision(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_review_note(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def require_rejection_note(self):
        if self.action == "reject" and not self.note:
            raise ValueError("Add a reason when rejecting a claim.")
        return self


class ClaimLimitCheck(BaseModel):
    category_id: UUID
    category_name: str
    max_amount: Decimal
    currency: str
    claimed_this_period: Decimal
    remaining_amount: Decimal
    period_type: str
    period_start: date
    period_end: date
    can_claim: bool
    message: str | None = None


class CategoryRequestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_category_request_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter a category name.")
        return normalized