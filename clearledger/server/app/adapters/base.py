"""
Базовый контракт адаптера источника данных.

Каждый SourceType (STS, ОФД, эквайринг, ЭДО, OData 1С, ...) реализуется
отдельным адаптером поверх этого ABC. Адаптеры регистрируются в реестре
через декоратор `@register_adapter('source_type')`.

Унифицированный контракт = планировщик каналов и UI не знают о специфике
источника. Добавление нового источника — новый модуль в adapters/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Описание формы настроек источника
# ---------------------------------------------------------------------------
@dataclass
class SetupField:
    """Одно поле в UI-форме создания/настройки Source."""

    key: str
    label: str
    field_type: Literal["text", "password", "number", "select", "tags", "url"]
    required: bool = True
    default_value: str | None = None
    placeholder: str | None = None
    options: list[dict] | None = None  # [{value, label}, ...] для select
    help_text: str | None = None
    # Если password — UI скрывает значение, бэк шифрует Fernet
    secret: bool = False


# ---------------------------------------------------------------------------
# Тип документа, доступный в источнике
# ---------------------------------------------------------------------------
@dataclass
class SourceDocType:
    """Что умеет тянуть данный источник."""

    id: str  # внутренний ключ ("shift_report", "receipt", "transactions")
    name: str  # «Сменные отчёты», «ТТН», ...
    description: str | None = None
    # Подсказка для UI о порядке выбора (числовое или enum)
    category: str | None = None


# ---------------------------------------------------------------------------
# Результат test_connection
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    ok: bool
    message: str | None = None
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Сырая порция данных от источника (до парсинга)
# ---------------------------------------------------------------------------
@dataclass
class RawBatch:
    """Возвращается из fetch_delta — то, что приехало от источника."""

    source_id: str  # UUID Source-а
    doc_type: str  # ключ SourceDocType.id
    fetched_at: datetime
    # Что забирали — окно фильтра
    since: datetime | None = None
    until: datetime | None = None
    # Сырые элементы (произвольные dict — потом нормализуются)
    items: list[dict[str, Any]] = field(default_factory=list)
    # Метаданные ответа (заголовки, токены пагинации и т.д.)
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Нормализованная запись после parse
# ---------------------------------------------------------------------------
@dataclass
class NormalizedRecord:
    """Унифицированная запись после parse — для записи в нормализованную БД."""

    # Целевая сущность (fuel_shift, fuel_receipt, raw_entry, ...)
    target_entity: str
    # Уникальный ключ записи в источнике (для идемпотентности)
    source_key: str
    # Нормализованные поля под целевую сущность
    payload: dict[str, Any]
    # Источник в виде ссылки на raw item
    raw_ref: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# SourceAdapter — базовый класс
# ---------------------------------------------------------------------------
class SourceAdapter(ABC):
    """
    Базовый адаптер источника данных.

    Каждый конкретный адаптер (STS, ОФД, OData 1С, ...) наследует этот
    класс и реализует обязательные методы.
    """

    # Уникальный код типа источника. Используется в БД как Source.source_type
    # и в UI для подбора иконки/категории.
    source_type: str = ""

    # Человекочитаемое название для UI-каталога.
    label: str = ""

    # Категория в UI-каталоге («Учётные системы», «Топливный учёт АЗС», ...).
    category: str = ""

    # Описание для тайла.
    description: str = ""

    # Иконка (имя из lucide-react, для UI).
    icon: str = "Box"

    # Поля формы настроек.
    setup_schema: list[SetupField] = []

    # Что умеет тянуть.
    available_doc_types: list[SourceDocType] = []

    # ----- Поведение -----

    @abstractmethod
    async def test_connection(
        self, connection: dict[str, Any]
    ) -> TestResult:
        """Проверить доступность источника с заданными credentials.

        `connection` — словарь параметров из формы (по setup_schema).
        Пароли уже расшифрованы вызывающей стороной.
        """
        ...

    @abstractmethod
    async def fetch_delta(
        self,
        connection: dict[str, Any],
        doc_type: str,
        since: datetime | None = None,
        until: datetime | None = None,
        filters: dict[str, Any] | None = None,
    ) -> RawBatch:
        """Получить дельту документов с момента since до until.

        Если since=None — забрать всё (первоначальная синхронизация).
        `filters` — дополнительные параметры (например, station для STS).
        """
        ...

    async def parse(self, raw: RawBatch) -> list[NormalizedRecord]:
        """Преобразовать сырой батч в нормализованные записи.

        Дефолтная реализация — пустой список. Каждый адаптер переопределяет
        для своих типов документов.
        """
        return []
