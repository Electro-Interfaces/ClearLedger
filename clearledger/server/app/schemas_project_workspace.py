"""Общие runtime DTO трёх команд рабочего пространства проекта."""
from datetime import date
from typing import Literal
import uuid

from pydantic import BaseModel, Field


class LinkBody(BaseModel):
    kind: Literal["doc", "task", "message"]
    id: uuid.UUID


class DecisionBody(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    source_message_id: uuid.UUID | None = None
    work: LinkBody | None = None
    deadline: date | None = None
    budget: float | None = Field(None, ge=0, allow_inf_nan=False)


class FileBody(BaseModel):
    message_id: uuid.UUID
    kind: str = Field("other", max_length=24)
