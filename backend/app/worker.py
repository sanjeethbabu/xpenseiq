import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.ai import extract_invoice, same_invoice_content
from app.core.config import settings
from app.db.session import SessionLocal
from app.documents import extract_text
from app.finance import has_duplicate_invoice
from app.models import Document, Invoice
from app.schemas import EXPENSE_CATEGORIES, InvoiceExtraction

logger = logging.getLogger(__name__)
PROCESSING_LEASE = timedelta(minutes=30)
POLL_INTERVAL_SECONDS = 2
CLEANUP_INTERVAL_SECONDS = 3600


def _existing_filename(db: Session, invoice: Invoice) -> str | None:
    if invoice.document_id is None:
        return None
    return db.scalar(select(Document.filename).where(Document.id == invoice.document_id))


def _set_stage(db: Session, document: Document, stage: str, status: str = "processing") -> None:
    document.stage = stage
    document.status = status
    document.updated_at = datetime.now(timezone.utc)
    db.commit()


def _stored_invoice_extraction(invoice: Invoice) -> InvoiceExtraction:
    category = invoice.category if invoice.category in EXPENSE_CATEGORIES else "Other"
    return InvoiceExtraction(
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        currency=invoice.currency or "INR",
        seller_name=invoice.seller_name,
        buyer_name=invoice.buyer_name,
        seller_gstin=invoice.seller_gstin,
        buyer_gstin=invoice.buyer_gstin,
        billing_address=invoice.billing_address,
        shipping_address=invoice.shipping_address,
        place_of_supply=invoice.place_of_supply,
        payment_terms=invoice.payment_terms,
        subtotal=invoice.subtotal,
        discount_total=invoice.discount_total,
        taxable_value=invoice.taxable_value,
        cgst=invoice.cgst,
        sgst=invoice.sgst,
        igst=invoice.igst,
        cess=invoice.cess,
        other_charges=invoice.other_charges,
        round_off=invoice.round_off,
        total=invoice.total,
        category=category,
        line_items=[
            {
                "description": item.description,
                "category": item.category if item.category in EXPENSE_CATEGORIES else None,
                "hsn_sac_code": item.hsn_sac_code,
                "quantity": item.quantity,
                "unit": item.unit,
                "unit_price": item.unit_price,
                "discount": item.discount,
                "taxable_amount": item.taxable_amount,
                "gst_rate": item.gst_rate,
                "cgst": item.cgst,
                "sgst": item.sgst,
                "igst": item.igst,
                "cess": item.cess,
                "line_total": item.line_total,
            }
            for item in invoice.items
        ],
    )


def claim_next_document() -> str | None:
    """Atomically claim one queued document, reclaiming abandoned work after its lease."""
    now = datetime.now(timezone.utc)
    stale_before = now - PROCESSING_LEASE
    with SessionLocal() as db:
        statement = (
            select(Document)
            .where(
                or_(
                    Document.status == "queued",
                    and_(
                        Document.status == "processing",
                        Document.updated_at < stale_before,
                    ),
                )
            )
            .order_by(Document.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        document = db.scalar(statement)
        if document is None:
            return None
        logger.info(f"Worker: Claimed document {document.id}, temp_path: {document.temp_path}")
        document.status = "processing"
        document.stage = "Starting document processing"
        document.updated_at = now
        document.error_code = None
        document.error_message = None
        db.commit()
        return str(document.id)


def process_document(document_id: str) -> None:
    db = SessionLocal()
    document = None
    source = None
    try:
        document = db.get(Document, UUID(document_id))
        if document is None or document.status != "processing":
            logger.info(f"Worker: Document {document_id} not found or not processing, status: {document.status if document else 'None'}")
            return
        source = Path(document.temp_path) if document.temp_path else None
        logger.info(f"Worker: Processing {document_id}, temp_path: '{document.temp_path}', source exists: {source.exists() if source else 'None'}")
        if source is None or not source.exists():
            raise HTTPException(status_code=422, detail="The temporary document file is no longer available.")
        _set_stage(db, document, "Extracting text and reading pages")
        text = extract_text(source, document.mime_type)
        if len(text.strip()) < 12:
            raise HTTPException(status_code=422, detail="No readable invoice text was found. Try a clearer scan.")
        _set_stage(db, document, "Interpreting invoice fields with Groq")
        logger.info(f"Worker: Calling extract_invoice for {document_id}")
        extracted = asyncio.run(extract_invoice(text))
        logger.info(f"Worker: extract_invoice returned for {document_id}")
        same_name_checked = False
        if getattr(document, "filename", None):
            same_name_candidates = db.scalars(
                select(Invoice)
                .join(Document, Invoice.document_id == Document.id)
                .options(selectinload(Invoice.items))
                .where(
                    Invoice.user_id == document.user_id,
                    Document.id != document.id,
                    func.regexp_replace(
                        func.lower(Document.filename), r"\.[^.]*$", ""
                    ) == Path(document.filename).stem.casefold(),
                )
            ).all()
            same_name_checked = bool(same_name_candidates)
            for candidate in same_name_candidates:
                if asyncio.run(same_invoice_content(extracted, _stored_invoice_extraction(candidate))):
                    existing_filename = _existing_filename(db, candidate)
                    document.status = "failed"
                    document.stage = "Duplicate invoice detected"
                    document.error_code = "DUPLICATE_INVOICE"
                    document.error_message = (
                        f"This upload matches existing file: {existing_filename}."
                        if existing_filename
                        else "This invoice already exists in your expenses. The uploaded file was not added again."
                    )
                    document.temp_path = None
                    document.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    source.unlink(missing_ok=True)
                    source = None
                    logger.info("Worker: Rejected same-name duplicate document_id=%s", document_id)
                    return
            if same_name_checked:
                document.allow_duplicate_invoice = True
        if (
            not same_name_checked
            and extracted.invoice_number
            and extracted.invoice_date
            and extracted.total is not None
        ):
            candidates = db.scalars(select(Invoice).where(
                Invoice.user_id == document.user_id,
                Invoice.invoice_date == extracted.invoice_date,
                Invoice.total == extracted.total,
            )).all()
            matching_invoice = next(
                (candidate for candidate in candidates if has_duplicate_invoice(extracted, [candidate])),
                None,
            )
            if matching_invoice is not None:
                existing_filename = _existing_filename(db, matching_invoice)
                document.status = "failed"
                document.stage = "Duplicate invoice detected"
                document.error_code = "DUPLICATE_INVOICE"
                document.error_message = (
                    f"This upload matches existing file: {existing_filename}."
                    if existing_filename
                    else "This invoice already exists in your expenses. The uploaded file was not added again."
                )
                document.temp_path = None
                document.updated_at = datetime.now(timezone.utc)
                db.commit()
                source.unlink(missing_ok=True)
                source = None
                logger.info(f"Worker: Rejected duplicate invoice document_id={document_id}")
                return
        _set_stage(db, document, "Checking totals and preparing your review")
        document.extraction = extracted.model_dump(mode="json")
        document.status = "review"
        document.stage = "Ready for your review"
        document.error_code = None
        document.error_message = None
        document.updated_at = datetime.now(timezone.utc)
        logger.info(f"Worker: Document {document_id} set to review, temp_path: {document.temp_path}")
        db.commit()
        logger.info(f"Worker: Document {document_id} committed, temp_path after commit: {document.temp_path}")
    except Exception as exc:
        logger.exception("Document processing failed for document_id=%s", document_id)
        db.rollback()
        if document is not None:
            current = db.get(Document, document.id)
            if current:
                current.status = "failed"
                current.stage = "Could not finish processing"
                current.error_code = "AI_PROVIDER_UNAVAILABLE" if "Groq" in str(exc) or "configured" in str(exc).lower() else "DOCUMENT_PROCESSING_FAILED"
                current.error_message = exc.detail if isinstance(exc, HTTPException) else "Processing could not be completed. Check the file or retry."
                current.updated_at = datetime.now(timezone.utc)
                db.commit()
    finally:
        if source and document:
            if document.status == "review":
                logger.info(f"Worker: Keeping temp file for review: {source}")
            else:
                logger.info(f"Worker: Keeping temp file for failed/preview: {source} (status: {document.status})")
        db.close()


def cleanup_expired_uploads() -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - settings.document_retention_hours * 3600
    directory = settings.temp_upload_dir
    if not directory.exists():
        return 0
    removed = 0
    with SessionLocal() as db:
        for path in directory.iterdir():
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except FileNotFoundError:
                continue
            document = db.scalar(select(Document).where(Document.temp_path == str(path)))
            if document and document.status in {"queued", "processing"}:
                document.status = "failed"
                document.stage = "Temporary upload expired"
                document.error_code = "PROCESSING_TIMEOUT"
                document.error_message = "This upload expired before processing could finish. Upload the file again."
                document.temp_path = None
                document.updated_at = datetime.now(timezone.utc)
                db.commit()
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.exception("Could not remove expired upload path=%s", path)
    return removed


def run_worker() -> None:
    logger.info("PostgreSQL document worker started")
    next_cleanup = 0.0
    while True:
        try:
            document_id = claim_next_document()
            if document_id is not None:
                process_document(document_id)
                continue
            now = time.monotonic()
            if now >= next_cleanup:
                cleanup_expired_uploads()
                next_cleanup = now + CLEANUP_INTERVAL_SECONDS
        except Exception:
            logger.exception("Database document worker iteration failed")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_worker()
