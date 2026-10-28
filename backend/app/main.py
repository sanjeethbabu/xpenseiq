import logging
import hashlib
import re
import uuid
import csv
import io
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.ai import answer_financial_question, classify_expense_categories
from app.core.config import settings
from app.db.session import get_db
from app.documents import render_pdf_page
from app.finance import amount, cash_flow, forecast_spending_window, has_duplicate_invoice, parse_daily_spending_scenario, parse_user_available_cash, project_month_end
from app.models import Budget, Document, Income, Invoice, InvoiceItem, ReimbursementCategory, ReimbursementClaim, ReimbursementMembership, ReimbursementTeam, User, UserClaim
from app.schemas import AssistantQuestion, BudgetCreate, CategoryRequestCreate, ClaimLimitCheck, EmployeeCreate, IncomeCreate, InvoiceExtraction, PasswordChange, ReimbursementCategoryCreate, ReimbursementCategoryOut, ReimbursementCategoryUpdate, ReimbursementClaimCreate, ReimbursementDecision, ReimbursementTeamCreate, UserCreate, UserLogin, UserOut, WhatIfRequest
from app.security import COOKIE_NAME, current_user, hash_password, set_session, verify_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("xpenziq")
app = FastAPI(title="XpenzIQ API", version="0.1.0", description="Financial document intelligence and analysis API")
allowed_origins = {settings.frontend_url}
if settings.app_env != "production":
    allowed_origins.update({"http://localhost:3000", "http://127.0.0.1:3000"})
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
AuthUser = Annotated[User, Depends(current_user)]
Database = Annotated[Session, Depends(get_db)]


def user_document(db: Session, user: User, document_id: uuid.UUID) -> Document:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def invoice_values(payload: InvoiceExtraction) -> dict:
    return payload.model_dump(exclude={"document_type", "line_items", "warnings"})


def existing_upload_name(db: Session, user_id: uuid.UUID, file_sha256: str) -> str | None:
    return db.scalar(
        select(Document.filename).where(
            Document.user_id == user_id,
            Document.file_sha256 == file_sha256,
            Document.status != "failed",
        )
    )


def invoice_out(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id), "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "merchant_name": invoice.seller_name, "description": invoice.seller_name or "Invoice",
        "category": invoice.category,
        "total_amount": str(invoice.total), "currency": invoice.currency,
        "status": "confirmed", "line_items": [
            {"description": item.description, "category": item.category,
             "quantity": str(item.quantity) if item.quantity is not None else None,
             "unit_price": str(item.unit_price) if item.unit_price is not None else None,
             "line_total": str(item.line_total) if item.line_total is not None else None}
            for item in invoice.items
        ],
    }


def reimbursement_membership(db: Session, user: User) -> ReimbursementMembership:
    membership = db.scalar(
        select(ReimbursementMembership).where(ReimbursementMembership.user_id == user.id)
    )
    if membership is None:
        raise HTTPException(status_code=409, detail="Create or join a reimbursement team first.")
    return membership


def reimbursement_owner_team(db: Session, user: User) -> ReimbursementMembership:
    membership = reimbursement_membership(db, user)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the reimbursement admin can manage employees.")
    return membership


def reimbursement_claim_out(
    claim: ReimbursementClaim, employee: User, reviewer: User | None = None
) -> dict:
    return {
        "id": str(claim.id),
        "expense_id": str(claim.invoice_id) if claim.invoice_id else None,
        "category_id": str(claim.category_id) if claim.category_id else None,
        "employee_id": str(claim.employee_id),
        "employee_name": employee.display_name,
        "employee_email": employee.email,
        "merchant_name": claim.merchant_name,
        "expense_date": claim.expense_date.isoformat() if claim.expense_date else None,
        "description": claim.description,
        "category": claim.category,
        "amount": str(claim.amount),
        "currency": claim.currency,
        "reason": claim.reason,
        "status": claim.status,
        "review_note": claim.review_note,
        "reviewer_name": reviewer.display_name if reviewer else None,
        "submitted_at": claim.submitted_at.isoformat(),
        "reviewed_at": claim.reviewed_at.isoformat() if claim.reviewed_at else None,
        "paid_at": claim.paid_at.isoformat() if claim.paid_at else None,
    }


def reimbursement_category_out(category: ReimbursementCategory) -> dict:
    return {
        "id": str(category.id),
        "team_id": str(category.team_id),
        "name": category.name,
        "description": category.description,
        "max_amount": str(category.max_amount),
        "currency": category.currency,
        "is_active": category.is_active,
        "created_at": category.created_at.isoformat(),
        "created_by": str(category.created_by) if category.created_by else None,
    }


def calculate_period_bounds(period_type: str, reference_date: date) -> tuple[date, date]:
    if period_type == "monthly":
        start = reference_date.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
        return start, end
    elif period_type == "quarterly":
        quarter = (reference_date.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        start = date(reference_date.year, start_month, 1)
        end_month = start_month + 3
        if end_month > 12:
            end = date(reference_date.year + 1, end_month - 12, 1)
        else:
            end = date(reference_date.year, end_month, 1)
        return start, end
    elif period_type == "yearly":
        return date(reference_date.year, 1, 1), date(reference_date.year + 1, 1, 1)
    else:
        start = reference_date.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
        return start, end


def check_claim_limit(
    db: Session,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    amount: Decimal,
    reference_date: date | None = None,
) -> ClaimLimitCheck:
    category = db.get(ReimbursementCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Reimbursement category not found.")
    if not category.is_active:
        raise HTTPException(status_code=409, detail="This reimbursement category is inactive.")

    ref_date = reference_date or date.today()
    period_type = "monthly"
    period_start, period_end = calculate_period_bounds(period_type, ref_date)

    claimed_sum = db.scalar(
        select(func.coalesce(func.sum(UserClaim.claimed_amount), Decimal("0"))).where(
            UserClaim.user_id == user_id,
            UserClaim.category_id == category_id,
            UserClaim.period_start >= period_start,
            UserClaim.period_end <= period_end,
        )
    ) or Decimal("0")

    remaining = category.max_amount - claimed_sum
    can_claim = amount <= remaining

    message = None
    if not can_claim:
        message = f"Claim exceeds category limit. You have claimed {amount(claimed_sum, category.currency)} of {amount(category.max_amount, category.currency)} for this period."

    return ClaimLimitCheck(
        category_id=category.id,
        category_name=category.name,
        max_amount=category.max_amount,
        currency=category.currency,
        claimed_this_period=claimed_sum,
        remaining_amount=max(remaining, Decimal("0")),
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        can_claim=can_claim,
        message=message,
    )


def record_user_claim(
    db: Session,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    claim_id: uuid.UUID,
    amount: Decimal,
    reference_date: date | None = None,
) -> None:
    ref_date = reference_date or date.today()
    period_type = "monthly"
    period_start, period_end = calculate_period_bounds(period_type, ref_date)

    user_claim = UserClaim(
        user_id=user_id,
        category_id=category_id,
        claim_id=claim_id,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        claimed_amount=amount,
    )
    db.add(user_claim)


def invoice_extraction_out(invoice: Invoice) -> dict:
    return {
        "document_type": "invoice",
        **{
            field: getattr(invoice, field).isoformat() if isinstance(getattr(invoice, field), date) else str(getattr(invoice, field)) if getattr(invoice, field) is not None else None
            for field in (
                "invoice_number", "invoice_date", "due_date", "category", "currency", "seller_name",
                "buyer_name", "seller_gstin", "buyer_gstin", "billing_address",
                "shipping_address", "place_of_supply", "payment_terms", "subtotal",
                "discount_total", "taxable_value", "cgst", "sgst", "igst", "cess",
                "other_charges", "round_off", "total",
            )
        },
        "line_items": [
            {
                "description": item.description, "category": item.category, "hsn_sac_code": item.hsn_sac_code,
                "quantity": str(item.quantity) if item.quantity is not None else None,
                "unit": item.unit,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "discount": str(item.discount) if item.discount is not None else None,
                "taxable_amount": str(item.taxable_amount) if item.taxable_amount is not None else None,
                "gst_rate": str(item.gst_rate) if item.gst_rate is not None else None,
                "cgst": str(item.cgst) if item.cgst is not None else None,
                "sgst": str(item.sgst) if item.sgst is not None else None,
                "igst": str(item.igst) if item.igst is not None else None,
                "cess": str(item.cess) if item.cess is not None else None,
                "line_total": str(item.line_total) if item.line_total is not None else None,
            }
            for item in invoice.items
        ],
        "warnings": invoice.validation_warnings,
    }


def document_out(document: Document) -> dict:
    return {
        "id": str(document.id), "filename": document.filename, "status": document.status,
        "stage": document.stage, "created_at": document.created_at.isoformat(),
        "error_code": document.error_code, "error_message": document.error_message,
    }


def cleanup_stale_uploads(db: Session) -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - settings.document_retention_hours * 3600
    for path in settings.temp_upload_dir.iterdir():
        if not path.is_file():
            continue
        try:
            modified_at = path.stat().st_mtime
        except FileNotFoundError:
            continue
        if modified_at >= cutoff:
            continue
        document = db.scalar(select(Document).where(Document.temp_path == str(path)))
        if document and document.status in {"queued", "processing"}:
            document.status = "failed"
            document.stage = "Temporary upload expired"
            document.error_code = "PROCESSING_TIMEOUT"
            document.error_message = "This upload expired before processing could finish. Upload the file again."
            document.temp_path = None
            db.commit()
        path.unlink(missing_ok=True)


def document_preview_path(document: Document) -> Path:
    if document.temp_path:
        return Path(document.temp_path)
    extension = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(document.mime_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="This document type cannot be previewed.")
    return settings.temp_upload_dir / f"{document.id}{extension}"


def budget_period_dates(period_type: str, year: int, period_index: int) -> tuple[date, date, str]:
    if period_type == "year":
        return date(year, 1, 1), date(year, 12, 31), str(year)
    if period_type == "half_year":
        start_month = 1 if period_index == 1 else 7
        end_month = start_month + 5
        title = f"H{period_index} {year}"
    else:
        start_month = (period_index - 1) * 3 + 1
        end_month = start_month + 2
        title = f"Q{period_index} {year}"
    return (
        date(year, start_month, 1),
        date(year, end_month, calendar.monthrange(year, end_month)[1]),
        title,
    )


def budget_output(budget: Budget, spent: Decimal) -> dict[str, str | int]:
    start_date, end_date, title = budget_period_dates(
        budget.period_type, budget.year, budget.period_index
    )
    target = amount(budget.amount)
    recorded_spending = amount(spent)
    return {
        "id": str(budget.id),
        "period_type": budget.period_type,
        "period_index": budget.period_index,
        "year": budget.year,
        "title": title,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": budget.currency,
        "amount": str(target),
        "expense_amount": str(recorded_spending),
        "remaining_amount": str(amount(max(target - recorded_spending, Decimal("0")))),
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "xpenziq-api"}


@app.get("/health/ready")
def readiness(db: Database):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The database is unavailable.") from exc
    return {"status": "ready", "service": "xpenziq-api"}


@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, response: Response, db: Database):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, display_name=payload.display_name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    set_session(response, user.id)
    return user


@app.post("/api/v1/auth/login", response_model=UserOut)
def login(payload: UserLogin, response: Response, db: Database):
    identifier = payload.email.lower()
    user = db.scalar(
        select(User).where(
            or_(User.email == identifier, User.employee_id == identifier.upper())
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or employee ID or password is incorrect.")
    set_session(response, user.id)
    return user


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response):
    is_prod = settings.app_env == "production"
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=is_prod, domain=None if is_prod else "localhost")
    response.status_code = 204
    return response


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: AuthUser):
    return user


@app.post("/api/v1/auth/change-password")
def change_password(payload: PasswordChange, user: AuthUser, db: Database):
    if not user.must_change_password:
        raise HTTPException(status_code=409, detail="Your password has already been changed.")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=422, detail="Choose a password different from your temporary password.")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"status": "updated"}


@app.post("/api/v1/documents/upload", status_code=202)
async def upload_document(
    user: AuthUser,
    db: Database,
    file: UploadFile = File(...),
):
    allowed = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    name = Path(file.filename or "upload").name[:255]
    extension = Path(name).suffix.lower()
    allowed_extensions = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    mime = allowed_extensions.get(extension)
    if mime not in allowed:
        raise HTTPException(status_code=415, detail="Upload a PDF, JPG, PNG, or WebP document.")
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Files must be {settings.max_upload_mb} MB or smaller.")
    signatures = {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) > 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not signatures[mime]:
        raise HTTPException(status_code=415, detail="The file content does not match its file type.")
    file_sha256 = hashlib.sha256(content).hexdigest()
    matched_filename = existing_upload_name(db, user.id, file_sha256)
    if matched_filename:
        raise HTTPException(
            status_code=409,
            detail=f"This file matches existing upload: {matched_filename}.",
        )
    failed_matches = db.scalars(select(Document).where(
        Document.user_id == user.id,
        Document.file_sha256 == file_sha256,
        Document.status == "failed",
    )).all()
    for failed_document in failed_matches:
        failed_document.file_sha256 = None
    settings.temp_upload_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_uploads(db)
    document_id = uuid.uuid4()
    path = settings.temp_upload_dir / f"{document_id}{allowed[mime]}"
    path.write_bytes(content)
    document = Document(
        id=document_id,
        user_id=user.id,
        filename=name,
        mime_type=mime,
        file_size=len(content),
        file_sha256=file_sha256,
        status="queued",
        stage="Upload accepted",
        temp_path=str(path),
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        path.unlink(missing_ok=True)
        matched_filename = existing_upload_name(db, user.id, file_sha256)
        if matched_filename:
            raise HTTPException(
                status_code=409,
                detail=f"This file matches existing upload: {matched_filename}.",
            ) from exc
        logger.exception("Could not persist upload job for document_id=%s", document_id)
        raise HTTPException(status_code=503, detail="Could not add the upload to the database queue. Try again shortly.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        path.unlink(missing_ok=True)
        logger.exception("Could not persist upload job for document_id=%s", document_id)
        raise HTTPException(status_code=503, detail="Could not add the upload to the database queue. Try again shortly.") from exc
    return document_out(document)


@app.get("/api/v1/documents")
def list_documents(user: AuthUser, db: Database, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    rows = db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [document_out(row) for row in rows]}


@app.get("/api/v1/documents/{document_id}/status")
def document_status(document_id: uuid.UUID, user: AuthUser, db: Database):
    return document_out(user_document(db, user, document_id))


@app.get("/api/v1/documents/{document_id}/details")
def document_details(document_id: uuid.UUID, user: AuthUser, db: Database):
    document = user_document(db, user, document_id)
    invoice = db.scalar(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.document_id == document.id, Invoice.user_id == user.id)
    )
    if invoice is not None:
        return {"expense_saved": True, **invoice_extraction_out(invoice)}
    if document.extraction:
        return {
            "expense_saved": False,
            **InvoiceExtraction.model_validate(document.extraction).model_dump(mode="json"),
        }
    raise HTTPException(status_code=404, detail="No extracted expense details are available for this document yet.")


@app.get("/api/v1/documents/{document_id}/preview")
def document_preview(document_id: uuid.UUID, user: AuthUser, db: Database):
    document = user_document(db, user, document_id)
    path = document_preview_path(document)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original document is no longer available. Upload the file again to preview it.")
    return Response(
        content=path.read_bytes(),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@app.get("/api/v1/documents/{document_id}/preview/page")
def document_preview_page(
    document_id: uuid.UUID,
    user: AuthUser,
    db: Database,
    page: int = Query(default=1, ge=1),
):
    document = user_document(db, user, document_id)
    if document.mime_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Page previews are only available for PDFs.")
    path = document_preview_path(document)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original document is no longer available. Upload the PDF again to preview it.")
    image, page_count, width, height = render_pdf_page(path, page)
    return Response(
        content=image,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-PDF-Page-Count": str(page_count),
            "X-PDF-Page-Width": str(width),
            "X-PDF-Page-Height": str(height),
        },
    )


@app.get("/api/v1/documents/{document_id}/extraction")
def document_extraction(document_id: uuid.UUID, user: AuthUser, db: Database):
    document = user_document(db, user, document_id)
    if document.status != "review" or not document.extraction:
        raise HTTPException(status_code=409, detail="This document is not ready for review.")
    extraction = InvoiceExtraction.model_validate(document.extraction)
    if extraction.invoice_number and extraction.invoice_date and extraction.total is not None:
        candidates = db.scalars(select(Invoice).where(
            Invoice.user_id == user.id,
            Invoice.invoice_date == extraction.invoice_date,
            Invoice.total == extraction.total,
        )).all()
    else:
        candidates = []
    if has_duplicate_invoice(extraction, candidates):
        extraction.warnings.append("A possible duplicate invoice with the same seller, number, date, and total exists.")
    return extraction.model_dump(mode="json")


@app.delete("/api/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, user: AuthUser, db: Database):
    document = user_document(db, user, document_id)
    if document.temp_path:
        Path(document.temp_path).unlink(missing_ok=True)
    db.delete(document)
    db.commit()
    return Response(status_code=204)


@app.post("/api/v1/documents/{document_id}/confirm")
def confirm_document(document_id: uuid.UUID, payload: InvoiceExtraction, user: AuthUser, db: Database):
    document = user_document(db, user, document_id)
    if document.status != "review":
        raise HTTPException(status_code=409, detail="This document is not awaiting review.")
    if payload.total is None:
        raise HTTPException(status_code=422, detail="Enter the invoice total before confirming.")
    warnings = list(dict.fromkeys(payload.warnings))
    if not getattr(document, "allow_duplicate_invoice", False) and payload.invoice_number and payload.invoice_date:
        candidates = db.scalars(select(Invoice).where(
            Invoice.user_id == user.id,
            Invoice.invoice_date == payload.invoice_date, Invoice.total == payload.total,
        )).all()
        if has_duplicate_invoice(payload, candidates):
            raise HTTPException(status_code=409, detail="This invoice already exists in your expenses. It was not saved again.")
    values = invoice_values(payload)
    invoice = Invoice(user_id=user.id, document_id=document.id, validation_warnings=warnings, **values)
    invoice.items = [InvoiceItem(**item.model_dump()) for item in payload.line_items]
    db.add(invoice)
    if document.temp_path:
        Path(document.temp_path).unlink(missing_ok=True)
    document.status, document.stage, document.extraction, document.temp_path = "completed", "Expense saved", payload.model_dump(mode="json"), None
    db.commit()
    return {"id": str(invoice.id), "status": "confirmed", "warnings": warnings}


@app.get("/api/v1/expenses")
def list_expenses(user: AuthUser, db: Database, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), search: str | None = None):
    query = select(Invoice).options(selectinload(Invoice.items)).where(Invoice.user_id == user.id).order_by(Invoice.invoice_date.desc().nullslast(), Invoice.created_at.desc())
    if search:
        like = f"%{search[:100]}%"
        query = query.where((Invoice.seller_name.ilike(like)) | (Invoice.invoice_number.ilike(like)))
    invoices = db.scalars(query.limit(limit).offset(offset)).all()
    return {"items": [
        {**invoice_out(row), "expense_date": row.invoice_date.isoformat() if row.invoice_date else None}
        for row in invoices
    ]}


@app.post("/api/v1/expenses", status_code=201)
def create_expense(payload: InvoiceExtraction, user: AuthUser, db: Database):
    if payload.total is None:
        raise HTTPException(status_code=422, detail="Enter an invoice total before saving.")
    invoice = Invoice(
        user_id=user.id,
        **invoice_values(payload),
        validation_warnings=payload.warnings,
    )
    invoice.items = [InvoiceItem(**item.model_dump()) for item in payload.line_items]
    db.add(invoice)
    db.commit()
    return {"id": str(invoice.id), "status": "confirmed", "warnings": invoice.validation_warnings}


@app.delete("/api/v1/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: uuid.UUID, user: AuthUser, db: Database):
    invoice = db.scalar(select(Invoice).where(Invoice.id == expense_id, Invoice.user_id == user.id))
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    db.delete(invoice)
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/expenses/{expense_id}")
def get_expense(expense_id: uuid.UUID, user: AuthUser, db: Database):
    invoice = db.scalar(
        select(Invoice).options(selectinload(Invoice.items)).where(
            Invoice.id == expense_id, Invoice.user_id == user.id
        )
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    return invoice_extraction_out(invoice)


@app.patch("/api/v1/expenses/{expense_id}")
def update_expense(expense_id: uuid.UUID, payload: InvoiceExtraction, user: AuthUser, db: Database):
    invoice = db.scalar(
        select(Invoice).options(selectinload(Invoice.items)).where(
            Invoice.id == expense_id, Invoice.user_id == user.id
        )
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    if payload.total is None:
        raise HTTPException(status_code=422, detail="Enter an invoice total before saving.")
    values = invoice_values(payload)
    for key, value in values.items():
        setattr(invoice, key, value)
    invoice.validation_warnings = payload.warnings
    invoice.items.clear()
    invoice.items.extend(InvoiceItem(**item.model_dump()) for item in payload.line_items)
    db.commit()
    return {"id": str(invoice.id), "status": "updated", "warnings": invoice.validation_warnings}


@app.get("/api/v1/analytics/overview")
def overview(user: AuthUser, db: Database):
    today = date.today()
    expense_total = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.user_id == user.id)) or Decimal("0")
    income_total = db.scalar(select(func.coalesce(func.sum(Income.amount), 0)).where(Income.user_id == user.id)) or Decimal("0")
    expense_count = db.scalar(select(func.count(Invoice.id)).where(Invoice.user_id == user.id)) or 0
    income_count = db.scalar(select(func.count(Income.id)).where(Income.user_id == user.id)) or 0
    months = []
    month_start = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    for offset in range(5, -1, -1):
        boundary = (today.replace(day=1) - timedelta(days=offset * 30)).replace(day=1)
        next_boundary = (boundary.replace(day=28) + timedelta(days=4)).replace(day=1)
        if boundary < month_start:
            continue
        total = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.user_id == user.id, Invoice.invoice_date >= boundary, Invoice.invoice_date < next_boundary)) or Decimal("0")
        months.append({"month": boundary.strftime("%b"), "total": str(amount(total))})
    merchants = db.execute(
        select(func.coalesce(Invoice.seller_name, "Uncategorized"), func.sum(Invoice.total))
        .where(Invoice.user_id == user.id)
        .group_by(Invoice.seller_name).order_by(func.sum(Invoice.total).desc()).limit(5)
    ).all()
    currency_totals = db.execute(
        select(Invoice.currency, func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.user_id == user.id)
        .group_by(Invoice.currency)
    ).all()
    line_item_taxes = (
        func.coalesce(InvoiceItem.cgst, 0)
        + func.coalesce(InvoiceItem.sgst, 0)
        + func.coalesce(InvoiceItem.igst, 0)
        + func.coalesce(InvoiceItem.cess, 0)
    )
    calculated_line_total = case(
        (InvoiceItem.taxable_amount.is_not(None), InvoiceItem.taxable_amount + line_item_taxes),
        (
            InvoiceItem.quantity.is_not(None) & InvoiceItem.unit_price.is_not(None),
            func.greatest(
                InvoiceItem.quantity * InvoiceItem.unit_price - func.coalesce(InvoiceItem.discount, 0),
                0,
            ) + line_item_taxes,
        ),
        else_=None,
    )
    line_item_amount = func.coalesce(InvoiceItem.line_total, calculated_line_total)
    categorized_line_totals = db.execute(
        select(
            Invoice.id,
            func.coalesce(InvoiceItem.category, Invoice.category, "Uncategorized"),
            Invoice.currency,
            func.sum(line_item_amount),
            func.count(InvoiceItem.id),
            Invoice.total,
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id, line_item_amount > 0)
        .group_by(Invoice.id, InvoiceItem.category, Invoice.category, Invoice.currency, Invoice.total)
    ).all()
    invoices_without_line_totals = db.execute(
        select(
            func.coalesce(Invoice.category, "Uncategorized"),
            Invoice.currency,
            func.sum(Invoice.total),
            func.count(Invoice.id),
        )
        .where(
            Invoice.user_id == user.id,
            ~select(InvoiceItem.id).where(
                InvoiceItem.invoice_id == Invoice.id,
                line_item_amount > 0,
            ).exists(),
        )
        .group_by(Invoice.category, Invoice.currency)
    ).all()
    category_totals_by_key: dict[tuple[str, str], tuple[Decimal, int]] = {}
    line_totals_by_invoice: dict[uuid.UUID, list[tuple[str, str, Decimal, int, Decimal]]] = {}
    for invoice_id, category, currency, total, count, invoice_total in categorized_line_totals:
        line_totals_by_invoice.setdefault(invoice_id, []).append(
            (category, currency, Decimal(total or 0), count, Decimal(invoice_total or 0))
        )
    for invoice_lines in line_totals_by_invoice.values():
        invoice_lines.sort(key=lambda line: (line[2], line[0], line[1]))
        line_subtotal = sum((total for _, _, total, _, _ in invoice_lines), Decimal("0"))
        invoice_total = invoice_lines[0][4]
        allocated_total = Decimal("0")
        for index, (category, currency, line_total, count, _) in enumerate(invoice_lines):
            final_total = (
                amount(invoice_total - allocated_total)
                if index == len(invoice_lines) - 1
                else amount(invoice_total * line_total / line_subtotal)
            )
            allocated_total += final_total
            key = (category, currency)
            old_total, old_count = category_totals_by_key.get(key, (Decimal("0"), 0))
            category_totals_by_key[key] = (old_total + final_total, old_count + count)
    for category, currency, total, count in invoices_without_line_totals:
        key = (category, currency)
        old_total, old_count = category_totals_by_key.get(key, (Decimal("0"), 0))
        category_totals_by_key[key] = (old_total + Decimal(total or 0), old_count + count)
    category_totals = [
        (category, currency, total, count)
        for (category, currency), (total, count) in sorted(
            category_totals_by_key.items(), key=lambda entry: entry[1][0], reverse=True
        )
    ]
    uncategorized_count = db.scalar(
        select(func.count(InvoiceItem.id))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id, InvoiceItem.category.is_(None))
    ) or 0
    return {
        "income": str(amount(income_total)), "expenses": str(amount(expense_total)),
        "cash_flow": str(cash_flow(Decimal(income_total), Decimal(expense_total))),
        "expense_count": expense_count, "income_count": income_count, "currency": user.preferred_currency,
        "currency_totals": [{"currency": c, "total": str(amount(t))} for c, t in currency_totals],
        "monthly": months, "merchants": [{"name": name or "Uncategorized", "total": str(amount(total))} for name, total in merchants],
        "category_totals": [
            {"category": category, "currency": currency, "total": str(amount(total)), "count": count}
            for category, currency, total, count in category_totals
        ],
        "uncategorized_count": uncategorized_count,
    }


@app.get("/api/v1/analytics/spending")
def spending_over_time(
    user: AuthUser,
    db: Database,
    months: int = Query(default=6, ge=1, le=6),
    from_date: date | None = None,
    to_date: date | None = None,
):
    if (from_date is None) != (to_date is None):
        raise HTTPException(status_code=422, detail="Both from_date and to_date are required for a custom range.")
    if from_date and to_date:
        if from_date > to_date:
            raise HTTPException(status_code=422, detail="from_date must be on or before to_date.")
        first_month = from_date.replace(day=1)
        last_month = to_date.replace(day=1)
        date_filter = (Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
    else:
        today = date.today()
        month_index = today.year * 12 + today.month - 1 - (months - 1)
        first_month = date(month_index // 12, month_index % 12 + 1, 1)
        last_month = today.replace(day=1)
        next_month_index = today.year * 12 + today.month
        date_filter = (Invoice.invoice_date >= first_month, Invoice.invoice_date < date(next_month_index // 12, next_month_index % 12 + 1, 1))

    rows = db.execute(
        select(Invoice.invoice_date, Invoice.total)
        .where(Invoice.user_id == user.id, *date_filter)
    ).all()
    totals: dict[date, Decimal] = {}
    for invoice_date, total in rows:
        month = invoice_date.replace(day=1)
        totals[month] = totals.get(month, Decimal("0")) + (total or Decimal("0"))

    monthly = []
    current_month = first_month
    while current_month <= last_month:
        monthly.append({
            "month": current_month.strftime("%b %Y"),
            "total": str(amount(totals.get(current_month, Decimal("0")))),
        })
        month_index = current_month.year * 12 + current_month.month
        current_month = date(month_index // 12, month_index % 12 + 1, 1)
    return {"monthly": monthly}


@app.post("/api/v1/analytics/categories/analyze")
async def analyze_expense_categories(user: AuthUser, db: Database):
    items = db.scalars(
        select(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .options(selectinload(InvoiceItem.invoice))
        .where(Invoice.user_id == user.id, InvoiceItem.category.is_(None))
        .order_by(Invoice.created_at, InvoiceItem.id)
        .limit(50)
    ).all()
    if not items:
        return {"categorized": 0, "remaining": 0}

    request_ids = {f"item_{index}": item for index, item in enumerate(items)}
    categories = await classify_expense_categories([
        {
            "id": request_id,
            "merchant": (item.invoice.seller_name or "")[:120],
            "items": [item.description[:160]],
        }
        for request_id, item in request_ids.items()
    ])
    for request_id, item in request_ids.items():
        item.category = categories[request_id]
    db.commit()
    remaining = db.scalar(
        select(func.count(InvoiceItem.id))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id, InvoiceItem.category.is_(None))
    ) or 0
    return {"categorized": len(items), "remaining": remaining}


@app.get("/api/v1/analytics/export.csv")
def export_financial_records(user: AuthUser, db: Database):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["record_type", "date", "merchant_or_source", "invoice_number", "description", "category", "amount", "currency", "taxable_value", "cgst", "sgst", "igst", "cess"])
    invoices = db.scalars(select(Invoice).where(Invoice.user_id == user.id).order_by(Invoice.invoice_date, Invoice.created_at)).all()
    incomes = db.scalars(select(Income).where(Income.user_id == user.id).order_by(Income.income_date)).all()
    for invoice in invoices:
        writer.writerow([
            "expense", invoice.invoice_date.isoformat() if invoice.invoice_date else "",
            invoice.seller_name or "", invoice.invoice_number or "", invoice.seller_name or "",
            invoice.category or "Uncategorized", invoice.total, invoice.currency, invoice.taxable_value or "", invoice.cgst or "",
            invoice.sgst or "", invoice.igst or "", invoice.cess or "",
        ])
    for record in incomes:
        writer.writerow([
            "income", record.income_date.isoformat(), record.source_name, "",
            record.description or "", "", record.amount, record.currency, "", "", "", "", "",
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="xpenziq-financial-records.csv"'},
    )


@app.get("/api/v1/income")
def list_income(user: AuthUser, db: Database, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    rows = db.scalars(select(Income).where(Income.user_id == user.id).order_by(Income.income_date.desc()).limit(limit).offset(offset)).all()
    return {"items": [{"id": str(row.id), "income_date": row.income_date.isoformat(), "source_name": row.source_name, "amount": str(row.amount), "currency": row.currency} for row in rows]}


@app.post("/api/v1/income", status_code=201)
def create_income(payload: IncomeCreate, user: AuthUser, db: Database):
    row = Income(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "source_name": row.source_name, "income_date": row.income_date.isoformat(), "amount": str(row.amount), "currency": row.currency}


@app.delete("/api/v1/income/{income_id}", status_code=204)
def delete_income(income_id: uuid.UUID, user: AuthUser, db: Database):
    row = db.scalar(select(Income).where(Income.id == income_id, Income.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Income record not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/budgets")
def list_budgets(user: AuthUser, db: Database):
    rows = db.scalars(
        select(Budget)
        .where(Budget.user_id == user.id)
        .order_by(Budget.year.desc(), Budget.period_type, Budget.period_index)
    ).all()
    items = []
    for budget in rows:
        start_date, end_date, _ = budget_period_dates(
            budget.period_type, budget.year, budget.period_index
        )
        spent = db.scalar(
            select(func.coalesce(func.sum(Invoice.total), 0)).where(
                Invoice.user_id == user.id,
                Invoice.currency == budget.currency,
                Invoice.invoice_date >= start_date,
                Invoice.invoice_date <= end_date,
            )
        ) or Decimal("0")
        items.append(budget_output(budget, Decimal(spent)))
    return {"items": items}


@app.post("/api/v1/budgets", status_code=201)
def create_budget(payload: BudgetCreate, user: AuthUser, db: Database):
    duplicate = db.scalar(
        select(Budget.id).where(
            Budget.user_id == user.id,
            Budget.period_type == payload.period_type,
            Budget.year == payload.year,
            Budget.period_index == payload.period_index,
            Budget.currency == payload.currency,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="A budget already exists for this period and currency.")
    budget = Budget(user_id=user.id, **payload.model_dump())
    db.add(budget)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A budget already exists for this period and currency.",
        ) from exc
    db.refresh(budget)
    return budget_output(budget, Decimal("0"))


@app.delete("/api/v1/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: uuid.UUID, user: AuthUser, db: Database):
    budget = db.scalar(
        select(Budget).where(Budget.id == budget_id, Budget.user_id == user.id)
    )
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found.")
    db.delete(budget)
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/reimbursements")
def reimbursement_workspace(user: AuthUser, db: Database):
    membership = db.scalar(
        select(ReimbursementMembership).where(ReimbursementMembership.user_id == user.id)
    )
    if membership is None:
        return {"team": None, "members": [], "items": []}
    team = db.get(ReimbursementTeam, membership.team_id)
    if team is None:
        raise HTTPException(status_code=409, detail="Your reimbursement team is unavailable.")
    member_rows = db.execute(
        select(ReimbursementMembership, User)
        .join(User, User.id == ReimbursementMembership.user_id)
        .where(ReimbursementMembership.team_id == team.id)
        .order_by(User.display_name, User.email)
    ).all()
    claim_query = (
        select(ReimbursementClaim, User)
        .join(User, User.id == ReimbursementClaim.employee_id)
        .where(ReimbursementClaim.team_id == team.id)
        .order_by(ReimbursementClaim.submitted_at.desc())
        .limit(100)
    )
    if membership.role != "owner":
        claim_query = claim_query.where(ReimbursementClaim.employee_id == user.id)
    claim_rows = db.execute(claim_query).all()
    return {
        "team": {"id": str(team.id), "name": team.name, "role": membership.role},
        "members": [
            {
                "id": str(member.user_id),
                "display_name": member_user.display_name,
                "email": member_user.email,
                "employee_id": member_user.employee_id,
                "role": member.role,
                "must_change_password": member_user.must_change_password,
            }
            for member, member_user in member_rows
        ],
        "items": [
            reimbursement_claim_out(
                claim,
                employee,
                db.get(User, claim.reviewer_id) if claim.reviewer_id else None,
            )
            for claim, employee in claim_rows
        ],
    }


@app.post("/api/v1/reimbursements/teams", status_code=201)
def create_reimbursement_team(
    payload: ReimbursementTeamCreate, user: AuthUser, db: Database
):
    existing = db.scalar(
        select(ReimbursementMembership.id).where(ReimbursementMembership.user_id == user.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="You already belong to a reimbursement team.")
    team = ReimbursementTeam(name=payload.name)
    db.add(team)
    db.flush()
    db.add(
        ReimbursementMembership(
            team_id=team.id,
            user_id=user.id,
            role="owner",
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="You already belong to a reimbursement team."
        ) from exc
    return {"team": {"id": str(team.id), "name": team.name, "role": "owner"}}


@app.get("/api/v1/reimbursements/users")
def reimbursement_users(user: AuthUser, db: Database):
    membership = reimbursement_owner_team(db, user)
    rows = db.execute(
        select(User, ReimbursementMembership.role)
        .join(ReimbursementMembership, ReimbursementMembership.user_id == User.id)
        .where(ReimbursementMembership.team_id == membership.team_id)
        .order_by(ReimbursementMembership.role, User.employee_id, User.display_name)
        .limit(500)
    ).all()
    return {
        "items": [
            {
                "id": str(member.id),
                "display_name": member.display_name,
                "email": member.email,
                "employee_id": member.employee_id,
                "role": role,
                "must_change_password": member.must_change_password,
                "created_at": member.created_at.isoformat(),
            }
            for member, role in rows
        ]
    }


@app.post("/api/v1/reimbursements/users", status_code=201)
def create_reimbursement_employee(
    payload: EmployeeCreate, user: AuthUser, db: Database
):
    membership = reimbursement_owner_team(db, user)
    team_id = membership.team_id
    existing = db.scalar(select(User.id).where(User.email == str(payload.email).lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    for attempt in range(5):
        sequence_value = db.execute(text("SELECT nextval('employee_id_seq')")).scalar_one()
        employee_id = f"EMP{sequence_value:03d}"
        employee = User(
            email=str(payload.email).lower(),
            display_name=payload.display_name,
            password_hash=hash_password(employee_id),
            employee_id=employee_id,
            must_change_password=True,
        )
        db.add(employee)
        try:
            db.flush()
            db.add(
                ReimbursementMembership(
                    team_id=team_id,
                    user_id=employee.id,
                    role="employee",
                )
            )
            db.commit()
            db.refresh(employee)
            return {
                "user": UserOut.model_validate(employee).model_dump(mode="json"),
                "temporary_password": employee_id,
            }
        except IntegrityError as exc:
            db.rollback()
            if db.scalar(select(User.id).where(User.email == str(payload.email).lower())):
                raise HTTPException(
                    status_code=409, detail="An account with this email already exists."
                ) from exc
            if attempt == 4:
                logger.exception("Could not allocate a unique employee ID for team_id=%s", team_id)
                raise HTTPException(
                    status_code=503, detail="Could not create the employee account. Try again."
                ) from exc

    raise HTTPException(status_code=503, detail="Could not create the employee account. Try again.")


@app.post("/api/v1/reimbursements/claims", status_code=201)
def create_reimbursement_claim(
    payload: ReimbursementClaimCreate, user: AuthUser, db: Database
):
    membership = reimbursement_membership(db, user)
    if membership.role != "employee":
        raise HTTPException(status_code=403, detail="Team owners cannot submit claims for their own review.")
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.expense_id, Invoice.user_id == user.id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    existing = db.scalar(
        select(ReimbursementClaim.id).where(ReimbursementClaim.invoice_id == invoice.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This expense has already been submitted for reimbursement.")
    claim = ReimbursementClaim(
        team_id=membership.team_id,
        employee_id=user.id,
        invoice_id=invoice.id,
        merchant_name=invoice.seller_name or "Expense",
        expense_date=invoice.invoice_date,
        description=invoice.items[0].description if invoice.items else invoice.seller_name or "Expense",
        category=invoice.category,
        amount=invoice.total,
        currency=invoice.currency,
        reason=payload.reason,
    )
    db.add(claim)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This expense has already been submitted for reimbursement."
        ) from exc
    return reimbursement_claim_out(claim, user)


@app.patch("/api/v1/reimbursements/claims/{claim_id}/decision")
def decide_reimbursement_claim(
    claim_id: uuid.UUID,
    payload: ReimbursementDecision,
    user: AuthUser,
    db: Database,
):
    membership = reimbursement_membership(db, user)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the team owner can review claims.")
    claim = db.scalar(
        select(ReimbursementClaim)
        .where(
            ReimbursementClaim.id == claim_id,
            ReimbursementClaim.team_id == membership.team_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Reimbursement claim not found.")
    if claim.employee_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot review your own reimbursement claim.")
    if claim.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted claims can be reviewed.")
    claim.status = "approved" if payload.action == "approve" else "rejected"
    claim.review_note = payload.note
    claim.reviewer_id = user.id
    claim.reviewed_at = datetime.now(timezone.utc)
    
    # If approved, create an expense record for the employee
    if payload.action == "approve":
        employee = db.get(User, claim.employee_id)
        if employee:
            expense_invoice = Invoice(
                user_id=employee.id,
                invoice_number=f"REIMB-{claim.id.hex[:8].upper()}",
                invoice_date=claim.expense_date or date.today(),
                category=claim.category,
                currency=claim.currency,
                seller_name=claim.merchant_name,
                buyer_name=employee.display_name,
                total=claim.amount,
                validation_warnings=[f"Created from approved reimbursement claim {claim.id}"],
            )
            db.add(expense_invoice)
            # Also add a line item for the reimbursement
            expense_invoice.items = [
                InvoiceItem(
                    description=claim.description,
                    category=claim.category,
                    line_total=claim.amount,
                )
            ]
    
    db.commit()
    employee = db.get(User, claim.employee_id)
    if employee is None:
        raise HTTPException(status_code=409, detail="The employee account is unavailable.")
    return reimbursement_claim_out(claim, employee, user)


@app.post("/api/v1/reimbursements/claims/{claim_id}/paid")
def mark_reimbursement_claim_paid(claim_id: uuid.UUID, user: AuthUser, db: Database):
    membership = reimbursement_membership(db, user)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the team owner can mark claims as paid.")
    claim = db.scalar(
        select(ReimbursementClaim)
        .where(
            ReimbursementClaim.id == claim_id,
            ReimbursementClaim.team_id == membership.team_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Reimbursement claim not found.")
    if claim.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved claims can be marked as paid.")
    claim.status = "paid"
    claim.paid_at = datetime.now(timezone.utc)
    db.commit()
    employee = db.get(User, claim.employee_id)
    if employee is None:
        raise HTTPException(status_code=409, detail="The employee account is unavailable.")
    return reimbursement_claim_out(claim, employee, user)


@app.get("/api/v1/reimbursements/categories")
def list_reimbursement_categories(user: AuthUser, db: Database):
    membership = reimbursement_membership(db, user)
    categories = db.scalars(
        select(ReimbursementCategory)
        .where(
            ReimbursementCategory.team_id == membership.team_id,
            ReimbursementCategory.is_active == True,
        )
        .order_by(ReimbursementCategory.name)
    ).all()
    return {"items": [reimbursement_category_out(cat) for cat in categories]}


@app.get("/api/v1/reimbursements/categories/all")
def list_all_reimbursement_categories(user: AuthUser, db: Database):
    membership = reimbursement_owner_team(db, user)
    categories = db.scalars(
        select(ReimbursementCategory)
        .where(ReimbursementCategory.team_id == membership.team_id)
        .order_by(ReimbursementCategory.name)
    ).all()
    return {"items": [reimbursement_category_out(cat) for cat in categories]}


@app.post("/api/v1/reimbursements/categories", status_code=201)
def create_reimbursement_category(
    payload: ReimbursementCategoryCreate, user: AuthUser, db: Database
):
    membership = reimbursement_owner_team(db, user)
    existing = db.scalar(
        select(ReimbursementCategory.id).where(
            ReimbursementCategory.team_id == membership.team_id,
            ReimbursementCategory.name == payload.name.strip(),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A category with this name already exists.")
    category = ReimbursementCategory(
        team_id=membership.team_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        max_amount=payload.max_amount,
        currency=payload.currency.upper(),
        is_active=True,
        created_by=user.id,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A category with this name already exists.") from exc
    db.refresh(category)
    return reimbursement_category_out(category)


@app.patch("/api/v1/reimbursements/categories/{category_id}")
def update_reimbursement_category(
    category_id: uuid.UUID,
    payload: ReimbursementCategoryUpdate,
    user: AuthUser,
    db: Database,
):
    membership = reimbursement_owner_team(db, user)
    category = db.scalar(
        select(ReimbursementCategory).where(
            ReimbursementCategory.id == category_id,
            ReimbursementCategory.team_id == membership.team_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Reimbursement category not found.")
    if payload.name is not None:
        existing = db.scalar(
            select(ReimbursementCategory.id).where(
                ReimbursementCategory.team_id == membership.team_id,
                ReimbursementCategory.name == payload.name.strip(),
                ReimbursementCategory.id != category_id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="A category with this name already exists.")
        category.name = payload.name.strip()
    if payload.description is not None:
        category.description = payload.description.strip() if payload.description else None
    if payload.max_amount is not None:
        category.max_amount = payload.max_amount
    if payload.currency is not None:
        category.currency = payload.currency.upper()
    if payload.is_active is not None:
        category.is_active = payload.is_active
    db.commit()
    db.refresh(category)
    return reimbursement_category_out(category)


@app.delete("/api/v1/reimbursements/categories/{category_id}", status_code=204)
def delete_reimbursement_category(category_id: uuid.UUID, user: AuthUser, db: Database):
    membership = reimbursement_owner_team(db, user)
    category = db.scalar(
        select(ReimbursementCategory).where(
            ReimbursementCategory.id == category_id,
            ReimbursementCategory.team_id == membership.team_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Reimbursement category not found.")
    claim_count = db.scalar(
        select(func.count(ReimbursementClaim.id)).where(
            ReimbursementClaim.category_id == category_id,
        )
    )
    if claim_count and claim_count > 0:
        category.is_active = False
        db.commit()
        return Response(status_code=204)
    db.delete(category)
    db.commit()
    return Response(status_code=204)


class CategoryRequestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


@app.post("/api/v1/reimbursements/categories/request", status_code=201)
def request_reimbursement_category(
    payload: CategoryRequestCreate, user: AuthUser, db: Database
):
    membership = reimbursement_membership(db, user)
    if membership.role != "employee":
        raise HTTPException(status_code=403, detail="Only employees can request categories.")
    # Create a notification or pending request for the admin
    # For now, we'll create an inactive category that admin can activate
    existing = db.scalar(
        select(ReimbursementCategory.id).where(
            ReimbursementCategory.team_id == membership.team_id,
            ReimbursementCategory.name == payload.name.strip(),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A category with this name already exists.")
    category = ReimbursementCategory(
        team_id=membership.team_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        max_amount=Decimal("0"),  # Zero means no limit until admin sets it
        currency="INR",
        is_active=False,  # Inactive until admin reviews and activates
        created_by=user.id,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A category with this name already exists.") from exc
    db.refresh(category)
    return reimbursement_category_out(category)


@app.post("/api/v1/reimbursements/claims/check-limit")
def check_reimbursement_claim_limit(
    payload: ReimbursementClaimCreate, user: AuthUser, db: Database
):
    membership = reimbursement_membership(db, user)
    if membership.role != "employee":
        raise HTTPException(status_code=403, detail="Only employees can check claim limits.")
    if payload.category_id is None:
        raise HTTPException(status_code=422, detail="Category is required to check limits.")
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.expense_id, Invoice.user_id == user.id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    claim_amount = payload.claim_amount or invoice.total
    limit_check = check_claim_limit(db, user.id, payload.category_id, claim_amount)
    return limit_check


@app.post("/api/v1/reimbursements/claims", status_code=201)
def create_reimbursement_claim(
    payload: ReimbursementClaimCreate, user: AuthUser, db: Database
):
    membership = reimbursement_membership(db, user)
    if membership.role != "employee":
        raise HTTPException(status_code=403, detail="Team owners cannot submit claims for their own review.")
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.expense_id, Invoice.user_id == user.id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Expense record not found.")
    existing = db.scalar(
        select(ReimbursementClaim.id).where(ReimbursementClaim.invoice_id == invoice.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This expense has already been submitted for reimbursement.")
    
    claim_amount = payload.claim_amount or invoice.total
    
    if payload.category_id is not None:
        limit_check = check_claim_limit(db, user.id, payload.category_id, claim_amount)
        if not limit_check.can_claim:
            raise HTTPException(status_code=409, detail=limit_check.message or "Claim exceeds category limit.")
        category = db.get(ReimbursementCategory, payload.category_id)
    else:
        category = None
    
    claim = ReimbursementClaim(
        team_id=membership.team_id,
        employee_id=user.id,
        invoice_id=invoice.id,
        category_id=payload.category_id,
        merchant_name=invoice.seller_name or "Expense",
        expense_date=invoice.invoice_date,
        description=invoice.items[0].description if invoice.items else invoice.seller_name or "Expense",
        category=category.name if category else invoice.category,
        amount=claim_amount,
        currency=invoice.currency,
        reason=payload.reason,
    )
    db.add(claim)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This expense has already been submitted for reimbursement."
        ) from exc
    
    if payload.category_id is not None:
        record_user_claim(db, user.id, payload.category_id, claim.id, claim_amount)
        db.commit()
    
    return reimbursement_claim_out(claim, user)


@app.post("/api/v1/ai/ask")
async def ask_financial_question(payload: AssistantQuestion, user: AuthUser, db: Database):
    question_lower = payload.question.casefold()
    history_questions = " ".join(
        message.content.casefold() for message in payload.history if message.role == "user"
    )
    daily_spending_scenario = parse_daily_spending_scenario(payload.question)
    forecast_pattern = (
        r"\b(forecast|predict(?:ion)?|budget|remaining|rest of|left to spend|"
        r"how much can i spend|make it to|cross (?:the )?(?:week|weekend)|"
        r"through (?:this )?(?:week|weekend)|until (?:the )?(?:weekend|sunday|month end))\b"
    )
    forecast_question = bool(
        re.search(forecast_pattern, payload.question, re.IGNORECASE)
        or re.search(forecast_pattern, history_questions, re.IGNORECASE)
        or daily_spending_scenario is not None
    )
    if forecast_question:
        today = date.today()
        if re.search(r"\b(month|month-end|month end)\b", f"{question_lower} {history_questions}"):
            period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        elif re.search(r"\b(week|weekend|sunday)\b", f"{question_lower} {history_questions}"):
            period_end = today + timedelta(days=6 - today.weekday())
        else:
            period_end = today + timedelta(days=7)

        month_start = today.replace(day=1)
        recent_start = today - timedelta(days=28)
        expense_rows = db.execute(
            select(Invoice.currency, func.coalesce(func.sum(Invoice.total), 0))
            .where(
                Invoice.user_id == user.id,
                Invoice.invoice_date >= month_start,
                Invoice.invoice_date <= today,
            )
            .group_by(Invoice.currency)
        ).all()
        income_rows = db.execute(
            select(Income.currency, func.coalesce(func.sum(Income.amount), 0))
            .where(
                Income.user_id == user.id,
                Income.income_date >= month_start,
                Income.income_date <= today,
            )
            .group_by(Income.currency)
        ).all()
        recent_rows = db.execute(
            select(Invoice.currency, func.coalesce(func.sum(Invoice.total), 0))
            .where(
                Invoice.user_id == user.id,
                Invoice.invoice_date >= recent_start,
                Invoice.invoice_date < today,
            )
            .group_by(Invoice.currency)
        ).all()
        expenses_by_currency = {currency: Decimal(total) for currency, total in expense_rows}
        income_by_currency = {currency: Decimal(total) for currency, total in income_rows}
        recent_by_currency = {currency: Decimal(total) for currency, total in recent_rows}
        currencies = sorted(
            expenses_by_currency.keys() | income_by_currency.keys() | recent_by_currency.keys()
        ) or [user.preferred_currency]
        forecast = {
            currency: forecast_spending_window(
                today=today,
                period_end=period_end,
                currency=currency,
                month_income=income_by_currency.get(currency, Decimal("0")),
                month_expenses=expenses_by_currency.get(currency, Decimal("0")),
                recent_28_day_expenses=recent_by_currency.get(currency, Decimal("0")),
            )
            for currency in currencies
        }
        reported_cash = next(
            (
                parsed_cash
                for message in reversed(payload.history)
                if message.role == "user"
                if (parsed_cash := parse_user_available_cash(message.content)) is not None
            ),
            None,
        )
        if reported_cash is not None:
            days_until_target = max((period_end - today).days, 0)
            forecast.setdefault(user.preferred_currency, {
                "currency": user.preferred_currency,
                "period_end": period_end.isoformat(),
                "days_ahead_excluding_today": days_until_target,
            })["user_reported_available_cash"] = {
                "amount": str(reported_cash),
                "currency": user.preferred_currency,
                "basis": "User-reported amount from this conversation; not independently verified.",
                "daily_equivalent_before_upcoming_bills": (
                    str(amount(reported_cash / days_until_target))
                    if days_until_target else None
                ),
            }
        if daily_spending_scenario is not None:
            selected = forecast.get(user.preferred_currency) or forecast[currencies[0]]
            days = int(selected["days_ahead_excluding_today"])
            scenario_total = amount(daily_spending_scenario * days)
            recent_total = Decimal(str(selected["expected_spending_at_recent_pace"]))
            selected.update({
                "scenario_analysis": {
                    "type": "daily_spending",
                    "assumed_daily_spending": str(daily_spending_scenario),
                    "days_in_scenario": days,
                    "target_date": selected["period_end"],
                    "estimated_total_spending": str(scenario_total),
                    "recent_pace_estimated_total_for_same_period": str(recent_total),
                    "difference_vs_recent_pace": str(amount(scenario_total - recent_total)),
                    "recorded_net_after_scenario_not_bank_balance": str(
                        cash_flow(
                            Decimal(str(selected["recorded_net_not_bank_balance"])),
                            scenario_total,
                        )
                    ),
                    "method": (
                        "The user's daily-spend assumption is multiplied by the number of days in the "
                        "active forecast horizon. The comparison is with the recent recorded daily pace. "
                        "All values are estimates, not verified cash or a guarantee."
                    ),
                }
            })
            metrics = {
                "assistant_name": "Stark",
                "request": "Analyze the user's daily-spending hypothetical within the active forecast horizon.",
                "forecast": forecast,
                "important_limit": (
                    "Recorded income minus recorded invoice totals is not a bank balance or verified available "
                    "cash. No opening balance, unrecorded purchases, upcoming bills, or future income is available. "
                    "Do not call a calculated ceiling safe or guaranteed. If affordability cannot be established, "
                    "explain the limitation and ask for actual available cash and upcoming obligations."
                ),
            }
            return {
                "answer": await answer_financial_question(
                    payload.question,
                    metrics,
                    [message.model_dump() for message in payload.history],
                ),
                "metrics": {"forecast": forecast},
            }

        metrics = {
            "assistant_name": "Stark",
            "request": "Personal spending forecast",
            "forecast": forecast,
            "important_limit": (
                "Recorded income minus recorded invoice totals is not a bank balance or verified available cash. "
                "No opening balance, unrecorded purchases, upcoming bills, or future income is available. "
                "Do not call the calculated ceiling safe or guaranteed. If it is unavailable, say that a real "
                "available balance and upcoming obligations are needed to give a practical budget."
            ),
        }
        return {
            "answer": await answer_financial_question(
                payload.question,
                metrics,
                [message.model_dump() for message in payload.history],
            ),
            "metrics": {"forecast": forecast},
        }

    metrics = overview(user, db)
    month_start = date.today().replace(day=1)
    today = date.today()
    month_expenses = db.execute(
        select(Invoice.currency, func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.user_id == user.id, Invoice.invoice_date >= month_start, Invoice.invoice_date <= today)
        .group_by(Invoice.currency)
    ).all()
    month_income = db.execute(
        select(Income.currency, func.coalesce(func.sum(Income.amount), 0))
        .where(Income.user_id == user.id, Income.income_date >= month_start, Income.income_date <= today)
        .group_by(Income.currency)
    ).all()
    income_by_currency = {currency: Decimal(total) for currency, total in month_income}
    expenses_by_currency = {currency: Decimal(total) for currency, total in month_expenses}
    month_projection = {}
    for currency in sorted(income_by_currency.keys() | expenses_by_currency.keys()):
        observed_income = income_by_currency.get(currency, Decimal("0"))
        observed_expenses = expenses_by_currency.get(currency, Decimal("0"))
        month_projection[currency] = {
            "recorded_income_to_date": str(amount(observed_income)),
            "recorded_expenses_to_date": str(amount(observed_expenses)),
            "recorded_net_to_date": str(cash_flow(observed_income, observed_expenses)),
            "expense_pace_forecast": project_month_end(
                observed_expenses, today.day, calendar.monthrange(today.year, today.month)[1]
            ),
            "future_income_assumption": "No future income is assumed; only income already recorded this month is included.",
        }

    merchant_rows = db.execute(
        select(
            func.coalesce(Invoice.seller_name, "Uncategorized"),
            Invoice.currency,
            func.coalesce(func.sum(Invoice.total), 0),
            func.count(Invoice.id),
        )
        .where(Invoice.user_id == user.id)
        .group_by(Invoice.seller_name, Invoice.currency)
        .order_by(func.sum(Invoice.total).desc())
        .limit(20)
    ).all()
    income_source_rows = db.execute(
        select(
            Income.source_name,
            Income.currency,
            func.coalesce(func.sum(Income.amount), 0),
            func.count(Income.id),
        )
        .where(Income.user_id == user.id)
        .group_by(Income.source_name, Income.currency)
        .order_by(func.sum(Income.amount).desc())
        .limit(15)
    ).all()
    item_rows = db.execute(
        select(
            InvoiceItem.description,
            InvoiceItem.quantity,
            InvoiceItem.unit_price,
            InvoiceItem.line_total,
            Invoice.currency,
            Invoice.invoice_date,
            Invoice.seller_name,
            Invoice.invoice_number,
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id, InvoiceItem.line_total.is_not(None))
        .order_by(InvoiceItem.line_total.desc())
        .limit(10)
    ).all()
    unit_price_rows = db.execute(
        select(
            InvoiceItem.description,
            InvoiceItem.quantity,
            InvoiceItem.unit_price,
            Invoice.currency,
            Invoice.invoice_date,
            Invoice.seller_name,
            Invoice.invoice_number,
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(
            Invoice.user_id == user.id,
            InvoiceItem.line_total.is_(None),
            InvoiceItem.unit_price.is_not(None),
        )
        .order_by(InvoiceItem.unit_price.desc())
        .limit(5)
    ).all()
    product_rows = db.execute(
        select(
            func.min(InvoiceItem.description),
            Invoice.currency,
            func.sum(InvoiceItem.line_total),
            func.count(InvoiceItem.id),
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id, InvoiceItem.line_total.is_not(None))
        .group_by(func.lower(func.trim(InvoiceItem.description)), Invoice.currency)
        .order_by(func.sum(InvoiceItem.line_total).desc())
        .limit(15)
    ).all()
    line_item_count = db.scalar(
        select(func.count(InvoiceItem.id))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.user_id == user.id)
    ) or 0
    recent = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.user_id == user.id)
        .order_by(Invoice.invoice_date.desc().nullslast(), Invoice.created_at.desc())
        .limit(8)
    ).all()

    tokens = [
        token for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", payload.question.casefold())
        if token not in {"the", "and", "for", "with", "from", "what", "which", "were", "was", "how", "much", "most", "show", "tell", "about", "have", "bought", "spent", "item", "items"}
    ][:8]
    question_matches = []
    if tokens:
        search_terms = [
            condition
            for token in tokens
            for condition in (
                InvoiceItem.description.ilike(f"%{token}%"),
                Invoice.seller_name.ilike(f"%{token}%"),
                Invoice.invoice_number.ilike(f"%{token}%"),
            )
        ]
        question_matches = db.scalars(
            select(Invoice)
            .options(selectinload(Invoice.items))
            .join(Invoice.items)
            .where(Invoice.user_id == user.id, or_(*search_terms))
            .order_by(Invoice.invoice_date.desc().nullslast())
            .limit(8)
        ).all()

    metrics["website_capabilities"] = [
        "Upload and review PDF/image invoices and receipts; extracted details can be corrected before saving.",
        "Track confirmed expense invoices, their line items and taxes, and manually recorded income.",
        "View spending by invoice date, merchant, category, and currency; export financial records as CSV.",
        "AI category analysis, financial Q&A, and explicit what-if savings scenarios are available.",
        "The assistant cannot see bank balances, unsaved uploads, external accounts, or transactions not recorded in this account.",
    ]
    metrics["data_scope"] = {
        "access": "Only confirmed financial records belonging to the authenticated account are included.",
        "expense_count": metrics["expense_count"],
        "income_count": metrics["income_count"],
        "line_item_count": line_item_count,
        "note": "All-time totals and grouped summaries use the full account history. Item rankings are top 10 by line total; when line totals are unavailable, up to 5 unit-price records are provided separately. Repeated-item totals are top 15 and use only recorded line totals. The latest 8 invoice headers and up to 8 question-matched invoices (including their line details) are provided as examples; the matching query is account-wide.",
    }
    metrics["merchants_by_currency"] = [
        {"merchant": name, "currency": currency, "total": str(amount(total)), "invoice_count": count}
        for name, currency, total, count in merchant_rows
    ]
    metrics["income_sources_by_currency"] = [
        {"source": name, "currency": currency, "total": str(amount(total)), "record_count": count}
        for name, currency, total, count in income_source_rows
    ]
    metrics["highest_line_items"] = [
        {
            "description": description[:200], "quantity": str(quantity) if quantity is not None else None,
            "unit_price": str(unit_price) if unit_price is not None else None,
            "line_total": str(line_total) if line_total is not None else None,
            "comparison_amount": str(line_total),
            "comparison_basis": "recorded line total",
            "currency": currency,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "merchant": merchant, "invoice_number": invoice_number,
        }
        for description, quantity, unit_price, line_total, currency, invoice_date, merchant, invoice_number in item_rows
    ]
    metrics["unit_price_when_line_total_unavailable"] = [
        {
            "description": description[:200], "quantity": str(quantity) if quantity is not None else None,
            "unit_price": str(unit_price), "currency": currency,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "merchant": merchant, "invoice_number": invoice_number,
            "note": "Line total is unavailable, so quantity-adjusted cost cannot be compared.",
        }
        for description, quantity, unit_price, currency, invoice_date, merchant, invoice_number in unit_price_rows
    ]
    metrics["repeated_item_spend"] = [
        {"description": description[:200], "currency": currency, "recorded_total": str(amount(total)), "line_count": count}
        for description, currency, total, count in product_rows
    ]
    metrics["current_month_projection"] = month_projection

    def invoice_detail(row: Invoice, *, include_line_items: bool) -> dict:
        detail = {
            "date": row.invoice_date.isoformat() if row.invoice_date else None,
            "merchant": row.seller_name,
            "invoice_number": row.invoice_number,
            "total": str(row.total),
            "currency": row.currency,
            "category": row.category,
            "document_type": "confirmed expense invoice",
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "buyer_name": row.buyer_name,
            "seller_gstin": row.seller_gstin,
            "subtotal": str(row.subtotal) if row.subtotal is not None else None,
            "discount_total": str(row.discount_total) if row.discount_total is not None else None,
            "taxable_value": str(row.taxable_value) if row.taxable_value is not None else None,
            "cgst": str(row.cgst) if row.cgst is not None else None,
            "sgst": str(row.sgst) if row.sgst is not None else None,
            "igst": str(row.igst) if row.igst is not None else None,
            "cess": str(row.cess) if row.cess is not None else None,
            "other_charges": str(row.other_charges) if row.other_charges is not None else None,
            "payment_terms": row.payment_terms,
        }
        if include_line_items:
            detail["items"] = [
                {
                    "description": item.description[:200],
                    "category": item.category or row.category,
                    "hsn_sac_code": item.hsn_sac_code,
                    "quantity": str(item.quantity) if item.quantity is not None else None,
                    "unit": item.unit,
                    "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                    "discount": str(item.discount) if item.discount is not None else None,
                    "taxable_amount": str(item.taxable_amount) if item.taxable_amount is not None else None,
                    "gst_rate": str(item.gst_rate) if item.gst_rate is not None else None,
                    "cgst": str(item.cgst) if item.cgst is not None else None,
                    "sgst": str(item.sgst) if item.sgst is not None else None,
                    "igst": str(item.igst) if item.igst is not None else None,
                    "cess": str(item.cess) if item.cess is not None else None,
                    "line_total": str(item.line_total) if item.line_total is not None else None,
                }
                for item in row.items[:12]
            ]
        return detail

    metrics["recent_expense_details"] = [invoice_detail(row, include_line_items=False) for row in recent]
    recent_ids = {row.id for row in recent}
    metrics["question_matched_expenses"] = [
        invoice_detail(row, include_line_items=True)
        for row in question_matches[:15] if row.id not in recent_ids
    ]
    return {
        "answer": await answer_financial_question(
            payload.question,
            metrics,
            [message.model_dump() for message in payload.history],
        ),
        "metrics": {"income": metrics["income"], "expenses": metrics["expenses"], "cash_flow": metrics["cash_flow"]},
    }


@app.post("/api/v1/ai/what-if")
async def what_if(payload: WhatIfRequest, user: AuthUser, db: Database):
    supported_intent = re.search(r"\b(save|saving|set aside|put away|reduce (?:my )?(?:monthly )?(?:spending|expenses))\b", payload.question, re.I)
    if not supported_intent:
        raise HTTPException(status_code=422, detail="This scenario tool currently supports recurring savings or reduced monthly spending. Try “What if I save ₹3,000 each month?”")
    change = payload.monthly_amount
    match = re.search(r"(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d{1,2})?)", payload.question, re.I)
    if change is None and match:
        change = Decimal(match.group(1).replace(",", ""))
    if change is None:
        raise HTTPException(status_code=422, detail="Add a monthly amount, such as “save ₹3,000 each month”.")
    metrics = overview(user, db)
    currency = user.preferred_currency
    total_improvement = amount(change * payload.months)
    scenario = {
        **metrics, "assumption": f"{currency} {amount(change)} saved or reduced in monthly spending for {payload.months} months",
        "months": payload.months, "additional_recorded_net": str(total_improvement),
        "calculation": "monthly amount × months; assumes the same savings or spending reduction each month, without investment returns.",
    }
    explanation = await answer_financial_question(
        f"Explain this deterministic what-if scenario in plain language. Do not change the calculated result: {scenario['assumption']} improves recorded net by {currency} {total_improvement} over the scenario period, if the assumption holds. State that this excludes interest and investment returns. User context: {payload.question}",
        scenario,
    )
    return {"answer": explanation, "scenario": scenario}


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled request error method=%s path=%s", request.method, request.url.path)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})
