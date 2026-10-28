# XpenzIQ

XpenzIQ turns invoices, receipts, and manually entered expenses into reviewable financial records. It includes a branded Next.js workspace, a FastAPI API, PostgreSQL persistence (including Supabase), a PostgreSQL-backed document queue, PDF text extraction, Tesseract OCR fallback, and Groq-backed invoice extraction and financial Q&A. Redis is not required.

## Configure Supabase and Groq

1. Copy `.env.example` to `.env`.
2. In Supabase, open **Project Settings → Database → Connection string** and copy a connection URI. Use the Supabase session pooler if your hosting provider cannot reach the direct database endpoint.
3. Set `DATABASE_URL` in `.env` to that URI. The app automatically configures Supabase's `postgresql://` URI scheme for its installed PostgreSQL driver; preserve the rest of the URI, including `sslmode=require`.
4. Set a unique `AUTH_SECRET` (at least 32 characters) and your server-side `GROQ_API_KEY`.
5. Keep `.env` private. Never put database or Groq credentials in frontend variables or commit them.

For a new/empty Supabase database, create the schema using **one** of these methods:

- Paste and run [`supabase_schema.sql`](./supabase_schema.sql) in the Supabase SQL Editor. **Warning:** this script drops and recreates the XpenzIQ app tables, deleting existing XpenzIQ users, expenses, budgets, and reimbursement claims. It seeds development-only `ADMIN001` and `EMP001` accounts with predictable temporary passwords that must be changed on first sign-in; replace the sample emails and use private credentials before production; or
- Run the Alembic migration with `alembic upgrade head` from `backend` using the configured `.env`.

Do not run both methods against the same new database.
For any database whose XpenzIQ data must be preserved, use Alembic migrations
instead of running the destructive SQL reset script.

For an existing database created with an earlier version of the schema, run
`alembic upgrade head` from `backend` before restarting the API and worker. This
applies any pending migrations, including period-based budget storage and
reimbursement teams and claims.

## Run locally

1. Install Node.js 20+ and Python 3.11+.
2. Install Tesseract OCR with the English language pack if scanned-image OCR is needed.
3. Set the `.env` values above.
4. In `frontend`, run `npm install` then `npm run dev`.
5. In `backend`, create a virtual environment, run `pip install -r requirements.txt`, then (if you did not apply the SQL file in Supabase) `alembic upgrade head`.
6. Start the API from `backend`: `uvicorn app.main:app --reload --port 8000`.
7. In a second `backend` terminal, start the database queue worker: `python -m app.worker`.

Alternatively, with Docker Engine installed, `docker compose up --build` starts the frontend, API, and PostgreSQL queue worker using the `DATABASE_URL` in `.env`. Run migrations first with `docker compose run --rm api alembic upgrade head` unless you already created the schema in Supabase SQL Editor.

Open http://localhost:3000. Register an account to use the authenticated workspace. API docs are at http://localhost:8000/docs. Liveness is `/health`; database readiness is `/health/ready`.

## Architecture notes

- The browser uses HttpOnly, SameSite cookies for access tokens; Groq and database credentials stay on the server.
- Expenses can be entered manually or extracted from uploaded invoices and receipts. Manual records are stored with a categorized line item so they appear in category reports consistently.
- Create one spending limit per currency for each calendar quarter, half-year, or full year. Budget progress uses confirmed expenses whose invoice dates fall inside the selected period; existing income records remain stored but are no longer entered from the web app.
- Reimbursements use separate teams: an admin creates a team and adds employees in the Users tab. Each employee receives an `EMP###` sign-in ID and the same temporary password, which must be changed at first sign-in. Employees submit saved expenses with a business purpose; the admin approves or rejects claims. Approved claims are paid outside the app and then marked paid manually. A saved expense can only be claimed once, admins cannot submit claims for their own review, and original receipt uploads are not retained as reimbursement attachments.
- Document rows with `status = 'queued'` are the durable work queue. The API persists an upload and its queued document record in PostgreSQL; the worker claims queued rows with `FOR UPDATE SKIP LOCKED`, so concurrent workers do not take the same job. Abandoned processing rows can be reclaimed after the worker lease expires.
- Uploads with the same filename are parsed before their financial contents are compared by AI. Matching content is rejected as a duplicate and identifies the existing file; different purchases can proceed to the normal review flow. Exact byte-for-byte uploads are rejected using their SHA-256 fingerprint before parsing and also identify the existing file.
- The worker polls PostgreSQL and periodically removes expired temporary uploads. No Redis, Celery, or separate scheduler is required.
- API and worker must use the same `DATABASE_URL` and have access to the same temporary upload files. Docker Compose provides a shared volume. When deploying API and worker separately, mount shared private storage at the same `TEMP_UPLOAD_DIR` path in both services.
- PDF text is extracted with PyMuPDF; Tesseract uses receipt/table-aware page segmentation for scanned PDF pages and images so item quantities, rates, and amounts are less likely to be lost. PDF originals are rendered one page at a time for reliable visual comparison during review. Original uploads are temporary and cleaned after processing; structured invoice data remains for review.
- Groq extraction output is validated with Pydantic and deterministic Decimal checks. When the model misses a total, the backend recovers it only from an explicit, clearly labeled OCR total row; it does not synthesize a total from incomplete line items. Confirming an extraction creates an invoice and normalized line-item rows.
- Groq assigns a category to each invoice line from its printed category label and description, so a mixed invoice can contribute to several spending categories. During review, users can accept or change each line-item suggestion; there is no separate invoice-level AI category control. Category reports allocate each invoice's final total across its categorized line amounts, so invoice-level discounts and other total adjustments are reflected while preserving the category split. Older records without line totals use the invoice category and total; the dashboard can analyze uncategorized line items on request.
- Dashboard figures and reports are derived from the authenticated user's confirmed records; empty accounts show no fabricated financial values.

## Configuration

| Setting | Needed for | Example |
| --- | --- | --- |
| `AUTH_SECRET` | Signing secure session cookies | Generate a unique random value of at least 32 characters |
| `ACCESS_TOKEN_MINUTES` | Session lifetime | `720` |
| `DATABASE_URL` | Supabase/PostgreSQL and the document queue | `postgresql+psycopg://.../postgres?sslmode=require` |
| `GROQ_API_KEY` | Invoice parsing and AI assistant | Your Groq API key; keep it server-side |
| `GROQ_MODEL` | Model selection | `openai/gpt-oss-120b` |
| `GROQ_BASE_URL` | Groq-compatible API endpoint | `https://api.groq.com/openai/v1` |
| `TESSERACT_CMD` | OCR executable | `tesseract` or its absolute executable path |
| `MAX_UPLOAD_MB`, `MAX_PDF_PAGES` | Upload resource limits | `20` MB and `40` pages |
| `TEMP_UPLOAD_DIR`, `DOCUMENT_RETENTION_HOURS` | Temporary uploads and expiry | `./backend/uploads`, `24` hours |
| `FRONTEND_URL` | Allowed browser origin | `http://localhost:3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend API address | `http://localhost:8000/api/v1` |

For production, use HTTPS, a long unique `AUTH_SECRET`, managed PostgreSQL, an exact `FRONTEND_URL`, private shared temporary storage for the API and worker, and separate API/worker services. Do not expose Groq or database credentials through `NEXT_PUBLIC_*`. Apply Alembic migrations as a deployment step, not from API startup.

## Limitations

Email verification/password reset, account deletion/export, full CRUD coverage for every finance entity, real-time push updates, and production object storage are not included. OCR needs Tesseract installed on the API/worker host. If Groq is not configured, parsing and assistant requests return an actionable error rather than synthetic results. Do not treat extracted or AI-generated information as tax, investment, or legal advice.
