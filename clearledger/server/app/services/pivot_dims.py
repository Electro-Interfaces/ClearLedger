"""Справочник измерений сводной таблицы - единственное место, откуда берётся SQL.

Правило безопасности: в запрос подставляется **только** выражение из этой карты.
Ничего пришедшего от клиента в SQL не попадает: клиент передаёт ключи (`station`,
`fuel`), а не колонки. Неизвестный ключ, дубль и превышение лимита уровней это 400,
а не «молча пропустим».

Второе назначение карты - общий словарь для разных источников тех же данных. Пока
источник один (таблица реализаций), но как только появится второй (выгрузка, кэш,
внешний API), он обязан группировать по этим же ключам, иначе разрезы разъедутся и
заметят это не сразу.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import cast, func
from sqlalchemy.types import String

from app.models import FuelTransaction as T

MAX_DIMS = 5

# key -> (подпись, SQL-выражение). Порядок = порядок в палитре UI.
_DIMS: dict[str, dict[str, Any]] = {
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


def dims_catalog() -> list[dict[str, str]]:
    """Справочник для UI: ключ и подпись. Порядок карты сохраняется."""
    return [{"key": k, "label": v["label"]} for k, v in _DIMS.items()]


def parse_dims(raw: str | None) -> list[str]:
    """CSV ключей → проверенный список. Мусор, дубли и перебор уровней это ошибка.

    Возвращает ключи, а не SQL: подстановкой занимается `dim_expr`, и только он.
    """
    keys = [k.strip() for k in (raw or "").split(",") if k.strip()]
    if not keys:
        raise ValueError("Не указано ни одного измерения")
    if len(keys) > MAX_DIMS:
        raise ValueError(f"Слишком много уровней: {len(keys)}, максимум {MAX_DIMS}")
    seen: set[str] = set()
    for k in keys:
        if k not in _DIMS:
            raise ValueError(f"Неизвестное измерение: {k}")
        if k in seen:
            raise ValueError(f"Измерение повторяется: {k}")
        seen.add(k)
    return keys


def dim_expr(key: str):
    """SQL-выражение измерения. Ключ обязан быть проверен `parse_dims`."""
    return _DIMS[key]["expr"]


def dim_label(key: str) -> str:
    return _DIMS[key]["label"]


def dim_select(key: str):
    """Выражение для SELECT: всё приводим к тексту, чтобы ключи строк были однородны."""
    return cast(dim_expr(key), String)


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
    assert dim_label("station") == "АЗС"
    assert len(dims_catalog()) == len(_DIMS)
    print("pivot_dims: проверки прошли")
