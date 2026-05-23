from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from app.services.onec.exceptions import (
    OneCAuthError,
    OneCConnectionError,
    OneCError,
    OneCNotFoundError,
    OneCTimeoutError,
)

logger = logging.getLogger("clearledger.onec.odata")


# OData-сущности БП 3.0 с кириллическими именами метаданных.
# Подмножество, необходимое ClearLedger для pull НСИ и документов.
# Префиксы — стандарт OData 1С: Catalog_/Document_/InformationRegister_/
# AccumulationRegister_/AccountingRegister_/Constant_.
ENTITY_COUNTERPARTIES = "Catalog_Контрагенты"
ENTITY_NOMENCLATURE = "Catalog_Номенклатура"
ENTITY_CONTRACTS = "Catalog_ДоговорыКонтрагентов"
ENTITY_WAREHOUSES = "Catalog_Склады"
ENTITY_ORGANIZATIONS = "Catalog_Организации"
ENTITY_DOC_PTU = "Document_ПоступлениеТоваровУслуг"
ENTITY_DOC_ORP = "Document_ОтчетОРозничныхПродажах"
ENTITY_DOC_OPZS = "Document_ОтчетПроизводстваЗаСмену"
ENTITY_DOC_WRITEOFF = "Document_СписаниеТоваров"
ENTITY_DOC_PKO = "Document_ПриходныйКассовыйОрдер"
ENTITY_DOC_TRANSFER = "Document_ПеремещениеТоваров"
ENTITY_DOC_CORRECTION = "Document_КорректировкаПоступления"
ENTITY_ACC_REGISTER = "AccountingRegister_Хозрасчетный"

# Регистры расширения TradeLedger.cfe — публикуются только при включённой
# опции `<extensionRefs>` в default.vrd. Если расширение не опубликовано,
# OData отдаст 404 на эти URL — это нормально и обрабатывается как
# отсутствие данных, а не как ошибка подключения.
ENTITY_TL_SOOTVET = "InformationRegister_TL_СоответствиеИсточников"
ENTITY_TL_SVERKA = "InformationRegister_TL_СверкаПакета"
ENTITY_TL_ERRORS = "InformationRegister_TL_ОшибкиЗагрузки"
ENTITY_TL_STATUS = "InformationRegister_TL_СтатусыЗагрузки"
ENTITY_TL_PAYMAP = "InformationRegister_TL_МаппингОплат"


def encode_entity(entity: str) -> str:
    """URL-encode имени сущности с кириллицей.

    OData 1С требует %-кодирования кириллических имён метаданных в пути
    запроса. Английские псевдонимы не работают — только as-is с encode.
    """
    return quote(entity, safe="")


def encode_filter(expr: str) -> str:
    """URL-encode значения параметра $filter с одинарными кавычками."""
    return quote(expr, safe="=' /()$@,.-")


class OneCODataClient:
    """Асинхронный pull-клиент OData 1С:БП 3.0.

    Идеология ClearLedger: только чтение из БП. Все мутации БП происходят
    через её собственное расширение, которое тянет данные из ClearLedger
    HTTP API. Этот клиент НЕ имеет методов post/patch/delete по дизайну.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if not base_url:
            raise ValueError("base_url не может быть пустым")
        if not username:
            raise ValueError("username не может быть пустым")

        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OneCODataClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ─── низкоуровневые операции ────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        params_effective = {"$format": "json", **(params or {})}

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.max_retries:
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params_effective,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("OData timeout %s %s (attempt %d)", method, path, attempt + 1)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("OData HTTP error %s %s (attempt %d): %s", method, path, attempt + 1, exc)
            else:
                self._raise_for_status(response)
                return response
            attempt += 1

        if isinstance(last_exc, httpx.TimeoutException):
            raise OneCTimeoutError(f"OData timeout {self.timeout}s: {method} {path}") from last_exc
        raise OneCConnectionError(f"OData connection failed: {method} {path}: {last_exc}") from last_exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        status = response.status_code
        body_preview = response.text[:500] if response.text else "<empty>"
        if status in (401, 403):
            raise OneCAuthError(f"HTTP {status}: {body_preview}")
        if status == 404:
            raise OneCNotFoundError(f"HTTP 404: {body_preview}")
        raise OneCError(f"HTTP {status}: {body_preview}")

    # ─── публичные API ──────────────────────────────────────────────

    async def metadata_catalogs(self) -> list[str]:
        """Список доступных Catalog_* из $metadata. Используется тестом подключения.

        $metadata возвращает EDM-XML с полным описанием схемы. Парсим
        грубо — только список EntitySet с префиксом Catalog_.
        """
        response = await self._request("GET", "/$metadata", params={})
        text = response.text
        # Простой парсинг — ищем EntitySet Name="Catalog_..." без зависимости от XML-библиотеки.
        # Этого хватает для проверки доступности; полный разбор не нужен.
        import re

        catalogs: list[str] = []
        for match in re.finditer(r'EntitySet\s+Name="(Catalog_[^"]+)"', text):
            catalogs.append(match.group(1))
        return catalogs

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
        """Прочитать страницу записей сущности.

        Поля select передаются как имена 1С (с кириллицей). Filter — как
        полное OData-выражение `ИНН eq '7839440090'`. Top/skip — для пагинации.
        """
        params: dict[str, Any] = {}
        if select:
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if orderby:
            params["$orderby"] = orderby
        if top is not None:
            params["$top"] = top
        if skip is not None:
            params["$skip"] = skip

        path = f"/{encode_entity(entity)}"
        response = await self._request("GET", path, params=params)
        data = response.json()
        if isinstance(data, dict) and "value" in data:
            return list(data["value"])
        # OData может вернуть {"d": {"results": [...]}} для legacy-режима.
        if isinstance(data, dict) and "d" in data and isinstance(data["d"], dict):
            return list(data["d"].get("results", []))
        raise OneCError(f"Неожиданный формат ответа OData: {type(data).__name__}")

    async def iter_entity(
        self,
        entity: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        page_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Итератор по всем записям сущности с автоматической пагинацией.

        Используется для синхронизации справочников, где могут быть
        десятки тысяч записей (Номенклатура 7000+, Контрагенты — сотни).
        """
        skip = 0
        while True:
            batch = await self.fetch_entity(
                entity,
                select=select,
                filter_expr=filter_expr,
                orderby=orderby,
                top=page_size,
                skip=skip,
            )
            if not batch:
                return
            for item in batch:
                yield item
            if len(batch) < page_size:
                return
            skip += page_size

    async def count_entity(
        self,
        entity: str,
        *,
        filter_expr: str | None = None,
    ) -> int:
        """Количество записей. OData 1С поддерживает суффикс /$count."""
        params: dict[str, Any] = {}
        if filter_expr:
            params["$filter"] = filter_expr
        # /$count возвращает plain integer, не JSON.
        path = f"/{encode_entity(entity)}/$count"
        response = await self._client.get(path, params=params)
        self._raise_for_status(response)
        return int(response.text.strip())

    # ─── удобные обёртки ────────────────────────────────────────────

    async def get_counterparty_by_inn(self, inn: str) -> dict[str, Any] | None:
        """Найти контрагента по ИНН. Возвращает первую запись или None."""
        items = await self.fetch_entity(
            ENTITY_COUNTERPARTIES,
            filter_expr=f"ИНН eq '{inn}'",
            top=1,
        )
        return items[0] if items else None
