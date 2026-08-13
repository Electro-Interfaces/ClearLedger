"""Каталог категорий оповещений: на что вообще можно подписаться.

Категория = группа действий журнала (`audit_events.action`). Каталог держим в коде, как
`access_catalog` и `channel_catalog`: подписка не может ссылаться на событие, которого
система не порождает — иначе в интерфейсе появляются галочки, за которыми ничего нет.

Источник у всех категорий один — журнал событий пространства. Прогоны каналов загрузки
теперь тоже события журнала (`channel.run.*` пишет фоновый прогон, docs/CONNECT.md В3),
поэтому сбои загрузок стали обычной подпиской. Состояние сервисов (живость контейнеров)
по-прежнему вне журнала — его показывает «Обзор».
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
        # Перечень намеренно от общего к частному: у компании без объектов (профиль
        # office) станций и оборудования нет вовсе, и подписка, обещающая их первыми,
        # выглядит чужой.
        description="Общие сущности пространства: контрагенты, договоры, справочники, "
                    "а у сетевых компаний — объекты и оборудование.",
        prefixes=("space.",),
        default_on=False,
    ),
    NotifyCategory(
        code="logins",
        label="Входы в пространство",
        description="Кто и когда вошёл, неудачные попытки входа, смена пароля, "
                    "переходы в приложения. Шумная категория — включать осознанно.",
        prefixes=("auth.", "sso."),
        default_on=False,
    ),
    NotifyCategory(
        code="load_failures",
        label="Сбои загрузок",
        description="Прогон канала данных упал или прошёл с ошибками: источник "
                    "недоступен, часть станций не загрузилась.",
        prefixes=("channel.run.failed", "channel.run.partial"),
    ),
    NotifyCategory(
        code="loads",
        label="Загрузки данных",
        description="Каждый завершённый прогон канала, включая успешные. "
                    "Шумная категория — ночные автозапуски идут каждый день.",
        prefixes=("channel.",),
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


def probe_action(code: str) -> str:
    """Действие для проверочного оповещения — из префиксов самой категории.

    Раньше карта проб была ручной и покрывала три категории из семи: «Сбои
    загрузок», «Загрузки», «Входы» и «Прочее» проверялись действием
    `test.delivery`, которое относится к «Прочим событиям». Кнопка «Проверить»
    отвечала «доставлено» про другую подписку.
    """
    c = _BY_CODE.get(code)
    if c and c.prefixes:
        p = c.prefixes[0]
        return p + "test" if p.endswith(".") else p
    return "test.delivery"


def is_known(code: str) -> bool:
    return code in _BY_CODE


def label_of(code: str) -> str:
    c = _BY_CODE.get(code)
    return c.label if c else code
