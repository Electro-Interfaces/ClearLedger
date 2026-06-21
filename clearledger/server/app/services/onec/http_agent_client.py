"""
HTTP-клиент для TradeLedger COM-Agent.

Тот же публичный интерфейс что и OneCComClient, но вместо subprocess через
stdin/stdout ходит к удалённому FastAPI-агенту по HTTPS.

Используется когда backend TradeLedger развёрнут на Linux (Miran), а сам
COM-агент крутится на Windows-машине рядом с 1С (1c-dev-01).

Сигнатуры методов 1:1 с OneCComClient — sync_service подменяется через factory.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.onec.exceptions import (
    OneCAuthError,
    OneCConnectionError,
    OneCError,
)

logger = logging.getLogger("clearledger.onec.httpagent")


class OneCHttpAgentClient:
    """Drop-in замена OneCComClient через HTTP-агента.

    Параметры берутся из ENV:
      COM_AGENT_URL    — например http://10.10.70.45:8080 (внутри Miran)
                         или https://1c-dev-01.dataworker.ru
      COM_AGENT_TOKEN  — Bearer secret для аутентификации

    Если connection_string задана — при первом вызове отправляется /connect.
    """

    def __init__(self, connection_string: str, agent_url: str | None = None, token: str | None = None) -> None:
        if not connection_string:
            raise ValueError("connection_string не может быть пустым")
        self.connection_string = connection_string
        self.agent_url = (agent_url or os.environ.get("COM_AGENT_URL", "")).rstrip("/")
        if not self.agent_url:
            raise ValueError("COM_AGENT_URL не задан (ENV или конструктор)")
        self.token = token or os.environ.get("COM_AGENT_TOKEN", "")
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
            self._client = httpx.AsyncClient(
                base_url=self.agent_url,
                headers=self._headers(),
                timeout=timeout,
                verify=False,  # внутренний trust внутри VPN; для prod через LE-cert поменять
            )
        return self._client

    async def _ensure_connected(self) -> None:
        if self._connected:
            return
        client = await self._ensure_client()
        try:
            resp = await client.post("/connect", json={"conn_string": self.connection_string})
        except httpx.HTTPError as exc:
            raise OneCConnectionError(f"Agent unreachable: {exc}") from exc
        if resp.status_code == 401:
            raise OneCAuthError("Agent: missing token")
        if resp.status_code == 403:
            raise OneCAuthError("Agent: invalid token")
        if resp.status_code >= 400:
            raise OneCError(f"Agent /connect failed [{resp.status_code}]: {resp.text[:300]}")
        self._connected = True

    async def _post(self, path: str, body: dict | None = None) -> Any:
        client = await self._ensure_client()
        try:
            resp = await client.post(path, json=body or {})
        except httpx.HTTPError as exc:
            raise OneCConnectionError(f"Agent {path} unreachable: {exc}") from exc
        if resp.status_code == 401:
            raise OneCAuthError(f"Agent: missing token on {path}")
        if resp.status_code == 403:
            raise OneCAuthError(f"Agent: invalid token on {path}")
        if resp.status_code >= 400:
            raise OneCError(f"Agent {path} [{resp.status_code}]: {resp.text[:300]}")
        return resp.json()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        client = await self._ensure_client()
        try:
            resp = await client.get(path, params=params or {})
        except httpx.HTTPError as exc:
            raise OneCConnectionError(f"Agent {path} unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise OneCError(f"Agent {path} [{resp.status_code}]: {resp.text[:300]}")
        return resp.json()

    # ─── lifecycle ──────────────────────────────────────────────────

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None
        self._connected = False

    async def __aenter__(self) -> OneCHttpAgentClient:
        await self._ensure_connected()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # Совместимость с OneCComClient (sync_service вызывает _ensure_started)
    async def _ensure_started(self) -> None:
        await self._ensure_connected()

    # ─── public API (совпадает с OneCComClient) ─────────────────────

    async def metadata_catalogs(self) -> list[str]:
        await self._ensure_connected()
        return list(await self._get("/metadata/catalogs") or [])

    async def metadata_registers(self, name_substring: str = "") -> list[str]:
        await self._ensure_connected()
        return list(await self._get("/metadata/registers", {"name_substring": name_substring}) or [])

    async def describe_entity(self, entity: str) -> dict[str, list[str]]:
        await self._ensure_connected()
        return dict(await self._post("/describe", {"entity": entity}) or {})

    async def fetch_entity(
        self,
        entity: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        top: int | None = None,
        skip: int | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_connected()
        body: dict[str, Any] = {"entity": entity}
        if select is not None:
            body["select"] = select
        if filter_expr is not None:
            body["filter"] = filter_expr
        if orderby is not None:
            body["orderby"] = orderby
        if top is not None:
            body["top"] = top
        if skip is not None:
            body["skip"] = skip
        return list(await self._post("/fetch_entity", body) or [])

    async def iter_entity(
        self,
        entity: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        page_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        skip = 0
        while True:
            batch = await self.fetch_entity(
                entity, select=select, filter_expr=filter_expr,
                orderby=orderby, top=page_size, skip=skip,
            )
            if not batch:
                return
            for item in batch:
                yield item
            if len(batch) < page_size:
                return
            skip += page_size

    async def count_entity(self, entity: str, *, filter_expr: str | None = None) -> int:
        await self._ensure_connected()
        body: dict[str, Any] = {"entity": entity}
        if filter_expr is not None:
            body["filter"] = filter_expr
        return int(await self._post("/count_entity", body) or 0)

    async def fetch_doc_lines(
        self,
        doc_type: str,
        doc_ref: str,
        tabular_name: str,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_connected()
        return list(await self._post("/fetch_doc_lines", {
            "doc_type": doc_type, "doc_ref": doc_ref,
            "tabular_name": tabular_name, "select": select or [],
        }) or [])

    async def fetch_postings(self, doc_type: str, doc_ref: str) -> list[dict[str, Any]]:
        await self._ensure_connected()
        return list(await self._post("/fetch_postings", {
            "doc_type": doc_type, "doc_ref": doc_ref,
        }) or [])

    async def find_docs_by_nomenclature(self, nomenclature_ref: str, limit: int = 50) -> list[dict[str, Any]]:
        await self._ensure_connected()
        return list(await self._post("/find_docs_by_nomenclature", {
            "nomenclature_ref": nomenclature_ref, "limit": limit,
        }) or [])

    async def enrich_nomenclature(self, refs: list[str]) -> dict[str, dict[str, Any]]:
        await self._ensure_connected()
        return dict(await self._post("/enrich_nomenclature", {"refs": refs}) or {})
