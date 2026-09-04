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
* **ознакомление** напоминает человеку о непрочитанном документе к сроку;
* **виза** напоминает согласующему и его заместителю: срок визы хранился с самого
  начала, но никого не дёргал, и согласование вставало молча;
* **обмен с СЭД** проверяет только явно включённые и уже обкатанные папки.

Устройство повторяет планировщик каналов (`channel_scheduler`): фоновый цикл из
lifespan, advisory-lock от двойного запуска в кластере, ошибка одной компании не
валит тик. Пишется отдельным модулем, потому что предмет другой — там приём
данных, здесь работа людей, и общий цикл смешал бы расписания разной природы.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
import calendar
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, cast, func, or_, select, text

from app.auth import resolve_member_modules
from app.database import async_session_factory
from app.models import (
    DocAcquaint, DocApproval, DocBreakGlassAccess, DocCard, DocExchangeTarget,
    PartnerMessage, PartnerSpace, PartnerTopic,
    Task, TaskChecklistItem, TaskEvent, TaskRecurrence, TaskTemplate, TaskType,
    User, UserCompany,
)
from app.services import (
    digest, doc_approvals, doc_exchange, process_templates, space_events,
    space_time, task_mail, work_state)

log = logging.getLogger("clearledger.tasks.scheduler")

# Тик реже, чем у каналов: работа людей не требует минутной точности, а лишние
# проходы по всем задачам пространства ничего не улучшают.
TICK_SECONDS = 300
LOCK_NAMESPACE = 0x1A5C5ED
ACQUAINT_LOCK_KEY = 0x0AC011
EXCHANGE_LOCK_KEY = 0x0ED011
BREAK_GLASS_LOCK_KEY = 0x0B6A55
APPROVAL_LOCK_KEY = 0x0A9F00
EVENTS_LOCK_KEY = 0x0E7E415
PERSONAL_LOCK_KEY = 0x0FE250
DIGEST_LOCK_KEY = 0x0D19E57

# Доля срока реакции, оставшаяся к моменту предупреждения: последняя четверть.
# Не фиксированный час: у типа со сроком реакции в два часа предупреждение за
# час — это половина срока и шум, а у суточного за час до конца человек уже
# ничего не успеет.
WARN_FRACTION = 0.25

# Сколько встреч за проход кладём в сводки. Предел, а не отбор: в
# пространстве на сотню человек их за сутки десятки, и упереться в него
# нельзя, но неограниченная выборка по всем компаниям стека — способ
# однажды вытащить в память полугодовой календарь.
_MEETING_LIMIT = 500

# На сколько вперёд материализуется серия и сколько встреч за проход.
# Горизонт — чтобы занятость и подбор времени видели планёрки заранее;
# предел за проход — чтобы включённая на год серия не вставила полсотни
# строк одним заходом и не заперла таблицу.
SERIES_HORIZON_DAYS = 60
SERIES_MAX_PER_TICK = 40

# Проходы, которые не шлют сами, а кладут повод в сводку окна.
_WITH_BUCKET = frozenset({"reminders", "escalations", "acquaints",
                          "approvals", "meetings", "partner_topics", "digests"})


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
    """Запустить документный процесс по расписанию тем же путём, что вручную."""
    actor = await db.get(User, rec.created_by) if rec.created_by else None
    if actor is None:
        log.warning("расписание %s: автор запуска не найден", rec.id)
        return None
    try:
        doc, _ = await process_templates.launch(
            db, rec.company_id, tpl, actor,
            source="api",
            source_ref=(f"recurrence:{rec.id}:"
                        f"{datetime.now(timezone.utc).isoformat()}"),
            source_note=f"по расписанию «{tpl.name}»",
        )
        return doc
    except process_templates.ProcessTemplateError as exc:
        log.warning("расписание %s: %s", rec.id, exc)
        return None


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
        stage_column=work_state.stage_column_of(route, route[0].get("code")),
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


async def run_due_reminders(db, now: datetime, bucket: digest.Bucket) -> int:
    """Напомнить исполнителю о сроке: за сутки до и в день просрочки.

    Не письмом и не сразу: повод кладётся в сводку окна (`services/digest.py`).
    Письмо на каждый срок и было тем потоком, из-за которого напоминания
    перестают читать, — а «завтра срок» не бывает срочнее сна.
    """
    soon = now + timedelta(days=1)
    # Кому напоминаем: исполнителю, а у своей записи — автору. Личная запись
    # исполнителя не имеет, и без этого `coalesce` она молча выпадала бы из
    # выборки на самом соединении.
    получатель = func.coalesce(Task.assignee_id, Task.author_id)
    rows = (await db.execute(
        select(Task)
        .join(User, User.id == получатель)
        .where(Task.status == "open", Task.due_at.is_not(None), Task.due_at <= soon,
               User.mail_only.is_(False),
               # Раз в сутки на задачу: «скоро срок» и «срок прошёл» — это два
               # повода за жизнь задачи, а не поток.
               or_(Task.reminded_at.is_(None), Task.reminded_at <= now - timedelta(days=1)),
               # Отданное наружу не напоминаем исполнителю: мяч не у него.
               or_(Task.waiting_for.is_(None), Task.waiting_for != "external"),
               # Своя запись со сроком напоминает о себе наравне с поручением:
               # правило «без срока — заметка, со сроком — дело» иначе остаётся
               # обещанием. Запрет на личное был верен, пока напоминание уходило
               # ПИСЬМОМ на рабочий ящик; сводка приходит в личную комнату
               # самого человека, где её не видит никто, включая администратора.
               or_(Task.visibility != "personal",
                   Task.author_id == получатель)))).scalars().all()
    sent = 0
    for t in rows:
        overdue = t.due_at < now
        # Срок датируется поясом ОРГАНИЗАЦИИ: он один на всех, кто работает по
        # этому договору, и у получателя из Владивостока не должен наступать
        # раньше, чем у московского коллеги.
        день = t.due_at.astimezone(
            space_time.zone(await bucket.tz(db, t.company_id))).strftime("%d.%m.%Y")
        bucket.add(
            t.company_id, t.assignee_id or t.author_id, f"task-due:{t.id}",
            (f"{'Просрочено' if overdue else 'Завтра срок'}: №{t.number} "
             f"«{t.title}» — {день}"),
            mark=lambda t=t: setattr(t, "reminded_at", now))
        sent += 1
    return sent


async def run_escalations(db, now: datetime, bucket: digest.Bucket) -> int:
    """Сообщить старшему о задачах, на которые не откликнулись вовремя, —
    предупредив исполнителя ДО этого.

    Два решения, и оба против того, чтобы эскалацию заглушили.

    **Предупреждение исполнителю.** Когда прошло три четверти срока реакции,
    человек получает в сводку строку «если не приступить до 17:00, задача уйдёт
    к N». Эскалация, о которой узнают постфактум, читается как донос, и её
    начинают обходить — договариваться заранее мимо системы. Предупреждение
    возвращает решение тому, кто ещё может его принять. Оно снабжено сроком
    годности: доставить его после того, как задача ушла наверх, бессмысленно, и
    сводка такую строку выбросит молча.

    **Наверх адресуется ПРЕДМЕТ, а не человек.** Строка начинается с задачи и
    её простоя, исполнитель — факт в конце, а не обвиняемый в начале. Плоская
    схема «любая просрочка → руководителю» глушится за недели именно потому,
    что читается как поток жалоб на людей.
    """
    rows = (await db.execute(
        select(Task, TaskType)
        .join(TaskType, TaskType.id == Task.type_id)
        .where(Task.status == "open", Task.reacted_at.is_(None),
               TaskType.reaction_hours.is_not(None),
               Task.assignee_id.is_not(None),
               # Эскалация личной записи сообщила бы старшему о её
               # существовании — ровно то, чего слово «личное» обещает не
               # делать. Тип с реакцией у личной задачи взяться может: человек
               # поднял в личное готовый шаблон.
               Task.visibility != "personal"))).all()
    sent = 0
    for t, ttype in rows:
        deadline = t.created_at + timedelta(hours=ttype.reaction_hours)
        # Событие задачи — единственный след, по которому потом отвечают на
        # вопрос «почему это ушло наверх» и «почему повторно не ушло».
        следы = set((await db.execute(select(TaskEvent.kind).where(
            TaskEvent.task_id == t.id,
            TaskEvent.kind.in_(("escalate", "escalate_warn"))))).scalars())

        if now < deadline:
            if now < deadline - timedelta(hours=ttype.reaction_hours * WARN_FRACTION):
                continue
            if "escalate_warn" in следы:
                continue
            target_id = ttype.escalate_to_id or t.author_id
            target = await db.get(User, target_id) if target_id else None
            assignee = await db.get(User, t.assignee_id)
            когда = deadline.astimezone(
                space_time.zone(assignee.tz if assignee else None)).strftime("%H:%M")
            bucket.add(
                t.company_id, t.assignee_id, f"escalate-warn:{t.id}",
                (f"Ждёт вашего отклика: №{t.number} «{t.title}». Если не "
                 f"приступить до {когда}, уйдёт к "
                 f"{target.name if target else 'постановщику'}"),
                mark=lambda t=t: db.add(TaskEvent(
                    task_id=t.id, kind="escalate_warn",
                    note="предупреждение исполнителю")),
                expires_at=deadline)
            sent += 1
            continue

        if "escalate" in следы:
            continue
        target_id = ttype.escalate_to_id or t.author_id
        target = await db.get(User, target_id) if target_id else None
        assignee = await db.get(User, t.assignee_id)
        след = TaskEvent(task_id=t.id, kind="escalate",
                         actor_name=target.name if target else None,
                         to_value=target.name if target else "—",
                         note=f"нет отклика {ttype.reaction_hours} ч")
        if target is None or target.mail_only:
            # Сказать некому: тип без старшего и задача без автора. След ставим
            # сразу — иначе регламент пересматривал бы эту задачу вечно, — но
            # называем вещи своими именами. Прежняя запись утверждала «ушло к —»,
            # то есть карточка сообщала о сработавшем регламенте, которого не
            # было; по ней же повторный прогон отказывался пробовать снова.
            след.to_value = "некому"
            след.note = (f"нет отклика {ttype.reaction_hours} ч; "
                         "получатель не назначен — эскалация не доставлена")
            db.add(след)
            sent += 1
            continue
        # След ставится ТОЛЬКО вместе с доставкой. Поставь его сразу — и ночная
        # эскалация пометится случившейся, а утренняя сводка её уже не найдёт:
        # старший не узнает никогда, а в карточке будет написано, что ушло.
        bucket.add(
            t.company_id, target.id, f"escalate:{t.id}",
            (f"Без отклика {ttype.reaction_hours} ч: №{t.number} "
             f"«{t.title}» (исполнитель — "
             f"{assignee.name if assignee else '—'})"),
            mark=lambda с=след: db.add(с))
        sent += 1
    return sent


async def run_acquaint_reminders(db, now: datetime, bucket: digest.Bucket) -> int:
    """Напомнить о документе за сутки до срока и затем не чаще раза в сутки.

    Повод идёт в сводку окна, а не письмом на каждое ознакомление.
    """
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": ACQUAINT_LOCK_KEY})
    if not got:
        return 0
    soon = now + timedelta(days=1)
    rows = (await db.execute(
        select(DocAcquaint, DocCard, User, UserCompany)
        .join(DocCard, and_(DocCard.id == DocAcquaint.doc_id,
                            DocCard.company_id == DocAcquaint.company_id))
        .join(User, User.id == DocAcquaint.user_id)
        .join(UserCompany, and_(UserCompany.user_id == DocAcquaint.user_id,
                                UserCompany.company_id == DocAcquaint.company_id))
        .where(DocAcquaint.status == "pending", DocAcquaint.due_at.is_not(None),
               User.mail_only.is_(False),
               DocAcquaint.due_at <= soon,
               # Раз в сутки на ознакомление. Отсева по «когда пробовали»
               # больше нет: он сторожил повторную ОТПРАВКУ ПИСЬМА, а повод
               # теперь просто кладётся в сводку, и та сама не повторяет
               # сказанное внутри окна.
               or_(DocAcquaint.reminded_at.is_(None),
                   DocAcquaint.reminded_at <= now - timedelta(days=1))))).all()
    sent = 0
    for acquaint, doc, user, membership in rows:
        if not user.is_superadmin and membership.role != "admin":
            modules = await resolve_member_modules(membership, db)
            if (modules is not None and "docs" not in modules and not any(
                    key.startswith("docs:") for key in modules)):
                continue
        overdue = acquaint.due_at < now
        number = doc.reg_number or "без номера"
        день = acquaint.due_at.astimezone(space_time.zone(
            await bucket.tz(db, acquaint.company_id))).strftime("%d.%m.%Y")
        bucket.add(
            acquaint.company_id, acquaint.user_id, f"acquaint:{acquaint.id}",
            (f"{'Просрочено ознакомление' if overdue else 'Ознакомиться'}: "
             f"«{doc.title}» ({number}) — до {день}"),
            mark=lambda a=acquaint: setattr(a, "reminded_at", now))
        sent += 1
    return sent


async def run_approval_reminders(db, now: datetime, bucket: digest.Bucket) -> int:
    """Напомнить согласующему о визе за сутки до срока и затем раз в сутки.

    Срок визы хранился с самого начала и не делал ничего: планировщик круг не
    читал, а `sla_hours` доезжал только до отчёта. Согласование останавливалось
    молча — ровно там, где документ ждёт одного человека.

    Заместителю тот же повод уходит в его сводку. Виза за другого запрещена, но
    отпуск не должен держать документ: заместитель визирует от своего имени, и
    узнать об ожидании он обязан не позже того, кого замещает.

    Доставка — сводкой окна, а не письмом на каждую визу: письмо по поводу на
    повод и было тем потоком, из-за которого напоминания перестают читать.
    """
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": APPROVAL_LOCK_KEY})
    if not got:
        return 0
    soon = now + timedelta(days=1)
    rows = (await db.execute(
        select(DocApproval, DocCard, User, UserCompany)
        .join(DocCard, and_(DocCard.id == DocApproval.doc_id,
                            DocCard.company_id == DocApproval.company_id))
        .join(User, User.id == DocApproval.assignee_id)
        .join(UserCompany, and_(UserCompany.user_id == DocApproval.assignee_id,
                                UserCompany.company_id == DocApproval.company_id))
        .where(DocApproval.status == "pending", DocApproval.due_at.is_not(None),
               User.mail_only.is_(False),
               DocApproval.due_at <= soon,
               or_(DocApproval.reminded_at.is_(None),
                   DocApproval.reminded_at <= now - timedelta(days=1))))).all()
    sent = 0
    for approval, doc, user, membership in rows:
        if not user.is_superadmin and membership.role != "admin":
            modules = await resolve_member_modules(membership, db)
            if (modules is not None and "docs" not in modules and not any(
                    key.startswith("docs:") for key in modules)):
                continue
        overdue = approval.due_at < now
        number = doc.reg_number or "без номера"
        срок = approval.due_at.astimezone(space_time.zone(
            await bucket.tz(db, approval.company_id))).strftime("%d.%m.%Y %H:%M")
        строка = (f"{'Просрочена виза' if overdue else 'Виза'}: «{doc.title}» "
                  f"({number}, {approval.step_name or 'согласование'}) — до {срок}")
        bucket.add(approval.company_id, approval.assignee_id,
                   f"approval:{approval.id}", строка,
                   mark=lambda a=approval: setattr(a, "reminded_at", now))
        # Заместителю — тем же поводом в его сводку. Виза за другого запрещена,
        # но отпуск не должен держать документ: заместитель визирует от своего
        # имени и узнать об ожидании обязан не позже того, кого замещает.
        # Отметку «сказано» ставит только строка основного согласующего: иначе
        # молчание заместителя гасило бы напоминание тому, кто визирует.
        for deputy_id in await doc_approvals.active_deputy_for(
                db, approval.company_id, user.id):
            bucket.add(approval.company_id, deputy_id, f"approval:{approval.id}",
                       f"{строка} (замещаете: {user.name})")
        sent += 1
    return sent


async def run_meeting_series(db, now: datetime) -> int:
    """Материализовать повторяющиеся встречи вперёд, на горизонт.

    Серия — не правило, разворачиваемое на чтении, а настоящие строки. Так
    участники, ответы, занятость, отмена и правка ОДНОЙ встречи работают тем же
    кодом, что у обычной: «изменить эту» — это правка строки, а не машина
    исключений из серии, ради которой пришлось бы завести второй способ
    существовать у каждой встречи.

    Ответ переносится с головы серии, а не спрашивается заново: «буду на
    планёрке» сказано один раз, и переспрашивать каждую неделю значит отправить
    человеку пятьдесят два вопроса в год — ровно тот поток, от которого мы уходим
    окнами доставки. Отказаться от одной встречи он по-прежнему может.
    """
    from app.models import CalendarAttendee, CalendarEvent

    горизонт = now + timedelta(days=SERIES_HORIZON_DAYS)
    головы = (await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.recurrence.is_not(None),
            CalendarEvent.status == "planned").limit(200))).scalars().all()
    создано = 0
    for head in головы:
        правило = head.recurrence or {}
        # Второй заслон к тому же: голова без внятного режима серией не
        # считается. Один заслон здесь уже подводил.
        if not isinstance(правило, dict) or not правило.get("mode"):
            continue
        зона = space_time.zone(head.tz)
        длительность = head.ends_at - head.starts_at
        предел = None
        if head.recurrence_until:
            предел = datetime.combine(head.recurrence_until, time(23, 59),
                                      tzinfo=зона)

        # Последняя уже созданная встреча серии — от неё и продолжаем. Считать
        # от головы значило бы каждый проход перебирать всю историю серии.
        последняя = await db.scalar(
            select(func.max(CalendarEvent.starts_at)).where(
                or_(CalendarEvent.series_id == head.id,
                    CalendarEvent.id == head.id)))
        курсор = space_time.as_utc(последняя or head.starts_at)

        участники = (await db.execute(select(CalendarAttendee).where(
            CalendarAttendee.event_id == head.id))).scalars().all()

        while True:
            следующая = _next_occurrence(курсор, правило, зона)
            if следующая is None or следующая > горизонт:
                break
            if предел is not None and следующая > предел:
                break
            if создано >= SERIES_MAX_PER_TICK:
                break
            копия = CalendarEvent(
                company_id=head.company_id, organizer_id=head.organizer_id,
                title=head.title, description=head.description,
                starts_at=следующая, ends_at=следующая + длительность,
                all_day=head.all_day, tz=head.tz, location=head.location,
                conference_url=head.conference_url, visibility=head.visibility,
                subject_ref=head.subject_ref, series_id=head.id)
            db.add(копия)
            await db.flush()
            for a in участники:
                db.add(CalendarAttendee(
                    event_id=копия.id, user_id=a.user_id, role=a.role,
                    response=a.response))
            курсор = следующая
            создано += 1
    return создано


def _next_occurrence(after: datetime, rule: dict, zone) -> datetime | None:
    """Следующее повторение после указанного момента.

    Час и минута берутся у самой встречи, а не у правила: серия задаётся
    временем головы, и второе место, где записано «в 10:00», разошлось бы с ней
    при первом же переносе.
    """
    шаг = max(1, int(rule.get("interval") or 1))
    # Без явного режима повторения нет. Умолчание «неделя» выглядело удобным и
    # означало, что любая строка с пустым правилом становится еженедельной.
    режим = str(rule.get("mode") or "").lower()
    здесь = after.astimezone(zone)
    if режим == "daily":
        return (здесь + timedelta(days=шаг)).astimezone(timezone.utc)
    if режим == "weekly":
        return (здесь + timedelta(weeks=шаг)).astimezone(timezone.utc)
    if режим == "monthly":
        # Через сложение дней, а не подменой номера месяца: 31-е есть не в
        # каждом, и «каждое 31-е» иначе то пропадает, то уезжает на март.
        месяц = здесь.month - 1 + шаг
        год = здесь.year + месяц // 12
        месяц = месяц % 12 + 1
        день = min(здесь.day, calendar.monthrange(год, месяц)[1])
        return здесь.replace(year=год, month=месяц, day=день).astimezone(timezone.utc)
    return None


async def run_meetings(db, now: datetime, bucket: digest.Bucket) -> int:
    """Сегодняшние встречи — поводом в утреннюю сводку.

    Встреча в сводке нужна не как напоминание за пять минут (для этого есть своё,
    которое человек ставит сам), а как каркас дня: утром он должен увидеть, во
    сколько его ждут, вместе со всем остальным, а не в отдельном сообщении.

    Поэтому повод один на встречу и на день: ключ содержит дату, и вторая сводка
    того же дня о ней не напомнит. Отменённые не берём — о них человек узнаёт из
    самой отмены, и «в 15:00 совещание» о снятой встрече хуже молчания.
    """
    from app.models import CalendarAttendee, CalendarEvent

    завтра = now + timedelta(days=1)
    rows = (await db.execute(
        select(CalendarEvent, CalendarAttendee.user_id)
        .join(CalendarAttendee, CalendarAttendee.event_id == CalendarEvent.id)
        .where(CalendarEvent.status == "planned",
               CalendarEvent.starts_at >= now,
               CalendarEvent.starts_at < завтра,
               # Отказавшийся получил бы напоминание о том, куда не идёт.
               CalendarAttendee.response != "declined")
        .limit(_MEETING_LIMIT))).all()
    # Пояс ПОЛУЧАТЕЛЯ, а не организации: повод адресован конкретному человеку и
    # читается его глазами. Поясом компании датируется СРОК — обязательство,
    # одно на всех; время встречи так датировать нельзя, иначе владивостокскому
    # участнику московская сводка напишет «в 10:00» о встрече, которая у него
    # в 17:00.
    люди = {u.id: u for u in (await db.execute(select(User).where(
        User.id.in_({uid for _, uid in rows})))).scalars()} if rows else {}
    for ev, uid in rows:
        когда = ev.starts_at.astimezone(
            space_time.zone(люди[uid].tz if uid in люди else None))
        bucket.add(
            ev.company_id, uid,
            f"meeting:{ev.id}:{когда.date().isoformat()}",
            ("Весь день: " if ev.all_day
             else f"В {когда.strftime('%H:%M')}: ") + f"«{ev.title}»"
            + (f" · {ev.location}" if ev.location else ""),
            # После начала встречи повод бессмыслен: сводка выбросит его молча.
            expires_at=ev.starts_at)
    return len(rows)


async def run_event_delivery(db, now: datetime) -> int:
    """Разослать события пространства подписчикам и погасить молчащих.

    Отдельного цикла для шины не заводим: доставка события терпит пять минут,
    а второй фоновый проход означал бы второй лок, второй лог и второй способ
    упасть. Понадобится мгновенная отдача — это будет отдельное решение.
    """
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": EVENTS_LOCK_KEY})
    if not got:
        return 0
    sent = await space_events.deliver_pending(db, now)
    await space_events.disable_dead(db, now)
    return sent


async def run_exchange_scans(db, now: datetime) -> int:
    """Проверить включённые папки СЭД; принятие найденного остаётся ручным."""
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": EXCHANGE_LOCK_KEY})
    if not got:
        return 0
    targets = (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.is_active.is_(True),
        DocExchangeTarget.scan_enabled.is_(True),
        DocExchangeTarget.inbox_path != ""))).scalars().all()
    added = 0
    for target in targets:
        interval = timedelta(minutes=max(5, target.scan_interval_min or 30))
        if target.last_scan_at and target.last_scan_at > now - interval:
            continue
        try:
            async with db.begin_nested():
                added += await doc_exchange.collect_inbox(db, target)
        except Exception as exc:  # noqa: BLE001 — одна папка не блокирует остальные
            target.last_scan_at = now
            target.last_error = str(exc)[:500]
            log.warning("автоскан СЭД %s: %s", target.id, exc)
    return added


async def run_break_glass_notifications(db, now: datetime) -> int:
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": BREAK_GLASS_LOCK_KEY})
    if not got:
        return 0
    rows = list((await db.execute(select(DocBreakGlassAccess).where(
        DocBreakGlassAccess.notification_status.in_(("pending", "error")),
        DocBreakGlassAccess.created_at >= now - timedelta(days=7),
    ).order_by(DocBreakGlassAccess.created_at).limit(100)
        .with_for_update(skip_locked=True))).scalars().all())
    sent = 0
    for row in rows:
        ok, error = await task_mail.send_notice_checked(
            row.notification_recipients or [],
            "Трек: активирован аварийный доступ",
            "Суперадминистратор активировал временный доступ к закрытому документу.\n"
            f"Код карточки: {row.doc_id}\n"
            f"Срок: {row.expires_at.isoformat()}\n"
            f"Причина: {row.reason}",
        )
        row.notification_status = "sent" if ok else "error"
        row.notification_error = error
        sent += int(ok)
    return sent


async def run_inbound_events(db: AsyncSession, now: datetime) -> int:
    """Разобрать принятые события приложений.

    Приём и обработка разделены: ручка отвечает отправителю сразу, иначе наша
    внутренняя ошибка превращалась бы в бесконечную повторную доставку.
    """
    from app.services import inbound_events
    return await inbound_events.process_pending(db)


async def run_approval_delivery(db: AsyncSession, now: datetime) -> int:
    """Отдать процессам исходы закрытых кругов виз.

    Круг закрывается независимо от того, доступен ли сейчас Координатор, поэтому
    исход сначала фиксируется у себя, а доставляется отсюда с повторами: визы
    собирают один раз, второй раз их никто собирать не будет.
    """
    from app.services import approval_requests
    return await approval_requests.deliver_pending(db)


async def run_project_reconcile(db: AsyncSession, now: datetime) -> int:
    """Досверить проекты, у которых шаг маршрута начат, но не отражён.

    Шаг применяется в двух системах по очереди, и обрыв между ними оставлял
    маршрут впереди, а проект позади — навсегда: повторить шаг нельзя, второй раз
    ребро не сработает. Раньше это чинило только чужое открытие карточки, то есть
    дата ввода в эксплуатацию зависела от того, кто и когда зайдёт на экран.

    Берём отметки старше пяти минут: меньший порог поймал бы шаг, который прямо
    сейчас нормально доигрывается в соседнем запросе.
    """
    from app.models import EzsSite
    from app.services import projects_process

    cutoff = now - timedelta(minutes=5)
    rows = (await db.execute(
        select(EzsSite).where(
            EzsSite.pending_link_id.is_not(None),
            EzsSite.pending_at < cutoff,
        ).limit(50)
    )).scalars().all()

    done = 0
    for site in rows:
        try:
            await projects_process.reconcile(db, site.company_id, site, user=None)
            site.pending_link_id = None
            site.pending_at = None
            done += 1
        except Exception:  # noqa: BLE001 — один проект не отменяет остальные
            log.exception("Досверка проекта %s не удалась", site.id)
    return done + await _refresh_route_snapshots(db, now)


async def _refresh_route_snapshots(db: AsyncSession, now: datetime) -> int:
    """Освежить снимок хода у живых проектов — ради отбора по узлу маршрута.

    Ход ведёт «Поддержка», и её фасад отвечает только про один предмет: списком
    узнать, кто на каком узле стоит, нельзя. Поэтому реестр отбирает по снимку, а
    снимок до сих пор появлялся лишь там, где кто-то делал шаг, — у 117 проектов
    из тысячи. Отбор по узлу на таких данных врал бы молча.

    Пачками по 40 за проход и не чаще, чем раз в шесть часов на проект: маршрут
    двигают руками, и чаще спрашивать нечего.
    """
    from app.models import EzsSite, ProcessSnapshot
    from app.services import ezs_sites, projects_process

    stale = now - timedelta(hours=6)
    свежие = select(ProcessSnapshot.subject_id).where(
        ProcessSnapshot.subject_type == "ezs_site", ProcessSnapshot.at >= stale)
    rows = (await db.execute(
        select(EzsSite).where(
            EzsSite.stage.in_(ezs_sites.STAGE_ORDER),
            cast(EzsSite.id, String).not_in(свежие),
        ).limit(40)
    )).scalars().all()

    done = 0
    for site in rows:
        try:
            # Читаем ход и запоминаем его — и только. `reconcile` здесь звать
            # нельзя: он отражает исход маршрута в воронке, то есть массово двигал
            # бы стадии живых проектов фоном, без человека и без причины.
            state = await projects_process.case_state(db, site.company_id, site)
            if state.get("exists"):
                await projects_process._remember(db, site.company_id, site, state)
                done += 1
        except Exception:  # noqa: BLE001 — недоступный Координатор не роняет регламент
            log.debug("Снимок хода проекта %s не обновлён", site.id)
    return done


async def run_personal_reminders(db, now: datetime) -> int:
    """Доставить сработавшие личные напоминания — в чат, не письмом.

    Отдельно от `run_due_reminders`: там срок задачи и почта всей компании,
    здесь — то, что человек назначил себе сам. Совмещать их значило бы либо
    слать личное почтой, либо лишить общие задачи писем.
    """
    from app.models import PersonalReminder
    from app.services import notify

    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": PERSONAL_LOCK_KEY})
    if not got:
        return 0
    rows = (await db.execute(
        select(PersonalReminder, User)
        .join(User, User.id == PersonalReminder.user_id)
        .where(PersonalReminder.remind_at <= now,
               PersonalReminder.fired_at.is_(None),
               PersonalReminder.done_at.is_(None))
        .limit(200))).all()
    sent = 0
    for row, user in rows:
        # Отметку ставим до доставки: сорванная доставка не должна оборачиваться
        # повторами каждые пять минут. Напоминание останется в колокольчике —
        # человек его увидит, даже если сообщение не дошло.
        row.fired_at = now
        try:
            await notify.notify_person(
                db, row.company_id, user, await _reminder_text(db, row),
                # Человек сам назначил это время, поэтому тишину оно проходит:
                # в тишину не пропускается регламентное, а не своё. Срок жизни
                # push всё равно ограничиваем — вернувшийся из офлайна не
                # должен получать вчерашнее как новое.
                ttl=space_time.push_ttl(now, user.tz, user.work_end))
            sent += 1
        except Exception:  # noqa: BLE001 — одно напоминание не валит остальные
            log.exception("Личное напоминание %s не доставлено", row.id)
    return sent


async def _reminder_text(db, row) -> str:
    """Текст напоминания: своя заметка, иначе предмет своим названием.

    Ссылка на предмет собирается по тому же словарю `<вид>:<ключ>`, что
    `subject_ref`. Название вытягиваем, чтобы напоминание читалось само по
    себе: «task:8f3c…» человеку ничего не говорит.
    """
    if row.note:
        return row.note
    kind, _, key = (row.target_ref or "").partition(":")
    if kind == "task":
        try:
            t = await db.get(Task, uuid.UUID(key))
        except (ValueError, AttributeError):
            t = None
        if t is not None:
            return f"Напоминание: {t.title}"
    return "Напоминание"


async def run_partner_topics(db, now: datetime, bucket: digest.Bucket) -> int:
    """Сказать человеку, что поддержка ответила или ждёт его (docs/BRIDGE.md).

    Разговор с поставщиком программы идёт в панели «Техподдержка», а панель
    открывают, когда о ней вспомнят. Пока «Секретарь» о ней не знал, ответ мог
    пролежать сутки, а обращение в состоянии «ждём вас» — до звонка куратора:
    мяч у клиента, и он об этом не догадывается.

    Поводов три, и на обращение за окно берётся ОДИН — самый весомый: «ждут вас»
    важнее «решено», «решено» важнее просто ответа. Три строки об одном разговоре
    в одной сводке — это тот же поток, только внутри окна.

    Говорим только у клиента (`role='vendor'`): у поддержки обращения живут в
    очереди Координатора, где своя механика сроков, и дублировать её сводкой
    значит звать дважды на одну работу.
    """
    rows = (await db.execute(
        select(PartnerTopic, PartnerSpace)
        .join(PartnerSpace, PartnerSpace.id == PartnerTopic.partner_id)
        .where(PartnerSpace.role == "vendor",
               PartnerTopic.state != "closed",
               PartnerTopic.opened_by_id.is_not(None)))).all()
    sent = 0
    for topic, partner in rows:
        # Ответ считаем по последней ВХОДЯЩЕЙ реплике: свои сообщения человеку
        # пересказывать незачем, а `last_message_at` двигают оба направления.
        answered_at = await db.scalar(
            select(func.max(PartnerMessage.created_at)).where(
                PartnerMessage.topic_id == topic.id, PartnerMessage.direction == "in"))
        state_new = topic.state != (topic.notified_state or "")
        answer_new = bool(answered_at and (topic.notified_at is None
                                           or answered_at > topic.notified_at))
        номер = f"№{topic.external_number} " if topic.external_number else ""
        if state_new and topic.state == "waiting":
            текст = f"{partner.name or partner.code} ждёт вашего ответа: {номер}«{topic.title}»"
        elif state_new and topic.state == "resolved":
            текст = (f"{partner.name or partner.code} считает решённым: {номер}"
                     f"«{topic.title}» — проверьте и закройте")
        elif answer_new:
            текст = f"Ответ поддержки: {номер}«{topic.title}»"
        else:
            continue

        def mark(topic=topic, answered_at=answered_at):
            topic.notified_at = answered_at or now
            topic.notified_state = topic.state

        bucket.add(topic.company_id, topic.opened_by_id,
                   f"partner-topic:{topic.id}", текст, mark=mark)
        sent += 1
    return sent


async def run_digests(db, now: datetime, bucket: digest.Bucket) -> int:
    """Разнести накопленное окнами доставки. Идёт последним в тике.

    Последним не по вкусу: сводка обязана собраться из ВСЕГО, что нашёл
    регламент за проход. Доставь её в середине — и человек получит визы одним
    сообщением, а сроки задач вторым, то есть тот же поток, только из двух труб.
    """
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": LOCK_NAMESPACE, "key": DIGEST_LOCK_KEY})
    if not got:
        return 0
    return await digest.deliver(db, now, bucket)


async def tick() -> dict[str, int]:
    """Один проход регламента. Ошибка одной части не отменяет остальные."""
    now = datetime.now(timezone.utc)
    out = {"recurrences": 0, "reminders": 0, "escalations": 0,
           "acquaints": 0, "approvals": 0, "events": 0, "exchange": 0, "break_glass": 0, "project_reconcile": 0,
           "inbound_events": 0, "approval_delivery": 0, "personal": 0,
           "series": 0, "meetings": 0, "partner_topics": 0, "digests": 0}
    # Поводы копятся весь проход и доставляются одним сообщением в конце: сводка
    # окна — это про число сообщений человеку, а не про удобство планировщика.
    bucket = digest.Bucket()
    async with async_session_factory() as db:
        for key, fn in (("recurrences", run_recurrences),
                        ("reminders", run_due_reminders),
                        ("escalations", run_escalations),
                        ("acquaints", run_acquaint_reminders),
                        ("approvals", run_approval_reminders),
                        ("events", run_event_delivery),
                        ("exchange", run_exchange_scans),
                        ("break_glass", run_break_glass_notifications),
                        ("project_reconcile", run_project_reconcile),
                        ("inbound_events", run_inbound_events),
                        ("approval_delivery", run_approval_delivery),
                        ("personal", run_personal_reminders),
                        ("series", run_meeting_series),
                        ("meetings", run_meetings),
                        ("partner_topics", run_partner_topics),
                        ("digests", run_digests)):
            try:
                out[key] = await (fn(db, now, bucket) if key in _WITH_BUCKET
                                  else fn(db, now))
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
