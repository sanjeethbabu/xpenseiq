# How XpenzIQ Works: Click to Screen

This guide follows an action in the browser all the way to the screen you see.
The main idea is:

> A click is handled by the frontend. If it needs backend work, the frontend
> sends an HTTP request. The backend processes it and sends a response. The
> frontend uses that response to update the screen.

## The parts of the application

| Part | What it does | Main files |
|---|---|---|
| Frontend | Shows forms, buttons, navigation, and results in the browser | `frontend/app/page.tsx` |
| Next.js server | Serves the frontend and forwards matching API requests | `frontend/next.config.mjs` |
| FastAPI backend | Handles API requests, applies application rules, and reads or writes data | `backend/app/main.py` |
| Database | Persists users, documents, expenses, budgets, and claims | `backend/app/models.py`, `backend/app/db/session.py` |
| Background worker | Processes uploaded documents outside the immediate web request | `backend/app/worker.py` |
| Backend helpers | Do focused work called by API routes or the worker | `backend/app/ai.py`, `backend/app/documents.py`, `backend/app/finance.py` |

When running locally, Next.js normally listens on port `3000` and FastAPI on
port `8000`. A port is part of a network address: it tells the computer which
running server should receive a request.

## Example 1: Click Sign in

### A. The form captures what you type

The login inputs are rendered by `AuthScreen` in `frontend/app/page.tsx`.
Their `onChange` handlers update React state in `HomePage`:

- The email or employee ID is stored in `authEmail`.
- The password is stored in `authPassword`.

React state is data the page remembers while it is open. Updating it causes
React to render the current values in the form.

### B. Submitting the form calls the login handler

`HomePage` passes its `submitAuth` function to `AuthScreen` as the `onSubmit`
prop. The form uses that prop as its submit handler. When you click **Sign in**
or press Enter, the browser submits the form and calls `submitAuth`.

`submitAuth` stops the browser's default form navigation, builds an object
from `authEmail` and `authPassword`, then converts it to JSON text with
`JSON.stringify`, for example:

```json
{"email":"alex@example.com","password":"example-password"}
```

### C. The frontend sends an HTTP request

`submitAuth` calls the app's helper function `request` with the path
`/auth/login`, the HTTP method `POST`, and the JSON body.

The helper is also in `frontend/app/page.tsx`. It combines that path with the
API prefix `/api/v1`, then calls the browser's built-in `fetch`:

```text
request path:       /auth/login
API prefix:         /api/v1
URL sent by fetch:  /api/v1/auth/login
```

An **HTTP request** is a message sent to a server. `POST` means the message
is submitting data for the server to process. The helper also marks the body
as JSON and includes cookies.

### D. Next.js forwards the request to FastAPI

The browser sends `/api/v1/auth/login` to the same site that served the page,
which is the Next.js server. Next.js reads the rewrite rule in
`frontend/next.config.mjs`:

```text
source:      /api/:path*
destination: http://localhost:8000/api/:path*
```

`:path*` means “match and keep the remaining path.” So Next.js forwards this
request:

```text
Browser → Next.js:  /api/v1/auth/login
Next.js → FastAPI:  http://localhost:8000/api/v1/auth/login
```

The files are not calling or importing each other here. The browser sends a
request to a URL, and Next.js applies its configured forwarding rule.

### E. FastAPI handles the request and sends a response

FastAPI is running the application created in `backend/app/main.py`. It looks
for a route matching both the request method and path:

```text
POST /api/v1/auth/login
```

That route calls the `login` function. FastAPI parses the JSON body and
validates it using the `UserLogin` schema in `backend/app/schemas.py`. The
login function then:

1. Looks up the user by email or employee ID in the database.
2. Checks the entered password against the stored password hash.
3. If they match, sets a session cookie and returns user information.
4. If they do not match, returns an error response instead.

The database models are defined in `backend/app/models.py`; database sessions
are provided by `backend/app/db/session.py`.

### F. The frontend uses the response to choose what to show

The response travels back through Next.js to the browser. The `request` helper
returns the successful response data, or raises an error if the response
failed.

- **Wrong credentials:** `submitAuth` catches the error, saves its message in
  `authError`, and React displays it on the login form.
- **Successful login:** `submitAuth` calls `setUser` with the returned user.
  React renders again. The login screen is shown only when there is no user.
  The default `view` is `"Dashboard"`, so a user who does not need to change
  a temporary password sees the Dashboard.
- **Temporary password:** if the returned user has `must_change_password`
  set, React shows the password-change screen first.

Login does not send a new HTML page from FastAPI. FastAPI checks the
credentials and returns data; React changes the displayed screen.

## Example 2: Click Dashboard or Settings

The sidebar buttons call `setView` with the selected section name. React
renders the matching section inside the existing page:

```text
Click Dashboard → setView("Dashboard") → React shows Dashboard
Click Settings  → setView("Settings")  → React shows Settings
```

This is a frontend-only screen change. It does not change the URL or require
a FastAPI request just to switch sections. Some sections may make API requests
when you perform actions or need data.

## How the Dashboard gets its data

After a user is set, a React effect calls `refreshData` in `page.tsx`.
`refreshData` uses `request` to ask FastAPI for data such as the overview,
expenses, documents, budgets, and reimbursements. FastAPI processes each
endpoint and returns data (usually read from the database). The frontend
stores the results in React state, and React displays the updated values.

```text
React asks for data
  → request / fetch
  → Next.js rewrite
  → matching FastAPI route
  → database read
  ← JSON response
  → React state update
  → updated screen
```

## Example 3: Upload a document

Some actions take longer than one request. For a document upload:

1. The frontend sends the selected file to a FastAPI upload endpoint.
2. The backend records the document as queued for processing.
3. The background worker in `backend/app/worker.py` picks it up.
4. The worker uses `documents.py` to read PDF or image text and `ai.py` to
   interpret invoice details.
5. The frontend checks the document's status periodically.
6. When processing is complete, React updates the document in the UI so it can
   be reviewed. Confirming the review then sends another API request to save
   the expense.

The API route, worker, and helper modules are all backend code, but each has a
different job: routes receive web requests, the worker handles queued tasks,
and helper modules perform focused processing.

## Quick vocabulary

- **Click handler:** frontend function that runs after a button or form action.
- **State:** data React remembers, such as the current user or selected page.
- **HTTP request:** a message sent from the browser/frontend to the backend.
- **Route/endpoint:** a method-and-path combination that FastAPI handles, such
  as `POST /api/v1/auth/login`.
- **Response:** the backend's reply, containing data or an error.
- **Rewrite:** a Next.js forwarding rule that sends matching request URLs to
  another server.
- **Helper function:** reusable code called by a route or worker to do a
  focused task, such as OCR, AI analysis, or financial calculations.

## Running locally

Start the backend from `backend`:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Start the frontend from `frontend` in another terminal:

```powershell
npm run dev
```

Open `http://localhost:3000`. The browser displays the frontend; API calls
matching `/api/*` are forwarded by Next.js to the backend at port `8000`.
