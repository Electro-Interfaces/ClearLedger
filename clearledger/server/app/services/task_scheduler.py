"""Регламент «Задач»: повторяющиеся работы, напоминания о сроке, эскалация.

Три вещи, которые обязаны происходить без человека:

* **повторяющаяся задача** порождается по расписанию из шаблона — новая, а не
  воскрешённая: продлевать одну и ту же значило бы терять ответ на вопрос
  «делали ли в прошлом месяце»;
* **напоминание о сроке** уходит исполнителю за сутки и в день просрочки —
  с отметкой `reminded_at`, иначе письмо шло бы каждый тик и его перестали бы
  читать на второй день;
* **эскалация** сообщает старшему, что на задачу не откликнулись за отведённое
  типом время. Смысл не в наказании: работа, которую никто не взял, обязана
  всплыть до срока, а не после.

Устройство повторяет планировщик каналов (`channel_scheduler`): фоновый цикл из
lifespan, advisory-lock от двойного запуска в кластере, ошибка одной компании не
валит тик. Пишется отдельным модулем, потому что предмет другой — там приём
данных, здесь работа людей, и общий цикл смешал бы расписания разной природы.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text

from app.database import async_session_factory
from app.models import (
    Task, TaskChecklistItem, TaskEvent, TaskRecurrence, TaskTemplate, TaskType, User,
)
from app.services import task_mail

log = logging.getLogger("clearledger.tasks.scheduler")

# Тик реже, чем у каналов: работа людей не требует минутной точности, а лишние
# проходы по всем задачам пространства ничего не улучшают.
TICK_SECONDS = 300
LOCK_NAMESPACE = 0x1A5C5ED


def _tz(rule: dict) -> ZoneInfo:
    try:
        return ZoneInfo(str(rule.get("tz") or "Europe/Moscow"))
    except Exception:  # noqa: BLE001 — незнакомый пояс не должен ронять расписание
        return ZoneInfo("Europe/Moscow")


def next_run(rule: dict, after: datetime) -> datetime:
    """Когда расписание сработает в следующий раз (в UTC).

    Считаем в местном времени пояса правила: «первого числа в 9 утра» человек
    понимает по своему календарю, а сервер живёт в UTC.
    """
    tz = _tz(rule)
    local = after.astimezone(tz)
    hh, _, mm = str(rule.get("at") or "09:00").partition(":")
    at_h, at_m = int(hh or 9), int(mm or 0)
    mode = str(rule.get("mode") or "daily").lower()

    nxt = local.replace(hour=at_h, minute=at_m, second=0, microsecond=0)
    if mode == "weekly":
        want = int(rule.get("weekday") or 0)  # 0 — понедельник
        shift = (want - nxt.weekday()) % 7
        nxt += timedelta(days=shift)
        if nxt <= local:
            nxt += timedelta(days=7)
    elif mode == "monthly":
        day = max(1, min(28, int(rule.get("day") or 1)))  # 28 — чтобы был в любом месяце
        nxt = nxt.replace(day=day)
        if nxt <= local:
            nxt = (nxt.replace(day=1) + timedelta(days=32)).replace(day=day, hour=at_h,
                                                                    minute=at_m)
    else:  # daily
        if nxt <= local:
            nxt += timedelta(days=1)
    return nxt.astimezone(timezone.utc)


async def spawn_doc_from_template(db, rec: TaskRecurrence, tpl: TaskTemplate):
    """Породить ДОКУМЕНТ по шаблону: «акт сверки к 5 числу каждого месяца».

    Второго планировщика под документы не заводим: расписание одно на
    пространство, а чем оно кончится, решает шаблон. Номер здесь не выдаётся —
    регистрация остаётся решением человека, и черновик обязан отличаться от
    зарегистрированного даже когда появился сам.
    """
    from app.models import DocCard, DocEvent, DocKind

    kind = await db.get(DocKind, tpl.doc_kind_id)
    if kind is None:
        log.warning("расписание %s: вид документа не найден", rec.id)
        return None
    now = datetime.now(timezone.utc)
    days = tpl.due_days
    d = DocCard(
        company_id=rec.company_id, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction, title=tpl.title,
        summary=tpl.description, author_id=rec.created_by,
        responsible_id=tpl.assignee_id, object_id=tpl.object_id,
        source="api", source_ref=f"recurrence:{rec.id}",
        due_at=now + timedelta(days=days) if days is not None else None)
    db.add(d)
    await db.flush()
    db.add(DocEvent(doc_id=d.id, kind="created", user_id=rec.created_by,
                    to_value=kind.name, note=f"по расписанию «{tpl.name}»"))
    return d


async def spawn_from_template(db, rec: TaskRecurrence, tpl: TaskTemplate) -> Task | None:
    """Породить задачу по шаблону. Возвращает её или None, если шаблон пуст."""
    if not tpl.title:
        return None
    # Шаблон с видом документа порождает документ, а не поручение.
    if getattr(tpl, "doc_kind_id", None):
        await spawn_doc_from_template(db, rec, tpl)
        return None
    now = datetime.now(timezone.utc)
    ttype = await db.get(TaskType, tpl.type_id) if tpl.type_id else None
    route = (ttype.route if ttype and ttype.route else None) or [
        {"code": "new", "name": "Постановка"}]
    days = tpl.due_days if tpl.due_days is not None else (
        ttype.due_days if ttype else None)

    t = Task(
        company_id=rec.company_id, type_id=tpl.type_id, title=tpl.title,
        description=tpl.description,
        priority=tpl.priority or (ttype.default_priority if ttype else "medium"),
        status="open", stage_code=route[0].get("code"),
        assignee_id=tpl.assignee_id, author_id=rec.created_by,
        object_id=tpl.object_id,
        due_at=now + timedelta(days=days) if days is not None else None)
    db.add(t)
    await db.flush()
    db.add(TaskEvent(task_id=t.id, kind="created", user_id=rec.created_by,
                     to_value=route[0].get("name"),
                     note=f"по расписанию «{tpl.name}»"))
    for i, item in enumerate(tpl.checklist or []):
        text_item = str(item).strip()
        if text_item:
            db.add(TaskChecklistItem(task_id=t.id, text=text_item[:500], position=(i + 1) * 10))
    return t


async def run_recurrences(db, now: datetime) -> int:
    """Породить задачи по всем сработавшим расписаниям."""
    rows = (await db.execute(
        select(TaskRecurrence, TaskTemplate)
        .join(TaskTemplate, TaskTemplate.id == TaskRecurrence.template_id)
        .where(TaskRecurrence.enabled.is_(True),
               or_(TaskRecurrence.next_run_at.is_(None),
                   TaskRecurrence.next_run_at <= now)))).all()
    made = 0
    for rec, tpl in rows:
        # Первый прогон расписания задачу не порождает: включили «каждый
        # понедельник» — ждём понедельника, а не создаём сразу.
        if rec.next_run_at is None:
            rec.next_run_at = next_run(rec.rule or {}, now)
            continue
        got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                              {"ns": LOCK_NAMESPACE, "key": rec.id.int % (2 ** 31)})
        if not got:
            continue
        task = await spawn_from_template(db, rec, tpl)
        rec.last_run_at = now
        rec.next_run_at = next_run(rec.rule or {}, now)
        if task is not None:
            made += 1
            person = await db.get(User, task.assignee_id) if task.assignee_id else None
            if person is not None and person.email:
                task_mail.send_notice_async(
                    [person.email], f"Задача №{task.number}: {task.title}",
                    f"Задача поставлена по расписанию «{tpl.name}».")
    return made


async def run_due_reminders(db, now: datetime) -> int:
    """Напомнить исполнителю о сроке: за сутки до и в день просрочки."""
    soon = now + timedelta(days=1)
    rows = (await db.execute(
        select(Task, User.email, User.name)
        .join(User, User.id == Task.assignee_id)
        .where(Task.status == "open", Task.due_at.is_not(None), Task.due_at <= soon,
               User.mail_only.is_(False),
               # Раз в сутки на задачу: «скоро срок» и «срок прошёл» — это два
               # письма за жизнь задачи, а не поток.
               or_(Task.reminded_at.is_(None), Task.reminded_at <= now - timedelta(days=1)),
               # Отданное наружу не напоминаем исполнителю: мяч не у него.
               or_(Task.waiting_for.is_(None), Task.waiting_for != "external")))).all()
    sent = 0
    for t, email, name in rows:
        overdue = t.due_at < now
        subject = (f"Просрочена задача №{t.number}: {t.title}" if overdue
                   else f"Завтра срок по задаче №{t.number}: {t.title}")
        body = (f"{'Срок прошёл' if overdue else 'Срок'}: "
                f"{t.due_at.strftime('%d.%m.%Y')}\n\n{t.description or ''}").strip()
        task_mail.send_notice_async([email], subject, body)
        t.reminded_at = now
        sent += 1
    return sent


async def run_escalations(db, now: datetime) -> int:
    """Сообщить старшему о задачах, на которые не откликнулись вовремя."""
    rows = (await db.execute(
        select(Task, TaskType)
        .join(TaskType, TaskType.id == Task.type_id)
        .where(Task.status == "open", Task.reacted_at.is_(None),
               TaskType.reaction_hours.is_not(None),
               Task.assignee_id.is_not(None)))).all()
    sent = 0
    for t, ttype in rows:
        deadline = t.created_at + timedelta(hours=ttype.reaction_hours)
        if now < deadline:
            continue
        # Эскалация — тоже событие задачи: без следа «почему пришло письмо
        # начальнику» ответа нет ни у кого.
        already = (await db.execute(select(TaskEvent.id).where(
            TaskEvent.task_id == t.id, TaskEvent.kind == "escalate"))).scalar_one_or_none()
        if already is not None:
            continue
        target_id = ttype.escalate_to_id or t.author_id
        target = await db.get(User, target_id) if target_id else None
        assignee = await db.get(User, t.assignee_id)
        db.add(TaskEvent(task_id=t.id, kind="escalate",
                         actor_name=target.name if target else None,
                         to_value=target.name if target else "—",
                         note=f"нет отклика {ttype.reaction_hours} ч"))
        if target is not None and target.email and not target.mail_only:
            task_mail.send_notice_async(
                [target.email],
                f"Нет отклика по задаче №{t.number}: {t.title}",
                f"Исполнитель {assignee.name if assignee else '—'} не приступил за "
                f"{ttype.reaction_hours} ч с постановки.")
        sent += 1
    return sent


async def tick() -> dict[str, int]:
    """Один проход регламента. Ошибка одной части не отменяет остальные."""
    now = datetime.now(timezone.utc)
    out = {"recurrences": 0, "reminders": 0, "escalations": 0}
    async with async_session_factory() as db:
        for key, fn in (("recurrences", run_recurrences),
                        ("reminders", run_due_reminders),
                        ("escalations", run_escalations)):
            try:
                out[key] = await fn(db, now)
                await db.commit()
            except Exception:  # noqa: BLE001 — одна часть не валит остальные
                log.exception("Регламент задач: сбой в «%s»", key)
                await db.rollback()
    return out


async def run_forever() -> None:
    """Фоновый цикл регламента — поднимается из lifespan приложения."""
    log.info("Регламент задач запущен (тик %d с)", TICK_SECONDS)
    while True:
        try:
            res = await tick()
            if any(res.values()):
                log.info("Регламент задач: %s", res)
        except asyncio.CancelledError:
            log.info("Регламент задач остановлен")
            raise
        except Exception:  # noqa: BLE001 — цикл обязан пережить любую ошибку
            log.exception("Сбой тика регламента задач")
        await asyncio.sleep(TICK_SECONDS)
