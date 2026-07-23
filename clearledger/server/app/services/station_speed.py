"""Скорость станции ЭЗС: медленная (AC) / быстрая (DC).

Классифицирует станцию по паспортному `speed_class` (fast/slow из справочника
CPO), а где он не заполнен — по номинальной мощности: DC-быстрые от 50 кВт,
ниже — AC-медленные. Одно место правды, чтобы «медленные/быстрые» одинаково
считали все разрезы (как [[station_owner]] для владельца).
"""
from __future__ import annotations

FAST_LABEL = "Быстрые (DC)"
SLOW_LABEL = "Медленные (AC)"
UNKNOWN_LABEL = "Скорость не указана"
SPEED_LABELS = {"fast": FAST_LABEL, "slow": SLOW_LABEL, "unknown": UNKNOWN_LABEL}
SPEED_ORDER = ("fast", "slow", "unknown")
# Порог быстрой (DC) зарядки в кВт — фолбэк, когда speed_class пуст.
FAST_KW = 50


def speed_class_sql(prefix: str = "sl.") -> str:
    """SQL-класс скорости по колонкам service_locations (speed_class + power_kwt).
    prefix — префикс таблицы ('sl.' для джойна, '' для одиночной)."""
    p = prefix
    return f"""
        case
          when lower(coalesce({p}speed_class, '')) = 'fast' then 'fast'
          when lower(coalesce({p}speed_class, '')) = 'slow' then 'slow'
          when {p}power_kwt >= {FAST_KW} then 'fast'
          when {p}power_kwt > 0 then 'slow'
          else 'unknown'
        end
    """
