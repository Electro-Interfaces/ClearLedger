"""Язык запросов к работе: «проект: TF #нерешённые исполнитель: я».

Этап 12 (реестр поручений) и 13в (общая лента). Разбор живёт здесь, а не в
роутере, потому что спрашивают им оба списка: вторая реализация разошлась бы с
первой, и «исполнитель: я» значил бы в двух местах разное.

Разбор на сервере, а не в браузере, — по той же причине: «тот же результат, что
формой» держался бы на честном слове, и расхождение вылезло бы в сохранённом
отборе, где его никто не ищет.

Имена полей русские, с английскими синонимами: язык пространства русский, а
раскладку посреди запроса переключать незачем.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocKind, ServiceLocation, TaskLabel, TaskProject, TaskSprint, TaskType,
    TaskVersion, User, UserCompany,
)

# «проект: TF #нерешённые исполнитель: я приоритет: высокий» — то, что формой не
# выражается: отбор в представлениях описывает простые случаи, а сложные человек
# и так держит в голове, просто не может записать.
#
# Имена полей русские: язык пространства русский, и `assignee` в строке поиска
# читается хуже, чем `исполнитель`. Английские синонимы приняты тоже — они
# набираются быстрее, и переключать раскладку посреди запроса незачем.
#
# Разбор живёт на сервере, а не в браузере. Иначе «тот же результат, что формой»
# держался бы на честном слове: два разных кода отбирали бы задачи по-разному, и
# расхождение вылезло бы там, где его никто не ищет — в сохранённом отборе.

QUERY_FIELDS = {
    "проект": "project", "project": "project",
    "версия": "fix_version", "version": "fix_version",
    "найдена": "found_version", "найдено": "found_version",
    "спринт": "sprint", "sprint": "sprint",
    "исполнитель": "assignee", "assignee": "assignee", "кому": "assignee",
    "автор": "author", "author": "author",
    "метка": "label", "тег": "label", "label": "label",
    "стадия": "stage", "stage": "stage",
    "приоритет": "priority", "срочность": "priority", "priority": "priority",
    "тип": "type", "type": "type",
    "объект": "object", "object": "object",
    "срок": "due", "due": "due",
    # Общая лента (13в): чем предмет является и где он стоит.
    "род": "entity", "kind": "entity",
    "состояние": "state", "state": "state",
}

# Флаги через `#` — крупный разрез, тот же, что кнопками разделов. Отдельный знак
# нужен затем, что «мои» без него неотличимо от слова в заголовке задачи.
QUERY_FLAGS = {
    "нерешённые": ("scope", "open"), "нерешенные": ("scope", "open"),
    "открытые": ("scope", "open"), "open": ("scope", "open"),
    "решённые": ("scope", "closed"), "решенные": ("scope", "closed"),
    "закрытые": ("scope", "closed"), "closed": ("scope", "closed"),
    "мои": ("scope", "mine"), "на_мне": ("scope", "mine"), "mine": ("scope", "mine"),
    "поручил": ("scope", "assigned"), "поручённые": ("scope", "assigned"),
    "наблюдаю": ("scope", "watching"), "watching": ("scope", "watching"),
    "просроченные": ("scope", "overdue"), "просрочено": ("scope", "overdue"),
    "сегодня": ("scope", "today"), "горит": ("scope", "today"),
    "ждём": ("scope", "waiting"), "ждем": ("scope", "waiting"),
    "все": ("scope", "all"), "all": ("scope", "all"),
    "бэклог": ("backlog", True), "backlog": ("backlog", True),
    # Род предмета флагом — короче, чем «род: документ», и читается так же.
    "документы": ("kind", "doc"), "docs": ("kind", "doc"),
    "поручения": ("kind", "task"), "tasks": ("kind", "task"),
}

# Состояния на общей оси словами человека. Коды те же, что в `work_state`.
STATE_WORDS: dict[str, str] = {
    "заведено": "new", "новое": "new", "черновик": "new", "new": "new",
    "в работе": "in_work", "работа": "in_work", "in_work": "in_work",
    "на согласовании": "approval", "согласование": "approval",
    "на визах": "approval", "approval": "approval",
    "ждём внешних": "external", "ждем внешних": "external",
    "внешние": "external", "external": "external",
    "готово": "done", "закрыто": "done", "done": "done",
}

# `поле: значение` (значение в кавычках, если в нём пробел), `#флаг`, остальное —
# свободный текст. Двоеточие обязательно: без него «проект TF» неотличимо от
# поиска слов «проект» и «TF» в заголовке.
QUERY_TOKEN = re.compile(r'#(\S+)|(\w+)\s*:\s*("[^"]*"|\S+)', re.UNICODE)


def _quote_known_phrases(text: str) -> str:
    """Обернуть в кавычки многословные значения из конечных словарей.

    «состояние: на согласовании» человек пишет именно так, а разбор режет
    значение по пробелу — и половина фразы уезжает в свободный текст. Требовать
    кавычки значит требовать помнить о кавычках; проще узнать фразу, раз список
    её значений нам известен заранее.
    """
    # Ищем строкой, а не регуляркой: список фраз конечный и известен заранее,
    # а регулярка на кириллице с `re.escape` здесь читается хуже, чем find.
    low = text.lower()
    for field in ("состояние", "state"):
        for phrase in sorted(STATE_WORDS, key=len, reverse=True):
            if " " not in phrase:
                continue
            for sep in (": ", ":"):
                needle = f"{field}{sep}{phrase}"
                at = low.find(needle)
                if at < 0:
                    continue
                text = text[:at] + f'{field}: "{phrase}"' + text[at + len(needle):]
                low = text.lower()
    return text


async def parse(db: AsyncSession, cid: uuid.UUID, user: User,
                       text: str) -> tuple[dict[str, Any], list[str], str]:
    """Строка запроса → отбор, неузнанное и свободный текст.

    Неузнанное возвращается списком, а не глотается: человек уверен, что отобрал
    работу по исполнителю, а фамилия набрана с опечаткой — и он смотрит на список,
    в котором нет того, что он ищет, считая, что этого нет вовсе.
    """
    text = _quote_known_phrases(text)
    parsed: dict[str, Any] = {}
    unknown: list[str] = []
    free: list[str] = []
    pos = 0

    async def _one(model, where) -> Any:
        return (await db.execute(select(model).where(*where))).scalars().first()

    for m in QUERY_TOKEN.finditer(text):
        free.append(text[pos:m.start()])
        pos = m.end()
        flag, field, raw = m.group(1), m.group(2), m.group(3)

        if flag:
            key = QUERY_FLAGS.get(flag.lower())
            (parsed.update({key[0]: key[1]}) if key else unknown.append(f"#{flag}"))
            continue

        name = QUERY_FIELDS.get((field or "").lower())
        value = (raw or "").strip('"').strip()
        if name is None:
            unknown.append(f"{field}: {value}")
            continue
        low = value.lower()

        if name == "project":
            row = await _one(TaskProject, (TaskProject.company_id == cid,
                                           or_(func.lower(TaskProject.code) == low,
                                               func.lower(TaskProject.name) == low)))
            (parsed.update({"project_id": str(row.id)}) if row
             else unknown.append(f"проект: {value}"))
        elif name in ("fix_version", "found_version"):
            row = await _one(TaskVersion, (TaskVersion.company_id == cid,
                                           func.lower(TaskVersion.name) == low))
            key = "fix_version_id" if name == "fix_version" else "found_version_id"
            (parsed.update({key: str(row.id)}) if row
             else unknown.append(f"версия: {value}"))
        elif name == "sprint":
            row = await _one(TaskSprint, (TaskSprint.company_id == cid,
                                          func.lower(TaskSprint.name) == low))
            (parsed.update({"sprint_id": str(row.id)}) if row
             else unknown.append(f"спринт: {value}"))
        elif name in ("assignee", "author"):
            key = "assignee_id" if name == "assignee" else "author_id"
            # «я» — то, ради чего запрос вообще пишут: «мои нерешённые в TF».
            if low in ("я", "me", "мне"):
                parsed[key] = str(user.id)
                continue
            row = (await db.execute(
                select(User).join(UserCompany, UserCompany.user_id == User.id)
                .where(UserCompany.company_id == cid,
                       func.lower(User.name).like(f"{low}%")))).scalars().first()
            (parsed.update({key: str(row.id)}) if row
             else unknown.append(f"{field}: {value}"))
        elif name == "label":
            row = await _one(TaskLabel, (TaskLabel.company_id == cid,
                                         func.lower(TaskLabel.name) == low))
            (parsed.update({"label_id": str(row.id)}) if row
             else unknown.append(f"метка: {value}"))
        elif name == "type":
            # Тип задачи и вид документа — один вопрос на общей ленте: «что это
            # за работа». Ищем в обоих справочниках, первый нашедшийся выигрывает.
            row = await _one(TaskType, (TaskType.company_id == cid,
                                        or_(func.lower(TaskType.name) == low,
                                            func.lower(TaskType.code) == low)))
            row = row or await _one(DocKind, (DocKind.company_id == cid,
                                              or_(func.lower(DocKind.name) == low,
                                                  func.lower(DocKind.code) == low)))
            (parsed.update({"type_id": str(row.id)}) if row
             else unknown.append(f"тип: {value}"))
        elif name == "stage":
            # Стадия — имя из маршрута любого типа: человек называет её словом,
            # а код стадии видит только тот, кто настраивал маршрут.
            types = (await db.execute(select(TaskType).where(
                TaskType.company_id == cid))).scalars().all()
            code = next((st.get("code") for ty in types for st in (ty.route or [])
                         if (st.get("name") or "").lower() == low), None)
            code = code or next((st["code"] for st in DEFAULT_ROUTE
                                 if st["name"].lower() == low), None)
            (parsed.update({"stage": code}) if code
             else unknown.append(f"стадия: {value}"))
        elif name == "priority":
            code = CMD_PRIORITY.get(low)
            (parsed.update({"priority": code}) if code
             else unknown.append(f"приоритет: {value}"))
        elif name == "object":
            row = (await db.execute(select(ServiceLocation).where(
                ServiceLocation.company_id == cid,
                func.lower(ServiceLocation.name).like(f"%{low}%")))).scalars().first()
            (parsed.update({"object_id": row.id}) if row
             else unknown.append(f"объект: {value}"))
        elif name == "entity":
            entity = {"документ": "doc", "документы": "doc", "doc": "doc",
                      "поручение": "task", "поручения": "task", "задача": "task",
                      "задачи": "task", "task": "task"}.get(low)
            (parsed.update({"kind": entity}) if entity
             else unknown.append(f"род: {value}"))
        elif name == "state":
            code = STATE_WORDS.get(low)
            (parsed.update({"state": code}) if code
             else unknown.append(f"состояние: {value}"))
        elif name == "due":
            now = datetime.now(timezone.utc)
            if low in ("сегодня", "today"):
                parsed["due_to"] = now + timedelta(days=1)
            elif low in ("неделя", "week"):
                parsed["due_to"] = now + timedelta(days=7)
            elif low in ("просрочен", "просрочено", "overdue"):
                parsed["scope"] = "overdue"
            elif (due := cmd_due(value)) is not None:
                parsed["due_to"] = due
            else:
                unknown.append(f"срок: {value}")

    free.append(text[pos:])
    return parsed, unknown, " ".join(" ".join(free).split())


# ── Слова, общие с командной строкой ────────────────────────────────────────
# Один словарь на разбор запроса и на команду над пачкой: «срочная» должна
# значить одно и то же, где бы человек её ни написал.

CMD_PRIORITY = {
    "низкая": "low", "низкий": "low", "low": "low",
    "обычная": "medium", "обычный": "medium", "средняя": "medium", "medium": "medium",
    "срочная": "high", "срочный": "high", "высокая": "high", "high": "high",
    "критичная": "critical", "критичный": "critical", "critical": "critical",
}

DEFAULT_ROUTE: list[dict[str, str]] = [
    {"code": "new", "name": "Постановка"},
    {"code": "in_progress", "name": "В работе"},
    {"code": "review", "name": "Проверка"},
]


def cmd_due(word: str) -> datetime | None:
    """«сегодня», «завтра», «через 3 дня», «12.09.2026» → срок."""
    now = datetime.now(timezone.utc)
    w = (word or "").strip().lower()
    if w in ("сегодня", "today"):
        return now
    if w in ("завтра", "tomorrow"):
        return now + timedelta(days=1)
    if w in ("послезавтра",):
        return now + timedelta(days=2)
    m = re.match(r"^(?:через\s+)?(\d+)\s*(?:дн|день|дня|дней|d)$", w)
    if m:
        return now + timedelta(days=int(m.group(1)))
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(w, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
