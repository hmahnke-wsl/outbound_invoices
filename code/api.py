"""FastAPI JSON API for the outbound invoice dashboard.

Run from the project folder: `uv run uvicorn api:build_app --factory --app-dir code --port 5040`
"""

import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AfterValidator, BaseModel, BeforeValidator, StrictFloat, StrictInt

from auth import SESSION_COOKIE, AuthSettings, DirectoryUnavailable, LdapAuthenticator, LoginLimiter, SessionCodec
from db import (DEFAULT_DB, get_invoice_history, get_pdf_file, init_db, last_refresh, list_ignored,
                list_needs_attention, list_open, list_paid, record_refresh, update_invoice)
from summary import days_open, summarize

import import_pdfs

Status = Literal["open", "paid"]
Amount = StrictInt | StrictFloat  # strict, so true/false are not taken as 1/0


def _not_blank(value):
    if not value.strip():
        raise ValueError("customer is required")
    return value


def _iso_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("must be a date as YYYY-MM-DD") from None
    return value


def _true_or_false(value):
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


Customer = Annotated[str, AfterValidator(_not_blank)]
IsoDate = Annotated[str, AfterValidator(_iso_date)]
Flag = Annotated[bool, BeforeValidator(_true_or_false)]


class InvoiceUpdate(BaseModel):
    """An edit: only the fields sent are changed. `status` "paid" needs `paid_at`; "open" clears it.
    `ignored` hides or restores a flagged invoice."""
    customer: Customer = None
    amount: Amount = None
    invoice_number: str | None = None
    invoice_date: IsoDate | None = None
    due_date: IsoDate | None = None
    terms: str | None = None
    currency: str | None = None
    memo: str | None = None
    po_number: str | None = None
    status: Status = None
    paid_at: IsoDate | None = None
    ignored: Flag = None


class Updated(BaseModel):
    id: int


# Response shapes. They mirror web/src/types.ts; keep the two in step.

class Invoice(BaseModel):
    id: int
    customer: str
    invoice_number: str | None
    invoice_date: str | None
    terms: str | None
    due_date: str | None
    amount: float
    currency: str
    memo: str | None
    po_number: str | None
    status: Status
    paid_at: str | None
    overdue: bool
    days_open: int | None
    source_link: str | None
    has_pdf: bool
    sent_at: str | None


class HistoryEntry(BaseModel):
    status: Status
    changed_at: str
    source: Literal["import", "manual"]


class AttentionItem(BaseModel):
    """A flagged invoice (Needs attention) or an ignored one."""
    id: int
    customer: str
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    amount: float | None
    currency: str
    reason: str | None
    source_link: str | None
    has_pdf: bool


class Money(BaseModel):
    currency: str
    amount: float


class Total(BaseModel):
    count: int
    amounts: list[Money]


class AgingBucket(Total):
    label: str


class AverageDays(BaseModel):
    days: float | None
    based_on: int


class Health(BaseModel):
    status: Literal["good", "watch", "action"] | None
    reason: str | None


class SummaryHealth(BaseModel):
    overdue: Health
    days_open: Health


class Summary(BaseModel):
    outstanding: Total
    overdue: Total
    days_overdue: AverageDays
    days_open: AverageDays
    aging: list[AgingBucket]
    health: SummaryHealth


class IngestResult(BaseModel):
    """What one import found. `new_invoice_ids` are the invoices first stored by this run."""
    saved: int
    flagged: int
    new_invoice_ids: list[int]


class LastRefresh(BaseModel):
    finished_at: str | None


# Reachable without a session: the login flow itself, and the container healthcheck.
_PUBLIC_API_PATHS = ("/api/auth/", "/api/health")


class LoginRequest(BaseModel):
    username: str
    password: str


def create_app(db_path=DEFAULT_DB, today=None, now=None, attachments_dir=None, run_ingest=None,
               auth: AuthSettings | None = None, authenticate=None, clock=time.time):
    """Build the app. `today` (ISO date) and `now` (ISO datetime) can be injected for testing.

    Invoice PDFs are served from `attachments_dir` (default: `attachments/` beside the database).
    `run_ingest(conn, attachments_dir)` is what Refresh calls (default: import the PDFs in INBOX_DIR).

    `auth=None` means no login gate (local dev with AUTH_DISABLED, and every test that isn't about auth).
    """
    app = FastAPI(title="Outbound Invoices")

    if auth is not None:
        sessions = SessionCodec(auth, clock)
        limiter = LoginLimiter(clock)
        authenticate = authenticate or LdapAuthenticator(auth)

        @app.middleware("http")
        async def require_session(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/") and not path.startswith(_PUBLIC_API_PATHS):
                if sessions.decode(request.cookies.get(SESSION_COOKIE)) is None:
                    return JSONResponse({"detail": "not signed in"}, status_code=401)
            return await call_next(request)

        @app.post("/api/auth/login")
        def login(body: LoginRequest) -> JSONResponse:
            if limiter.is_locked(body.username):
                raise HTTPException(429, "Too many attempts -- try again in 15 minutes")
            try:
                ok = authenticate(body.username, body.password)
            except DirectoryUnavailable:
                raise HTTPException(503, "Can't reach the login server -- try again shortly")
            if not ok:
                limiter.record_failure(body.username)
                raise HTTPException(401, "Incorrect username or password")
            limiter.record_success(body.username)
            resp = JSONResponse({"user": body.username})
            resp.set_cookie(SESSION_COOKIE, sessions.encode(body.username),
                            httponly=True, samesite="lax", secure=auth.cookie_secure,
                            max_age=auth.session_max_age_seconds)
            return resp

        @app.post("/api/auth/logout")
        def logout() -> JSONResponse:
            resp = JSONResponse({"user": None})
            resp.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax", secure=auth.cookie_secure)
            return resp

        @app.get("/api/auth/me")
        def me(request: Request) -> dict:
            user = sessions.decode(request.cookies.get(SESSION_COOKIE))
            if user is None:
                raise HTTPException(401, "not signed in")
            return {"user": user}

    init_db(db_path).close()
    pdf_dir = Path(attachments_dir or Path(db_path).resolve().parent / "attachments")
    ingest = run_ingest or (lambda conn, attachments: import_pdfs.import_folder(conn, attachments_dir=attachments))
    ingest_lock = threading.Lock()

    def current_date():
        return today or date.today().isoformat()

    def current_time():
        return now or datetime.now().astimezone().isoformat(timespec="seconds")

    def with_timing(invoices):
        """Adds `overdue` and `days_open` as of today."""
        today_ = date.fromisoformat(current_date())
        for i in invoices:
            i["overdue"] = i["status"] == "open" and bool(i["due_date"]) and i["due_date"] < current_date()
            i["days_open"] = days_open(i, today_)
        return invoices

    def get_db():
        """One connection per request, closed once the response is sent."""
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/invoices", response_model=list[Invoice])
    def get_invoices(conn=Depends(get_db)):
        """Open (unpaid) invoices."""
        return with_timing(list_open(conn))

    @app.get("/api/paid-invoices", response_model=list[Invoice])
    def get_paid_invoices(conn=Depends(get_db)):
        return with_timing(list_paid(conn))

    @app.get("/api/summary", response_model=Summary)
    def get_summary(conn=Depends(get_db)):
        return summarize(list_open(conn), current_date())

    @app.patch("/api/invoices/{invoice_id}", response_model=Updated,
               responses={400: {"description": "The edit breaks a business rule"}, 404: {"description": "No such invoice"}})
    def patch_invoice(invoice_id: int, edit: InvoiceUpdate, conn=Depends(get_db)):
        try:
            found = update_invoice(conn, invoice_id, edit.model_dump(exclude_unset=True), current_time())
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not found:
            raise HTTPException(404, "invoice not found")
        return {"id": invoice_id}

    @app.get("/api/invoices/{invoice_id}/history", response_model=list[HistoryEntry])
    def get_history(invoice_id: int, conn=Depends(get_db)):
        return get_invoice_history(conn, invoice_id)

    @app.get("/api/invoices/{invoice_id}/pdf", response_class=FileResponse,
             responses={200: {"content": {"application/pdf": {}}}, 404: {"description": "No PDF for this invoice"}})
    def get_invoice_pdf(invoice_id: int, conn=Depends(get_db)):
        name = get_pdf_file(conn, invoice_id)
        path = (pdf_dir / name).resolve() if name else None
        if not path or not path.is_relative_to(pdf_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "invoice PDF not found")
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.get("/api/needs-attention", response_model=list[AttentionItem])
    def get_needs_attention(conn=Depends(get_db)):
        return list_needs_attention(conn)

    @app.get("/api/ignored", response_model=list[AttentionItem])
    def get_ignored(conn=Depends(get_db)):
        return list_ignored(conn)

    @app.get("/api/last-refresh", response_model=LastRefresh)
    def get_last_refresh(conn=Depends(get_db)):
        return {"finished_at": last_refresh(conn)}

    @app.post("/api/ingest", response_model=IngestResult,
              responses={409: {"description": "A refresh is already running"}})
    def post_ingest(conn=Depends(get_db)):
        """Import new invoice PDFs (what `code/import_pdfs.py` does)."""
        if not ingest_lock.acquire(blocking=False):
            raise HTTPException(409, "A refresh is already running")
        try:
            result = ingest(conn, str(pdf_dir))
            record_refresh(conn, current_time())
            return result
        finally:
            ingest_lock.release()

    return app


def build_app():
    """The uvicorn entry point (`--factory`), so nothing runs on import.

    The LDAP login gate is on unless AUTH_DISABLED=true (local dev); see
    `auth.settings_from_env` for the settings it needs.
    """
    import os

    from auth import settings_from_env

    return create_app(auth=settings_from_env(os.environ))
