"""Pydantic-схемы записей и источников."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- Source ----------

class SourceOut(BaseModel):
    id: UUID
    company_id: str
    file_name: str
    mime_type: str
    file_size: int
    file_path: str
    fingerprint: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Entry ----------

class EntryCreate(BaseModel):
    company_id: str
    title: str
    category_id: str
    subcategory_id: str
    doc_type_id: str | None = None
    source_type: str
    source_label: str = ""
    metadata: dict[str, Any] = {}
    doc_purpose: str = "accounting"
    sync_status: str = "not_applicable"


class EntryUpdate(BaseModel):
    title: str | None = None
    category_id: str | None = None
    subcategory_id: str | None = None
    doc_type_id: str | None = None
    status: str | None = None
    source_label: str | None = None
    metadata: dict[str, Any] | None = None
    doc_purpose: str | None = None
    sync_status: str | None = None


class EntryOut(BaseModel):
    id: UUID
    company_id: str
    source_id: UUID | None
    title: str
    category_id: str
    subcategory_id: str
    doc_type_id: str | None
    status: str
    doc_purpose: str
    sync_status: str
    source_type: str
    source_label: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    verified_at: datetime | None
    verified_by: UUID | None
    transferred_at: datetime | None

    model_config = {"from_attributes": True, "populate_by_name": True}


class EntryList(BaseModel):
    items: list[EntryOut]
    total: int
