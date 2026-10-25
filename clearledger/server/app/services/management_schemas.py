"""Публичный контракт V1 и минимальная проекция, отдаваемая источником."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.management_config import Kind


class ManagementRecord(BaseModel):
    # Extra поля источника (href/source/...) не переходят в публичный ответ.
    source_id: UUID
    kind: Kind
    title: str = Field(max_length=1000)
    subtitle: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=100)
    updated_at: datetime | None = None
    author_name: str | None = Field(default=None, max_length=255)
    assignee_name: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    unread_count: int | None = Field(default=None, ge=0)
    project_name: str | None = Field(default=None, max_length=255)


class SourceIdentity(BaseModel):
    code: str
    name: str
    company_id: str
    company_name: str


class ManagementItem(ManagementRecord):
    id: str
    source_id: str
    source: SourceIdentity
    href: str


class ManagementSource(BaseModel):
    code: str
    name: str
    state: Literal["ok", "error", "forbidden", "not_configured"]
    fetched_at: datetime | None = None
    error: str | None = None
    truncated: bool = False


class SourceOverview(BaseModel):
    fetched_at: datetime
    items: list[ManagementRecord] = Field(max_length=200)
    truncated: bool


class ManagementOverview(BaseModel):
    enabled: bool
    fetched_at: datetime
    items: list[ManagementItem]
    sources: list[ManagementSource]
    truncated: bool
