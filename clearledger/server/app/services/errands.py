"""Поручение как активность процесса: маршрут просит работу и ждёт её исхода.

Симметрично согласованию (`approval_requests`). Узел маршрута доходит до «сделать»
— и до сих пор упирался в человека-курьера: тот шёл в «Трек», заводил поручение по
заготовке, ждал его и возвращался нажать кнопку. Работа машины прерывалась
человеком и рвалась ровно там, где он забывал.

Здесь передача становится машинной, но владение не меняется: поручение — сущность
«Трека», и он ничего не знает о стройке. Процесс просит активность («сделай работу
по этой заготовке»), а получает событие исхода.

Две вещи, из-за которых это не сводится к паре вызовов:

1. **Поручение нельзя завести дважды.** Доставка просьбы — at-least-once, повтор
   штатен. Ключ `request_id` и частичный уникальный индекс по открытому поручению
   держат правило «одна просьба — одно поручение» даже при гонке.
2. **Исход нельзя потерять.** Поручение закрывается независимо от того, доступен ли
   сейчас Координатор, поэтому исход сначала фиксируется у себя, а доставляется
   фоновым проходом с ретраями — тем же, что возит исходы кругов виз. Второй
   механизм доставки означал бы вторые ретраи и вторую историю о том, где потерялось.

Автор поручения — служебный участник пространства «Процесс»: работу поручил
маршрут, а не человек, и подставлять живого сотрудника значило бы приписать ему
чужое решение. Откуда пришла работа, видно в примечании поручения.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, Task, TaskTemplate, User, UserCompany
from app.services import process_templates

log = logging.getLogger("clearledger.errands")

SERVICE_EMAIL = "process@space.local"
SERVICE_NAME = "Процесс"


class ErrandError(Exception):
    """Просьба о работе невыполнима — с причиной для журнала событий."""


async def service_actor(db: AsyncSession, company_id: uuid.UUID) -> User:
    """Служебный участник «Процесс» — от его имени маршрут поручает работу.

    Заводится лениво и один раз: пароль случайный и нигде не хранится, войти этой
    учёткой нельзя. Членство в компании нужно затем, что «Трек» проверяет автора
    поручения по пространству, а не по глобальному признаку.
    """
    user = (await db.execute(select(User).where(User.email == SERVICE_EMAIL))).scalar_one_or_none()
    if user is None:
        user = User(
            email=SERVICE_EMAIL, name=SERVICE_NAME, role="user",
            # Хеш заведомо невалидный: это не учётка для входа, а подпись автора.
            password_hash=f"!process-{secrets.token_hex(16)}",
        )
        db.add(user)
        await db.flush()
    if await db.get(UserCompany, (user.id, company_id)) is None:
        db.add(UserCompany(user_id=user.id, company_id=company_id, role="member"))
        await db.flush()
    return user


async def request(db: AsyncSession, company_id: uuid.UUID, request_id: str,
                  data: dict[str, Any]) -> ApprovalRequest:
    """Развернуть поручение по заготовке и запомнить, что процесс ждёт его исхода."""
    process_id = data.get("process_id") or data.get("processId") or data.get("ticket_id")
    if not process_id:
        raise ErrandError("В просьбе не указан процесс")

    template = await _template(db, company_id, data)
    actor = await service_actor(db, company_id)
    # Откуда работа взялась — пишем словами просителя, если он их сказал. Работу
    # заводит не только маршрут: управляющий делает это с рабочего места, и
    # «поручено маршрутом» в её истории было бы неправдой.
    source = str(data.get("source_note") or data.get("sourceNote") or "").strip()[:200]
    note = source or f"поручено маршрутом (процесс {process_id})"
    task, _ = await process_templates.launch_task(
        db, company_id, template, actor,
        title=(data.get("title") or None),
        responsible_id=_uuid_or_none(data.get("assignee_id") or data.get("assigneeId")),
        object_id=(data.get("object_id") or data.get("objectId") or None),
        source_ref=str(process_id),
        source_note=note,
    )

    row = ApprovalRequest(
        company_id=company_id,
        request_id=str(request_id)[:120],
        kind="errand",
        process_id=str(process_id)[:64],
        branch_id=(str(data.get("branch_id") or data.get("branchId"))[:64]
                   if data.get("branch_id") or data.get("branchId") else None),
        task_id=task.id,
        round=0,
        # Глаголы, которыми процесс пойдёт дальше. Не задан — маршрут просил только
        # сделать работу, а идти дальше собирается сам: это законный случай.
        on_approved=(data.get("on_done") or data.get("onDone") or "").strip()[:120] or None,
        on_rejected=(data.get("on_cancelled") or data.get("onCancelled") or "").strip()[:120] or None,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Повтор просьбы или живое поручение по этому же процессу — не ошибка
        # отправителя, а штатная доставка at-least-once.
        await db.rollback()
        raise ErrandError("Поручение по этой просьбе уже заведено") from exc
    log.info("Поручение %s заведено маршрутом процесса %s", task.number, process_id)
    return row


async def _template(db: AsyncSession, company_id: uuid.UUID,
                    data: dict[str, Any]) -> TaskTemplate:
    """Заготовка поручения: по идентификатору или по имени.

    Имя допускается намеренно: маршруты пишут люди, и ссылаться на UUID заготовки в
    графе неудобно — при пересборке пространства он меняется, а имя остаётся.
    """
    raw_id = _uuid_or_none(data.get("template_id") or data.get("templateId"))
    if raw_id is not None:
        tpl = await db.get(TaskTemplate, raw_id)
        if tpl is not None and tpl.company_id == company_id and not tpl.doc_kind_id:
            return tpl
        raise ErrandError("Заготовка поручения не найдена")

    name = str(data.get("template") or data.get("templateName") or "").strip()
    if not name:
        raise ErrandError("В просьбе не названа заготовка поручения")
    tpl = (await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == company_id,
        TaskTemplate.doc_kind_id.is_(None),
        TaskTemplate.name == name))).scalars().first()
    if tpl is None:
        raise ErrandError(f"Заготовка поручения «{name}» не заведена")
    return tpl


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


async def close(db: AsyncSession, task: Task, status: str) -> ApprovalRequest | None:
    """Поручение закрыто — зафиксировать исход для процесса, который его ждёт.

    Отметка ставится здесь, внутри закрывающей транзакции: доставка пойдёт фоном,
    но потерять исход нельзя — работа уже сделана, второй раз её не сделают.
    """
    row = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.task_id == task.id,
        ApprovalRequest.kind == "errand",
        ApprovalRequest.outcome.is_(None)))).scalars().first()
    if row is None:
        return None
    from datetime import datetime, timezone

    row.outcome = "done" if status == "done" else "cancelled"
    row.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return row
