"""Ручная правка реквизита сохраняет приоритет перед повторным импортом.

Маркеры живут отдельно от raw: исходный снимок должен оставаться снимком
источника. Отмечаются только изменённые поля, а не вся присланная форма.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_SYSTEM_FIELDS = {
    "id", "company_id", "external_ref", "raw", "manual_overrides",
    "created_at", "updated_at",
}


def snapshot_reference_fields(row: Any) -> dict[str, Any]:
    return {
        column.key: deepcopy(getattr(row, column.key))
        for column in row.__table__.columns
        if column.key not in _SYSTEM_FIELDS and column.computed is None
    }


def mark_reference_changes(row: Any, before: dict[str, Any]) -> None:
    changed = {field for field, old in before.items() if getattr(row, field) != old}
    if changed:
        row.manual_overrides = sorted(set(row.manual_overrides or []) | changed)


def apply_import_values(row: Any, values: dict[str, Any]) -> None:
    manual = set(row.manual_overrides or [])
    for field, value in values.items():
        if field not in manual:
            setattr(row, field, value)
