"""
STS API адаптер.

Тонкая обёртка над `app.services.sts_client` под унифицированный
контракт `SourceAdapter`. Поддерживает multi-system_id (65, 15)
в одном источнике через filters['system'].
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters import (
    RawBatch,
    SetupField,
    SourceAdapter,
    SourceDocType,
    TestResult,
    register_adapter,
)
from app.services import sts_client


@register_adapter("sts")
class STSAdapter(SourceAdapter):
    """STS API — pos.autooplata.ru/tms.

    Тянет сменные отчёты и ТТН по нефтепродуктам. У ClearLedger клиент
    ГИГ имеет две тех. сети `system_id=65` и `system_id=15`. Оба
    обслуживаются одним адаптером — `system` передаётся в filters
    при fetch_delta.
    """

    label = "STS API (АЗС)"
    category = "Топливный учёт АЗС"
    description = (
        "Источник смен и ТТН по нефтепродуктам от STS-партнёра "
        "(pos.autooplata.ru/tms). Поддерживает несколько технических "
        "сетей в одном клиенте (system_id)."
    )
    icon = "Fuel"

    setup_schema = [
        SetupField(
            key="base_url",
            label="Base URL",
            field_type="url",
            default_value="https://pos.autooplata.ru/tms",
            placeholder="https://pos.autooplata.ru/tms",
            help_text="Базовый адрес STS API. По умолчанию — Автооплата.",
        ),
        SetupField(
            key="login",
            label="Логин",
            field_type="text",
            placeholder="ivanov@gig.ru",
            help_text="Логин учётной записи в STS.",
        ),
        SetupField(
            key="password",
            label="Пароль",
            field_type="password",
            secret=True,
            help_text="Пароль учётной записи. Шифруется в БД Fernet.",
        ),
        SetupField(
            key="default_system_ids",
            label="ID сетей по умолчанию",
            field_type="tags",
            default_value="65,15",
            help_text=(
                "Список технических идентификаторов сетей через запятую. "
                "Канал может уточнить в фильтрах при запуске."
            ),
        ),
    ]

    available_doc_types = [
        SourceDocType(
            id="shift_report",
            name="Сменные отчёты",
            description=(
                "Сменный отчёт со всеми разрезами: продажи, резервуары, "
                "ТРК, оплаты, остатки."
            ),
            category="fuel",
        ),
        SourceDocType(
            id="receipt",
            name="Поступления (ТТН)",
            description=(
                "Товарно-транспортные накладные на приём нефтепродуктов "
                "по конкретной смене (плотность, масса, объём)."
            ),
            category="fuel",
        ),
    ]

    # ----- Реализация контракта -----

    async def test_connection(
        self, connection: dict[str, Any]
    ) -> TestResult:
        """Тест: login + список смен по первой указанной сети."""
        base_url = connection.get("base_url") or "https://pos.autooplata.ru/tms"
        login = connection.get("login") or ""
        password = connection.get("password") or ""
        system_ids = _parse_system_ids(connection.get("default_system_ids"))

        if not login or not password:
            return TestResult(
                ok=False,
                message="Не задан логин или пароль",
            )
        if not system_ids:
            return TestResult(
                ok=False,
                message="Не указан ни один system_id",
            )

        # Проверяем по каждой указанной сети
        results: dict[int, dict] = {}
        any_ok = False
        for sid in system_ids:
            try:
                check = await sts_client.sts_test_connection(
                    base_url, login, password, sid
                )
                results[sid] = check
                if check.get("ok"):
                    any_ok = True
            except Exception as e:  # noqa: BLE001
                results[sid] = {"ok": False, "error": str(e)}

        return TestResult(
            ok=any_ok,
            message=(
                "Все указанные сети доступны"
                if all(r.get("ok") for r in results.values())
                else "Часть сетей недоступна — см. details"
            ),
            details={"by_system": results},
        )

    async def fetch_delta(
        self,
        connection: dict[str, Any],
        doc_type: str,
        since: datetime | None = None,
        until: datetime | None = None,
        filters: dict[str, Any] | None = None,
    ) -> RawBatch:
        """Забрать смены или ТТН.

        Дельты STS по дате не поддерживает напрямую — поэтому забираем
        список смен и фильтруем по closed/opened на стороне нормализации.
        Если в filters указана конкретная смена (`station`, `shift`) —
        забираем её детально.
        """
        filters = filters or {}
        base_url = connection.get("base_url") or "https://pos.autooplata.ru/tms"
        login = connection.get("login") or ""
        password = connection.get("password") or ""

        # Системы (одна или несколько)
        system_ids = filters.get("system_ids")
        if not system_ids:
            system_ids = _parse_system_ids(
                connection.get("default_system_ids")
            )

        station = filters.get("station")  # опциональный фильтр
        shift = filters.get("shift")  # опциональный — для детали

        items: list[dict[str, Any]] = []
        meta: dict[str, Any] = {"system_ids": system_ids, "doc_type": doc_type}

        for sid in system_ids:
            if doc_type == "shift_report":
                if station and shift:
                    # Детальный сменный отчёт
                    item = await sts_client.sts_get_shift_report(
                        base_url, login, password, sid, station, shift
                    )
                    items.append({"system": sid, "station": station,
                                  "shift": shift, "report": item})
                else:
                    # Список всех смен (потом батчевая выборка деталей)
                    shifts = await sts_client.sts_get_shifts(
                        base_url, login, password, sid, station
                    )
                    items.extend(
                        {"system": sid, "shift_meta": s} for s in shifts
                    )

            elif doc_type == "receipt":
                if not (station and shift):
                    raise ValueError(
                        "Для doc_type='receipt' нужны фильтры station и shift"
                    )
                receipts = await sts_client.sts_get_receipts(
                    base_url, login, password, sid, station, shift
                )
                items.extend(
                    {"system": sid, "station": station, "shift": shift,
                     "receipt": r}
                    for r in receipts
                )

            else:
                raise ValueError(
                    f"Неизвестный doc_type='{doc_type}' для STS-адаптера. "
                    f"Поддерживаются: shift_report, receipt"
                )

        return RawBatch(
            source_id=connection.get("_source_id", ""),
            doc_type=doc_type,
            fetched_at=datetime.now(timezone.utc),
            since=since,
            until=until,
            items=items,
            meta=meta,
        )

    # parse() не реализуем — для STS нормализация уже есть
    # в существующем коде (services/fuel/shiftNormalizer на фронте + бэк
    # logic в fuel_router.py). Адаптер пока отвечает только за «достать
    # сырое», нормализация подключится в Шаге 3 (отдельным сервисом
    # mapping/sts_to_fuel.py).


def _parse_system_ids(value: Any) -> list[int]:
    """Развернуть строку '65,15' или список → list[int]."""
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for v in value:
            try:
                result.append(int(v))
            except (TypeError, ValueError):
                pass
        return result
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, str):
        result = []
        for part in value.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                pass
        return result
    return []
