# Run XpenzIQ locally

Your API is already running and its health check returned `200 OK`. Keep that
terminal open. Open two more PowerShell terminals for the worker and frontend.

## Terminal 1 — API (already running)

If you need to restart it, paste:

```powershell
Set-Location D:\xpenziq\backend
D:\xpenziq\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

## Terminal 2 — document-processing worker

Paste:

```powershell
Set-Location D:\xpenziq\backend
D:\xpenziq\.venv\Scripts\python.exe -m app.worker
```

## Terminal 3 — web app

Paste:

```powershell
Set-Location D:\xpenziq\frontend
npm run dev
```

When the frontend reports that it is ready, open [http://localhost:3000](http://localhost:3000).
Keep all three terminals running while using the app. Press `Ctrl+C` in a
terminal to stop that service.

## Check the API

Open [http://localhost:8000/health/ready](http://localhost:8000/health/ready).
A healthy API responds with `{"status":"ready","service":"xpenziq-api"}`.

## Notes

- After updating the app, run the database migration from the backend terminal:

  ```powershell
  Set-Location D:\xpenziq\backend
  D:\xpenziq\.venv\Scripts\python.exe -m alembic upgrade head
  ```

  This applies pending database changes, including period-based budgets,
  reimbursement claims, and employee sign-in IDs.
- JPG, PNG, and WebP uploads are read with Tesseract OCR. Install Tesseract OCR
  with the English language pack before uploading images. On Windows, if
  Tesseract is not on `PATH`, set `TESSERACT_CMD` in the root `.env` to its
  executable, for example:

  ```dotenv
  TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
  ```

  Restart the document worker after installing Tesseract or changing this
  setting.
- Redis is not required. The worker uses PostgreSQL (Supabase) for its queue.
- Restart the document worker after changing OCR or extraction code. Documents
  already waiting for review keep their saved extraction; upload the original
  again to run the improved parser on them.
- Keep `.env` in `D:\xpenziq`; do not paste its secret values into a terminal
  command or share them.
- Text-based PDFs can be processed without Tesseract.
