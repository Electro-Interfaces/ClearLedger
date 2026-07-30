"""Справочники измерений и метрик сводных - единственное место, откуда берётся SQL.

Правило безопасности: в запрос подставляется **только** выражение из этих карт.
Ничего пришедшего от клиента в SQL не попадает: клиент передаёт ключи (`station`,
`fuel`), а не колонки. Неизвестный ключ, дубль и превышение лимита уровней это 400,
а не «молча пропустим».

Второе назначение - общий словарь для источников. Их уже два (реализации и
поступления топлива), и у каждого свои измерения с метриками: у продаж литры с
выручкой, у приёмки массы по документу и факту с отклонением. Складывать их в одну
сводную нельзя (итоги разойдутся с KPI), поэтому источники разведены явно.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import cast, func
from sqlalchemy.types import String

from app.models import FuelReceipt as R
from app.models import FuelTransaction as T

MAX_DIMS = 5

# ─── Источник «реализации» (пооперационные транзакции) ───────────────────────
_TX_DIMS: dict[str, dict[str, Any]] = {
    "station": {"label": "АЗС", "expr": T.station_code},
    "fuel": {"label": "Вид топлива", "expr": T.fuel_name},
    "payment": {"label": "Способ оплаты", "expr": func.coalesce(T.payment_method, T.pay_type_name)},
    "pay_type": {"label": "Вид оплаты (как в источнике)", "expr": T.pay_type_name},
    "status": {"label": "Статус", "expr": T.status},
    "shift": {"label": "Смена", "expr": T.shift_number},
    "pos": {"label": "Касса (POS)", "expr": T.pos},
    "nozzle": {"label": "Пистолет", "expr": T.nozzle},
    "tank": {"label": "Резервуар", "expr": T.tank},
    "card": {"label": "Карта", "expr": T.card},
    "day": {"label": "День", "expr": func.to_char(T.dt, "YYYY-MM-DD")},
    "month": {"label": "Месяц", "expr": func.to_char(T.dt, "YYYY-MM")},
    "weekday": {"label": "День недели", "expr": func.to_char(T.dt, "ID")},
    "hour": {"label": "Час", "expr": func.to_char(T.dt, "HH24")},
}

_TX_METRICS: dict[str, dict[str, Any]] = {
    "ops": {"label": "Операций", "expr": func.count(), "digits": 0},
    "liters": {"label": "Литры", "expr": func.coalesce(func.sum(T.liters), 0), "digits": 3},
    "amount": {"label": "Выручка, ₽", "expr": func.coalesce(func.sum(T.amount), 0), "digits": 2},
}

# ─── Источник «поступления» (приёмка ТТН) ────────────────────────────────────
# Здесь метрики другие и это принципиально: приёмку сверяют по МАССЕ, а не по литрам
# (объём зависит от температуры). Отклонение факта от документа - главный ответ
# экрана, поэтому оно считается суммой, а не выводится из средних.
_RC_DIMS: dict[str, dict[str, Any]] = {
    "supplier": {"label": "Поставщик", "expr": func.coalesce(R.supplier, "")},
    "fuel": {"label": "Вид топлива", "expr": R.fuel_name},
    "station": {"label": "АЗС", "expr": R.station_id},
    "tank": {"label": "Резервуар", "expr": R.tank},
    "shift": {"label": "Смена", "expr": R.shift_number},
    "ttn": {"label": "Номер ТТН", "expr": R.ttn},
    "day": {"label": "День", "expr": func.to_char(R.received_at, "YYYY-MM-DD")},
    "month": {"label": "Месяц", "expr": func.to_char(R.received_at, "YYYY-MM")},
}

_RC_METRICS: dict[str, dict[str, Any]] = {
    "docs": {"label": "Документов", "expr": func.count(), "digits": 0},
    "doc_mass": {"label": "Масса по ТТН, кг", "expr": func.coalesce(func.sum(R.doc_mass_kg), 0), "digits": 2},
    "fact_mass": {"label": "Масса факт, кг", "expr": func.coalesce(func.sum(R.fact_mass_kg), 0), "digits": 2},
    "diff_mass": {"label": "Отклонение массы, кг", "expr": func.coalesce(func.sum(R.diff_mass), 0), "digits": 2},
    "doc_volume": {"label": "Объём по ТТН, л", "expr": func.coalesce(func.sum(R.doc_volume_liters), 0), "digits": 2},
    "fact_volume": {"label": "Объём факт, л", "expr": func.coalesce(func.sum(R.fact_volume_liters), 0), "digits": 2},
    # Сумм по ТТН в источнике нет: `doc_cost` и `fact_cost` приходят нулями на всех
    # 1445 документах (проверено на данных ГИГ). Колонка из нулей только мешает
    # читать разрез, вернём её, когда поставщик начнёт отдавать суммы.
}

SOURCES: dict[str, dict[str, Any]] = {
    "transactions": {"dims": _TX_DIMS, "metrics": _TX_METRICS, "default_metric": "amount"},
    "receipts": {"dims": _RC_DIMS, "metrics": _RC_METRICS, "default_metric": "doc_mass"},
}


def _src(source: str) -> dict[str, Any]:
    if source not in SOURCES:
        raise ValueError(f"Неизвестный источник сводной: {source}")
    return SOURCES[source]


def dims_catalog(source: str = "transactions") -> list[dict[str, str]]:
    """Справочник измерений для UI: ключ и подпись, в порядке карты."""
    return [{"key": k, "label": v["label"]} for k, v in _src(source)["dims"].items()]


def metrics_catalog(source: str = "transactions") -> list[dict[str, Any]]:
    """Метрики источника: что можно показать и по чему сортировать."""
    return [{"key": k, "label": v["label"], "digits": v["digits"]}
            for k, v in _src(source)["metrics"].items()]


def parse_dims(raw: str | None, source: str = "transactions") -> list[str]:
    """CSV ключей → проверенный список. Мусор, дубли и перебор уровней это ошибка.

    Возвращает ключи, а не SQL: подстановкой занимается `dim_expr`, и только он.
    """
    dims = _src(source)["dims"]
    keys = [k.strip() for k in (raw or "").split(",") if k.strip()]
    if not keys:
        raise ValueError("Не указано ни одного измерения")
    if len(keys) > MAX_DIMS:
        raise ValueError(f"Слишком много уровней: {len(keys)}, максимум {MAX_DIMS}")
    seen: set[str] = set()
    for k in keys:
        if k not in dims:
            raise ValueError(f"Неизвестное измерение: {k}")
        if k in seen:
            raise ValueError(f"Измерение повторяется: {k}")
        seen.add(k)
    return keys


def dim_expr(key: str, source: str = "transactions"):
    """SQL-выражение измерения. Ключ обязан быть проверен `parse_dims`."""
    return _src(source)["dims"][key]["expr"]


def dim_label(key: str, source: str = "transactions") -> str:
    return _src(source)["dims"][key]["label"]


def dim_select(key: str, source: str = "transactions"):
    """Выражение для SELECT: всё приводим к тексту, чтобы ключи строк были однородны."""
    return cast(dim_expr(key, source), String)


def metric_selects(source: str = "transactions") -> list[tuple[str, Any, int]]:
    """(ключ, выражение, знаков после запятой) для всех метрик источника."""
    return [(k, v["expr"], v["digits"]) for k, v in _src(source)["metrics"].items()]


if __name__ == "__main__":  # самопроверка валидации
    assert parse_dims("station,fuel") == ["station", "fuel"]
    assert parse_dims(" station , fuel ") == ["station", "fuel"]
    for bad in ("", "dims=1=1--", "station,station", "dt::date", "station;drop",
                "station,fuel,payment,day,hour,month"):
        try:
            parse_dims(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"должно было упасть: {bad!r}")
    # Измерения источников не пересекаются вслепую: ключ одного не подходит другому.
    assert parse_dims("supplier,fuel", "receipts") == ["supplier", "fuel"]
    for bad_src in ("payment", "card", "nozzle"):
        try:
            parse_dims(bad_src, "receipts")
        except ValueError:
            pass
        else:
            raise AssertionError(f"ключ реализаций прошёл в поступления: {bad_src}")
    try:
        parse_dims("station", "нет-такого")
    except ValueError:
        pass
    else:
        raise AssertionError("неизвестный источник прошёл")
    assert dim_label("station") == "АЗС"
    assert len(metrics_catalog("receipts")) == 6
    print("pivot_dims: проверки прошли")
