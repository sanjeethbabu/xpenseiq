import io
import logging
from pathlib import Path

import fitz
import pytesseract
from fastapi import HTTPException
from PIL import Image, ImageOps
from pytesseract import TesseractError, TesseractNotFoundError

from app.core.config import settings

logger = logging.getLogger(__name__)
PDF_PREVIEW_PIXEL_LIMIT = 40_000_000
OCR_IMAGE_PIXEL_LIMIT = 16_000_000
TESSERACT_RECEIPT_CONFIG = "--psm 4"

pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


def render_pdf_page(path: Path, page_number: int) -> tuple[bytes, int, int, int]:
    try:
        with fitz.open(path) as document:
            if page_number > document.page_count:
                raise HTTPException(status_code=416, detail="This PDF page does not exist.")
            page = document.load_page(page_number - 1)
            page_area = max(page.rect.width * page.rect.height, 1)
            scale = min(2, (PDF_PREVIEW_PIXEL_LIMIT / page_area) ** 0.5)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes("png"), document.page_count, pixmap.width, pixmap.height
    except HTTPException:
        raise
    except (fitz.FileDataError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail="This PDF page could not be displayed.") from exc


def _ocr_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Tesseract OCR is not installed or is not available to the document worker. "
            "Install Tesseract OCR, set TESSERACT_CMD to its executable path, and restart the worker."
        ),
    )


def _ocr_receipt_image(image: Image.Image) -> str:
    pixel_count = image.width * image.height
    scale = max(1, min(2, (OCR_IMAGE_PIXEL_LIMIT / pixel_count) ** 0.5))
    if scale > 1:
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return pytesseract.image_to_string(
        ImageOps.grayscale(image),
        config=TESSERACT_RECEIPT_CONFIG,
        timeout=45,
    )


def extract_text(path: Path, mime_type: str) -> str:
    if mime_type == "application/pdf":
        try:
            with fitz.open(path) as document:
                if document.page_count > settings.max_pdf_pages:
                    raise HTTPException(status_code=413, detail="This PDF has too many pages.")
                parts: list[str] = []
                for page in document:
                    text = page.get_text("text").strip()
                    if len(text) >= 25:
                        parts.append(text)
                    else:
                        page_area = max(page.rect.width * page.rect.height, 1)
                        scale = min(1.7, (PDF_PREVIEW_PIXEL_LIMIT / page_area) ** 0.5)
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                        parts.append(_ocr_receipt_image(image))
                return "\n\n".join(part for part in parts if part.strip())
        except HTTPException:
            raise
        except TesseractNotFoundError as exc:
            raise _ocr_unavailable() from exc
        except TesseractError as exc:
            logger.exception("Tesseract could not OCR PDF path=%s", path)
            raise HTTPException(status_code=422, detail="Tesseract could not read the scanned pages in this PDF. Try a clearer copy.") from exc
        except (fitz.FileDataError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="This PDF could not be read. Try exporting it again.") from exc
    try:
        with Image.open(path) as image:
            if image.width * image.height > 80_000_000:
                raise HTTPException(status_code=413, detail="This image has too many pixels.")
            image = ImageOps.exif_transpose(image).convert("L")
            return _ocr_receipt_image(image).strip()
    except HTTPException:
        raise
    except TesseractNotFoundError as exc:
        raise _ocr_unavailable() from exc
    except TesseractError as exc:
        logger.exception("Tesseract could not OCR image path=%s", path)
        raise HTTPException(status_code=422, detail="Tesseract could not read this image. Try a clearer JPG, PNG, or WebP copy.") from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Image processing failed for path=%s", path)
        raise HTTPException(status_code=422, detail=f"This image could not be read. Ensure it's a valid JPG, PNG, or WebP file. Error: {exc}") from exc
