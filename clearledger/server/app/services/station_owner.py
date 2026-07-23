"""Владелец станции ЭЗС: канон и классификация «свои / партнёрские».

`service_locations.owner` приходит грязным: «ООО СНК» и «СНК» — один партнёр,
«Доступная энергия» — это НАШ бренд (РусГидро), «gsegse»/пусто — мусор. Поэтому
владелец приводится к канону, а канон — к классу:

  • own     — наши станции (РусГидро и её бренды);
  • partner — станции партнёра (СНК);
  • unknown — владелец не указан / нераспознан.

Одно место правды, чтобы «своих/партнёрских» одинаково считали обзор,
надёжность, простой и любой будущий разрез. Появится новый партнёр или бренд —
правится только здесь.
"""
from __future__ import annotations

# Подстрока (в нижнем регистре) → канон. Порядок неважен: совпадение по вхождению.
_OWNER_CANON: list[tuple[str, str, str]] = [
    # (подстрока, каноничное имя, класс)
    ("русгидро", "РусГидро", "own"),
    ("доступная энерг", "Доступная энергия", "own"),   # наш бренд, не партнёр
    ("снк", "СНК", "partner"),
]
OWN_LABEL = "Собственные (РусГидро)"
PARTNER_LABEL = "Партнёрские"
UNKNOWN_LABEL = "Владелец не указан"
CLASS_LABELS = {"own": OWN_LABEL, "partner": PARTNER_LABEL, "unknown": UNKNOWN_LABEL}


def owner_canon(raw: str | None) -> tuple[str, str]:
    """(каноничный владелец, класс). Мусор и пустое → ('—', 'unknown')."""
    s = (raw or "").strip().lower()
    if not s:
        return ("—", "unknown")
    for needle, canon, cls in _OWNER_CANON:
        if needle in s:
            return (canon, cls)
    return (raw.strip()[:120], "unknown")   # незнакомый ненулевой владелец — как есть


# SQL-выражение того же канона для агрегатов (owner → класс own|partner|unknown).
# lower(coalesce(owner,'')) — стабильно к регистру и NULL. Держать синхронно с
# _OWNER_CANON выше.
OWNER_CLASS_SQL = """
    case
      when lower(coalesce({col}, '')) like '%русгидро%'
        or lower(coalesce({col}, '')) like '%доступная энерг%' then 'own'
      when lower(coalesce({col}, '')) like '%снк%' then 'partner'
      else 'unknown'
    end
"""


def owner_class_sql(col: str = "sl.owner") -> str:
    """SQL, дающий класс владельца по колонке (по умолчанию service_locations)."""
    return OWNER_CLASS_SQL.format(col=col)
