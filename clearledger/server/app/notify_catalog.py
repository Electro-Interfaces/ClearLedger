"""Каталог категорий оповещений: на что вообще можно подписаться.

Категория = группа действий журнала (`audit_events.action`). Каталог держим в коде, как
`access_catalog` и `channel_catalog`: подписка не может ссылаться на событие, которого
система не порождает — иначе в интерфейсе появляются галочки, за которыми ничего нет.

Источник у всех категорий один — журнал событий пространства. Состояние сервисов и сбои
загрузок сюда НЕ вписаны намеренно: их порождает не журнал, а фоновая проверка, и подписка
на них появится вместе с ней. Пока «что упало прямо сейчас» показывает «Обзор».
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class NotifyCategory:
    code: str
    label: str
    """Что попадает в категорию — человеческим языком, для интерфейса."""
    description: str
    """Префиксы действий журнала. Первое совпадение определяет категорию."""
    prefixes: tuple[str, ...]
    """Разумный дефолт: подписка включена сразу или предлагается выключенной."""
    default_on: bool = True


CATEGORIES: list[NotifyCategory] = [
    NotifyCategory(
        code="people",
        label="Люди пространства",
        description="Человека добавили или убрали, сменилась принадлежность "
                    "(свой сотрудник ↔ компания-партнёр), должность или роль.",
        prefixes=("user.", "member.role", "member.party"),
    ),
    NotifyCategory(
        code="access",
        label="Доступы и роли",
        description="Изменения прав: роль создана или изменена, участнику выдан "
                    "или сужен доступ, изменён скоуп объектов.",
        prefixes=("role.", "member.access", "member.scope"),
    ),
    NotifyCategory(
        code="space",
        label="Объекты и справочники",
        description="Общие сущности пространства: объекты, контрагенты, договоры, "
                    "оборудование — создание и изменение.",
        prefixes=("space.",),
        default_on=False,
    ),
    NotifyCategory(
        code="other",
        label="Прочие события",
        description="Всё остальное, что попадает в журнал организации.",
        prefixes=(),          # ловит то, что не подошло ни одной категории выше
        default_on=False,
    ),
]

_BY_CODE = {c.code: c for c in CATEGORIES}


def list_categories() -> list[dict]:
    """Каталог для интерфейса и конструктора подписок."""
    return [asdict(c) for c in CATEGORIES]


def category_for(action: str) -> str:
    """Категория события по его действию. Не подошло ни одной — «Прочие события».

    Порядок важен: `member.role` относится к людям, а `member.access` — к доступам,
    поэтому сравниваем по конкретным префиксам, а не по одному общему `member.`.
    """
    act = (action or "").strip()
    for c in CATEGORIES:
        if c.prefixes and any(act.startswith(p) for p in c.prefixes):
            return c.code
    return "other"


def is_known(code: str) -> bool:
    return code in _BY_CODE


def label_of(code: str) -> str:
    c = _BY_CODE.get(code)
    return c.label if c else code
