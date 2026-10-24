"""Изолированная конфигурация обзора: никаких неявных SSO/email grants."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["chats", "tasks", "calendar"]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutboundGrant(StrictModel):
    id: Code
    local_user_id: UUID
    local_company_id: UUID
    remote_user_id: UUID
    kinds: list[Kind] = Field(min_length=1)


class RemoteSource(StrictModel):
    code: Code
    name: str = Field(min_length=1, max_length=200)
    base_url: str
    company_id: UUID
    company_name: str = Field(min_length=1, max_length=200)
    grants: list[OutboundGrant] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def reserved_code(cls, value: str) -> str:
        if value == "all":
            raise ValueError("reserved source code")
        return value

    @field_validator("base_url")
    @classmethod
    def safe_base(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path not in ("", "/")
                or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            raise ValueError("source base must be an HTTPS origin")
        # Force port validation too.
        _ = parts.port
        return value.rstrip("/")

    @model_validator(mode="after")
    def unique_actors(self):
        keys = [(g.local_user_id, g.local_company_id, k) for g in self.grants for k in g.kinds]
        if len(keys) != len(set(keys)) or len({g.id for g in self.grants}) != len(self.grants):
            raise ValueError("ambiguous source grants")
        return self


class InboundGrant(StrictModel):
    id: Code
    actor_user_id: UUID
    actor_company_id: UUID
    user_id: UUID
    company_id: UUID
    kinds: list[Kind] = Field(min_length=1)


class TrustedIssuer(StrictModel):
    issuer: Code
    public_key_b64: str = Field(repr=False)
    grants: list[InboundGrant] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({g.id for g in self.grants}) != len(self.grants):
            raise ValueError("duplicate inbound grant")
        return self


class ManagementConfig(StrictModel):
    enabled: bool = False
    hub_enabled: bool = False
    code: Code = "local"
    name: str = Field(default="Текущее пространство", min_length=1, max_length=200)
    signing_private_key_b64: str = Field(default="", repr=False)
    sources: list[RemoteSource] = Field(default_factory=list, max_length=20)
    trusted_issuers: list[TrustedIssuer] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_sources(self):
        codes = [self.code, *(s.code for s in self.sources)]
        issuers = [i.issuer for i in self.trusted_issuers]
        if "all" in codes or len(codes) != len(set(codes)) or len(issuers) != len(set(issuers)):
            raise ValueError("duplicate management identity")
        return self


class ManagementConfigError(Exception):
    pass


def load_config() -> ManagementConfig:
    """Читается заново: удаление grant немедленно закрывает последующие запросы."""
    path = os.environ.get("MANAGEMENT_CONFIG_PATH", "")
    if not path:
        return ManagementConfig()
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(262145)
        if len(raw) > 262144:
            raise ValueError("config too large")
        return ManagementConfig.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise ManagementConfigError("Конфигурация обзора недоступна") from exc
