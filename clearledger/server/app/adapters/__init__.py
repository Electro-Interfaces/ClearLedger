"""
Реестр адаптеров источников данных.

Адаптеры регистрируются через декоратор `@register_adapter('source_type')`.
Импорт пакетов адаптеров (sts, onec_odata, ...) триггерит регистрацию.

Использование:
    from app.adapters import get_adapter, list_adapters

    adapter_cls = get_adapter("sts")        # → STSAdapter
    adapters = list_adapters()              # → каталог для UI
"""

from __future__ import annotations

from typing import Type

from app.adapters.base import (
    NormalizedRecord,
    RawBatch,
    SetupField,
    SourceAdapter,
    SourceDocType,
    TestResult,
)

__all__ = [
    "NormalizedRecord",
    "RawBatch",
    "SetupField",
    "SourceAdapter",
    "SourceDocType",
    "TestResult",
    "register_adapter",
    "get_adapter",
    "list_adapters",
]


# Реестр source_type → класс адаптера
_REGISTRY: dict[str, Type[SourceAdapter]] = {}


def register_adapter(source_type: str):
    """Декоратор регистрации адаптера в реестре.

    Применяется к классу — наследнику `SourceAdapter`. Проверяет
    что source_type не занят и что класс корректно унаследован.

        @register_adapter("sts")
        class STSAdapter(SourceAdapter):
            source_type = "sts"
            ...
    """

    def decorator(cls: Type[SourceAdapter]) -> Type[SourceAdapter]:
        if not issubclass(cls, SourceAdapter):
            raise TypeError(
                f"Адаптер {cls.__name__} должен наследоваться от SourceAdapter"
            )
        if source_type in _REGISTRY:
            existing = _REGISTRY[source_type]
            if existing is not cls:
                raise ValueError(
                    f"Дубликат source_type='{source_type}': "
                    f"уже зарегистрирован {existing.__name__}"
                )
        cls.source_type = source_type
        _REGISTRY[source_type] = cls
        return cls

    return decorator


def get_adapter(source_type: str) -> Type[SourceAdapter]:
    """Получить класс адаптера по source_type."""
    if source_type not in _REGISTRY:
        raise KeyError(
            f"Адаптер source_type='{source_type}' не зарегистрирован. "
            f"Доступные: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[source_type]


def list_adapters() -> list[dict]:
    """Каталог зарегистрированных адаптеров для UI.

    Возвращает список словарей с метаданными — то, что нужно для тайлов
    в UI «Каталог источников».
    """
    return [
        {
            "source_type": cls.source_type,
            "label": cls.label,
            "category": cls.category,
            "description": cls.description,
            "icon": cls.icon,
            "setup_schema": [
                {
                    "key": f.key,
                    "label": f.label,
                    "type": f.field_type,
                    "required": f.required,
                    "default_value": f.default_value,
                    "placeholder": f.placeholder,
                    "options": f.options,
                    "help_text": f.help_text,
                    "secret": f.secret,
                }
                for f in cls.setup_schema
            ],
            "available_doc_types": [
                {
                    "id": dt.id,
                    "name": dt.name,
                    "description": dt.description,
                    "category": dt.category,
                }
                for dt in cls.available_doc_types
            ],
        }
        for cls in _REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Автоимпорт пакетов адаптеров — триггер регистрации
# ---------------------------------------------------------------------------
# Каждый модуль ниже импортом регистрирует свой адаптер в _REGISTRY.
# Когда добавляется новый адаптер — добавить строку импорта здесь.

from app.adapters import sts  # noqa: E402, F401
