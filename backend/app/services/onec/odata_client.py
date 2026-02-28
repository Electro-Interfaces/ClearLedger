"""OData-клиент для 1С:Бухгалтерия 3.0.

Burst-sync: быстро подключиться → забрать дельту → отключиться.
Файловая база 1С допускает одно OData-соединение.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("onec.odata")

PAGE_SIZE = 500
REQUEST_DELAY = 0.2  # пауза между запросами (сек)
SESSION_TIMEOUT = 300  # максимальная длительность сессии (5 мин)
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 30
RETRY_DELAYS = [2, 5, 15]  # backoff


class ODataConnectionError(Exception):
    """1С недоступна или база заблокирована."""


class ODataClient:
    """Async-клиент для OData-интерфейса 1С."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self._client: httpx.AsyncClient | None = None
        self._session_start: datetime | None = None

    async def __aenter__(self) -> "ODataClient":
        self._client = httpx.AsyncClient(
            auth=self.auth,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT),
            headers={"Accept": "application/json"},
        )
        self._session_start = datetime.utcnow()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._session_start = None

    def _check_session_limit(self) -> None:
        """Прерываем если сессия длится дольше SESSION_TIMEOUT."""
        if self._session_start:
            elapsed = (datetime.utcnow() - self._session_start).total_seconds()
            if elapsed > SESSION_TIMEOUT:
                raise ODataConnectionError(
                    f"Превышен лимит сессии ({SESSION_TIMEOUT}с). "
                    "Отключаемся, чтобы не блокировать файловую базу 1С."
                )

    async def check_availability(self) -> dict[str, Any]:
        """GET $metadata — проверка доступности 1С.

        Returns:
            dict с ключами: available (bool), catalogs (list[str]), error (str | None)
        """
        url = f"{self.base_url}/$metadata"
        assert self._client is not None
        try:
            resp = await self._client.get(url, timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=10, write=10, pool=10))
            if resp.status_code in (503, 423):
                return {"available": False, "catalogs": [], "error": "База 1С занята другим сеансом"}
            resp.raise_for_status()
            # Извлекаем имена EntitySet из $metadata XML
            catalogs = self._parse_entity_sets(resp.text)
            return {"available": True, "catalogs": catalogs, "error": None}
        except httpx.TimeoutException:
            return {"available": False, "catalogs": [], "error": "Таймаут подключения к 1С"}
        except httpx.ConnectError:
            return {"available": False, "catalogs": [], "error": "Не удалось подключиться к 1С"}
        except Exception as e:
            return {"available": False, "catalogs": [], "error": str(e)}

    @staticmethod
    def _parse_entity_sets(metadata_xml: str) -> list[str]:
        """Извлекает имена EntitySet из $metadata."""
        import re
        return re.findall(r'EntitySet\s+Name="([^"]+)"', metadata_xml)

    async def get_catalog(
        self,
        entity_name: str,
        *,
        select: str | None = None,
        expand: str | None = None,
        since: datetime | None = None,
        extra_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Получает все записи каталога/документа с пагинацией.

        Args:
            entity_name: имя OData-сущности (Catalog_Контрагенты, Document_ПоступлениеТоваровУслуг)
            select: $select
            expand: $expand (для табличных частей)
            since: дата для delta-sync ($filter по Date_LastUpdate)
            extra_filter: дополнительный $filter
        """
        assert self._client is not None
        all_items: list[dict[str, Any]] = []
        skip = 0

        while True:
            self._check_session_limit()

            params: dict[str, str] = {
                "$format": "json",
                "$top": str(PAGE_SIZE),
                "$skip": str(skip),
            }
            if select:
                params["$select"] = select
            if expand:
                params["$expand"] = expand

            # Фильтры
            filters: list[str] = []
            if since:
                iso = since.strftime("%Y-%m-%dT%H:%M:%S")
                filters.append(f"Date_LastUpdate gt datetime'{iso}'")
            if extra_filter:
                filters.append(extra_filter)
            if filters:
                params["$filter"] = " and ".join(filters)

            url = f"{self.base_url}/{entity_name}"
            data = await self._request_with_retry(url, params)

            items = data.get("value", [])
            all_items.extend(items)

            if len(items) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

            await asyncio.sleep(REQUEST_DELAY)

        logger.info("OData %s: загружено %d записей", entity_name, len(all_items))
        return all_items

    async def _request_with_retry(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        """GET-запрос с retry и backoff."""
        assert self._client is not None
        last_error: Exception | None = None

        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code in (503, 423):
                    raise ODataConnectionError("База 1С занята другим сеансом")
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning("OData retry %d/%d: %s", attempt + 1, len(RETRY_DELAYS), e)
                await asyncio.sleep(delay)
            except ODataConnectionError:
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise ODataConnectionError("Неверные учётные данные 1С")
                raise

        raise ODataConnectionError(f"1С недоступна после {len(RETRY_DELAYS)} попыток: {last_error}")
