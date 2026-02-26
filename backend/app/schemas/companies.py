"""Pydantic-схемы компаний."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CompanyCreate(BaseModel):
    id: str
    name: str
    short_name: str
    inn: str | None = None
    profile_id: str
    color: str = "#3b82f6"
    settings: dict[str, Any] = {}


class CompanyUpdate(BaseModel):
    name: str | None = None
    short_name: str | None = None
    inn: str | None = None
    color: str | None = None
    settings: dict[str, Any] | None = None


class CompanyOut(BaseModel):
    id: str
    name: str
    short_name: str
    inn: str | None
    profile_id: str
    color: str
    settings: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
