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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, cast, or_, select, text

from app.auth import resolve_member_modules
from app.database import async_session_factory
from app.models import (
    DocAcquaint, DocApproval, DocBreakGlassAccess, DocCard, DocExchangeTarget,
    Task, TaskChecklistItem, TaskEvent, TaskRecurrence, TaskTemplate, TaskType,
    User, UserCompany,
)
from app.services import (
    doc_approvals, doc_exchange, process_templates, space_events, task_mail,
    work_state)

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
               or_(Task.waiting_for.is_(None), Task.waiting_for != "external"),
               # Личная запись почтой не напоминает: человек завёл её себе, а
               # письмо о ней уходит на рабочий ящик и делает личное видимым
               # там, где человек его не заводил. Свой срок — своим
               # напоминанием (`PersonalReminder`).
               Task.visibility != "personal"))).all()
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
               Task.assignee_id.is_not(None),
               # Эскалация личной записи сообщила бы старшему о её
               # существовании — ровно то, чего слово «личное» обещает не
               # делать. Тип с реакцией у личной задачи взяться может: человек
               # поднял в личное готовый шаблон.
               Task.visibility != "personal"))).all()
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


async def run_acquaint_reminders(db, now: datetime) -> int:
    """Напомнить о документе за сутки до срока и затем не чаще раза в сутки."""
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
               or_(DocAcquaint.reminded_at.is_(None),
                   DocAcquaint.reminded_at <= now - timedelta(days=1)),
               or_(DocAcquaint.reminder_attempted_at.is_(None),
                   DocAcquaint.reminder_attempted_at <= now - timedelta(hours=1))))).all()
    sent = 0
    for acquaint, doc, user, membership in rows:
        if not user.is_superadmin and membership.role != "admin":
            modules = await resolve_member_modules(membership, db)
            if (modules is not None and "docs" not in modules and not any(
                    key.startswith("docs:") for key in modules)):
                continue
        if not user.email:
            continue
        overdue = acquaint.due_at < now
        number = doc.reg_number or "без номера"
        ok, error = await task_mail.send_notice_checked(
            [user.email],
            f"{'Просрочено ознакомление' if overdue else 'Нужно ознакомиться'}: {doc.title}",
            f"Документ {number}\nСрок: {acquaint.due_at.strftime('%d.%m.%Y')}\n\n"
            "Откройте «Трек» → «На мне» → «Ознакомиться».")
        acquaint.reminder_attempted_at = now
        acquaint.reminder_error = error
        if ok:
            acquaint.reminded_at = now
            sent += 1
    return sent


async def run_approval_reminders(db, now: datetime) -> int:
    """Напомнить согласующему о визе за сутки до срока и затем раз в сутки.

    Срок визы хранился с самого начала и не делал ничего: планировщик круг не
    читал, а `sla_hours` доезжал только до отчёта. Согласование останавливалось
    молча — ровно там, где документ ждёт одного человека.

    Заместителю пишем тем же письмом. Виза за другого запрещена, но отпуск не
    должен держать документ: заместитель визирует от своего имени, и узнать об
    ожидании он обязан не позже того, кого замещает.
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
                   DocApproval.reminded_at <= now - timedelta(days=1)),
               or_(DocApproval.reminder_attempted_at.is_(None),
                   DocApproval.reminder_attempted_at
                   <= now - timedelta(hours=1))))).all()
    sent = 0
    for approval, doc, user, membership in rows:
        if not user.is_superadmin and membership.role != "admin":
            modules = await resolve_member_modules(membership, db)
            if (modules is not None and "docs" not in modules and not any(
                    key.startswith("docs:") for key in modules)):
                continue
        if not user.email:
            continue
        addresses = [user.email]
        for deputy_id in await doc_approvals.active_deputy_for(
                db, approval.company_id, user.id):
            deputy_mail = await db.scalar(
                select(User.email).where(User.id == deputy_id))
            if deputy_mail and deputy_mail not in addresses:
                addresses.append(deputy_mail)
        overdue = approval.due_at < now
        number = doc.reg_number or "без номера"
        ok, error = await task_mail.send_notice_checked(
            addresses,
            f"{'Просрочена виза' if overdue else 'Ожидает визы'}: {doc.title}",
            f"Документ {number}\nШаг: {approval.step_name or 'согласование'}\n"
            f"Срок: {approval.due_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Откройте «Трек» → «На мне» → «Визы».")
        approval.reminder_attempted_at = now
        approval.reminder_error = error
        if ok:
            approval.reminded_at = now
            sent += 1
    return sent


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
            await notify.notify_person(db, row.company_id, user,
                                       await _reminder_text(db, row))
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


async def tick() -> dict[str, int]:
    """Один проход регламента. Ошибка одной части не отменяет остальные."""
    now = datetime.now(timezone.utc)
    out = {"recurrences": 0, "reminders": 0, "escalations": 0,
           "acquaints": 0, "approvals": 0, "events": 0, "exchange": 0, "break_glass": 0, "project_reconcile": 0,
           "inbound_events": 0, "approval_delivery": 0, "personal": 0}
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
                        ("personal", run_personal_reminders)):
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
