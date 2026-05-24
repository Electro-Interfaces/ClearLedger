"""
ClearLedger COM-Agent — FastAPI обёртка над V83.COMConnector.

Запускается на Windows-машине (1c-dev-01) рядом с 1С. Принимает HTTP-запросы
от backend ClearLedger (Linux в Miran) и проксирует их в COM-вызовы 1С.

Endpoints совпадают 1:1 с операциями `com_worker.py` — HTTP-обёртка тех же ops.

Аутентификация: Bearer token из ENV `COM_AGENT_TOKEN` (или из .env).
Без токена 401. Без правильного токена 403.

Запуск:
  uvicorn app.main:app --host 0.0.0.0 --port 8080

Windows Service:
  nssm install ClearLedgerCOMAgent "C:\Python313\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 8080"
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from app import runtime

load_dotenv()

TOKEN = os.environ.get("COM_AGENT_TOKEN", "").strip()
AUTO_CONN_STRING = os.environ.get("COM_AGENT_AUTO_CONNECT", "").strip()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if not TOKEN:
        print("[WARN] COM_AGENT_TOKEN не задан — агент будет принимать запросы БЕЗ аутентификации")
    if AUTO_CONN_STRING:
        try:
            info = runtime.op_connect(AUTO_CONN_STRING)
            print(f"[OK] Auto-connect to 1C: {info}")
        except Exception as exc:
            print(f"[ERR] Auto-connect failed: {exc}")
    yield
    try:
        runtime.op_disconnect()
    except Exception:
        pass


app = FastAPI(
    title="ClearLedger COM-Agent",
    version="1.0.0",
    description="HTTP-обёртка над 1С V83.COMConnector. Деплоится рядом с 1С на Windows.",
    lifespan=lifespan,
)


def auth(authorization: str | None = Header(None)) -> None:
    if not TOKEN:
        return  # auth выключена (dev)
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Expected 'Bearer <token>'")
    if parts[1].strip() != TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


# ─── Health ──────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    info = runtime.op_ping()
    return {"status": "ok", "service": "clearledger-com-agent", "version": "1.0.0", **info}


# ─── Connect/Disconnect ──────────────────────────────────────────────


class ConnectBody(BaseModel):
    conn_string: str


@app.post("/connect", dependencies=[Depends(auth)])
async def connect(body: ConnectBody) -> dict:
    try:
        return runtime.op_connect(body.conn_string)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


@app.post("/disconnect", dependencies=[Depends(auth)])
async def disconnect() -> dict:
    return runtime.op_disconnect()


# ─── Metadata ─────────────────────────────────────────────────────────


@app.get("/metadata/catalogs", dependencies=[Depends(auth)])
async def metadata_catalogs() -> list[str]:
    try:
        return runtime.op_metadata_catalogs()
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


@app.get("/metadata/registers", dependencies=[Depends(auth)])
async def metadata_registers(name_substring: str = "") -> list[str]:
    try:
        return runtime.op_metadata_registers(name_substring)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class DescribeBody(BaseModel):
    entity: str


@app.post("/describe", dependencies=[Depends(auth)])
async def describe(body: DescribeBody) -> dict:
    try:
        return runtime.op_describe_entity(body.entity)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


# ─── Fetch ────────────────────────────────────────────────────────────


class FetchEntityBody(BaseModel):
    entity: str
    select: list[str] | None = None
    filter: str | None = None
    orderby: str | None = None
    top: int | None = None
    skip: int | None = None


@app.post("/fetch_entity", dependencies=[Depends(auth)])
async def fetch_entity(body: FetchEntityBody) -> list[dict]:
    try:
        return runtime.op_fetch_entity(
            entity=body.entity,
            select=body.select,
            filter=body.filter,
            orderby=body.orderby,
            top=body.top,
            skip=body.skip,
        )
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class CountEntityBody(BaseModel):
    entity: str
    filter: str | None = None


@app.post("/count_entity", dependencies=[Depends(auth)])
async def count_entity(body: CountEntityBody) -> int:
    try:
        return runtime.op_count_entity(entity=body.entity, filter=body.filter)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class FetchDocLinesBody(BaseModel):
    doc_type: str
    doc_ref: str
    tabular_name: str
    select: list[str] | None = None


@app.post("/fetch_doc_lines", dependencies=[Depends(auth)])
async def fetch_doc_lines(body: FetchDocLinesBody) -> list[dict]:
    try:
        return runtime.op_fetch_doc_lines(
            doc_type=body.doc_type,
            doc_ref=body.doc_ref,
            tabular_name=body.tabular_name,
            select=body.select,
        )
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class FetchPostingsBody(BaseModel):
    doc_type: str
    doc_ref: str


@app.post("/fetch_postings", dependencies=[Depends(auth)])
async def fetch_postings(body: FetchPostingsBody) -> list[dict]:
    try:
        return runtime.op_fetch_postings(body.doc_type, body.doc_ref)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class FindDocsBody(BaseModel):
    nomenclature_ref: str
    limit: int = 50


@app.post("/find_docs_by_nomenclature", dependencies=[Depends(auth)])
async def find_docs_by_nomenclature(body: FindDocsBody) -> list[dict]:
    try:
        return runtime.op_find_docs_by_nomenclature(body.nomenclature_ref, body.limit)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


class EnrichNomBody(BaseModel):
    refs: list[str]


@app.post("/enrich_nomenclature", dependencies=[Depends(auth)])
async def enrich_nomenclature(body: EnrichNomBody) -> dict:
    try:
        return runtime.op_enrich_nomenclature(body.refs)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
