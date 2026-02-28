"""Pydantic-схемы для интеграции 1С."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── Подключения ───────────────────────────────────────────

class OneCConnectionCreate(BaseModel):
    company_id: str
    name: str = "1С:Бухгалтерия"
    odata_url: str = Field(..., description="URL OData-интерфейса 1С")
    username: str
    password: str = Field(..., description="Пароль (будет зашифрован)")
    exchange_path: str | None = None
    sync_interval_sec: int = 300


class OneCConnectionUpdate(BaseModel):
    name: str | None = None
    odata_url: str | None = None
    username: str | None = None
    password: str | None = None
    exchange_path: str | None = None
    sync_interval_sec: int | None = None
    status: str | None = None


class OneCConnectionOut(BaseModel):
    id: UUID
    company_id: str
    name: str
    odata_url: str
    username: str
    exchange_path: str | None
    status: str
    last_sync_at: datetime | None
    sync_interval_sec: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Тест подключения ─────────────────────────────────────

class OneCTestResult(BaseModel):
    available: bool
    catalogs: list[str] = []
    error: str | None = None


# ── Лог синхронизации ─────────────────────────────────────

class OneCSyncLogOut(BaseModel):
    id: UUID
    connection_id: UUID
    direction: str
    sync_type: str
    status: str
    items_processed: int
    items_created: int
    items_updated: int
    items_errors: int
    details: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ── Результат синхронизации ───────────────────────────────

class SyncResult(BaseModel):
    status: str
    stats: dict[str, int]
    details: dict[str, Any]
    log_id: str


# ── Экспорт ───────────────────────────────────────────────

class ExportResult(BaseModel):
    status: str
    file_path: str | None = None
    entries_count: int = 0
    error: str | None = None


class ExportFeedback(BaseModel):
    status: str
    files: list[dict[str, Any]] = []
    error: str | None = None
