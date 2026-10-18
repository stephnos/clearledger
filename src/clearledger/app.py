import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from clearledger.ledger import MAX_AMOUNT, Ledger, LedgerError


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    currency: Literal["GBP", "USD", "EUR"] = "GBP"


class TransferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_account_id: str = Field(min_length=1, max_length=64)
    destination_account_id: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(strict=True, gt=0, le=MAX_AMOUNT)
    reference: str = Field(min_length=1, max_length=120)


def create_app(db_path: str | Path | None = None, *, demo: bool | None = None) -> FastAPI:
    ledger = Ledger(db_path or os.getenv("CLEARLEDGER_DB", "data/ledger.sqlite3"))
    seed = demo if demo is not None else os.getenv("CLEARLEDGER_DEMO", "1") == "1"

    @asynccontextmanager
    async def lifespan(app):
        ledger.initialize()
        if seed:
            ledger.seed_demo()
        yield

    app = FastAPI(
        title="ClearLedger API",
        version="1.0.0",
        lifespan=lifespan,
        description="Local educational ledger. No real money or authentication.",
    )
    app.state.ledger = ledger

    @app.exception_handler(LedgerError)
    async def ledger_error(request: Request, exc: LedgerError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(request: Request, exc: sqlite3.OperationalError):
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "1"},
                content={
                    "error": {
                        "code": "ledger_busy",
                        "message": "Ledger busy. Retry with the same key.",
                    }
                },
            )
        raise exc

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # The browser dashboard is same-origin. No wildcard CORS is enabled.
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        with ledger.connection() as db:
            db.execute("SELECT 1 FROM accounts LIMIT 1")
        return {"status": "ok"}

    @app.get("/api/accounts")
    def accounts():
        return {"items": ledger.accounts()}

    @app.post("/api/accounts", status_code=201)
    def create_account(body: AccountInput):
        return ledger.create_account(body.name, body.currency)

    @app.get("/api/summary")
    def summary():
        return ledger.summary()

    @app.get("/api/transfers")
    def transfers(
        limit: Annotated[int, Query(ge=1, le=100)] = 25, offset: Annotated[int, Query(ge=0)] = 0
    ):
        return ledger.transfers(limit, offset)

    @app.get("/api/accounts/{account_id}/entries")
    def entries(
        account_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return ledger.entries(account_id, limit, offset)

    @app.post("/api/transfers", status_code=201)
    def transfer(
        body: TransferInput,
        response: Response,
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
        ],
    ):
        result, replayed = ledger.transfer(
            body.source_account_id,
            body.destination_account_id,
            body.amount_minor,
            body.reference,
            idempotency_key,
        )
        response.status_code = 200 if replayed else 201
        response.headers["Idempotent-Replayed"] = str(replayed).lower()
        return result

    static = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    return app
