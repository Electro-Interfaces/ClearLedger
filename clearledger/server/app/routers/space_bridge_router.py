"""Разговор между пространствами: приём, лента, отправка.

Не путать с `partner_router.py` — там партнёр в ПРОЦЕССЕ: чужая система
согласует один наш документ по одноразовому праву. Здесь другое: два полноценных
пространства, наше и заказчика, разговаривают друг с другом постоянно.

Три ручки на обе стороны моста (`services/partner_bridge.py`):

* `POST /eco/partner/message` — принять сообщение от другого пространства. Ключ
  интеграции, как у остальных машинных входов; сессии здесь нет.
* `GET  /partner-space/{code}/feed` — прочитать разговор человеку.
* `POST /partner-space/{code}/message` — написать в другое пространство.

У заказчика этим пользуются его сотрудники («написать в техподдержку»), у нас —
оператор поддержки. Код один, потому что и там и там это одно и то же: переписка
двух пространств.
"""
from __future__ import annotations

import base64
import json
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import quote
from typing import Any

from fastapi import (
    APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import (
    assert_company_member, create_access_token, get_company_by_api_key, get_current_user,
    hash_password,
)
from app.database import get_db
from app.models import (
    Company, PartnerAttachment, PartnerMessage, PartnerSpace, PartnerTopic,
    SourceFile, Task, TaskEvent, User, UserCompany,
)
from app.services import file_store, partner_bridge, sso, support_mirror

router = APIRouter(tags=["Пространства-партнёры"])


class OutgoingMessage(BaseModel):
    body: str
    subject_kind: str | None = None
    subject_ref: str | None = None


class GuestVisit(BaseModel):
    """Пропуск, с которым сотрудник партнёра входит в это пространство."""

    token: str
    space: str


class MailReply(BaseModel):
    """Ответ оператора, который надо отправить письмом с ящика пространства."""

    to: str
    subject: str = ""
    body: str
    inbox: str | None = None       # с какого ящика отвечаем; пусто — первый исходящий
    external_id: str | None = None


class SupportReply(BaseModel):
    """Ответ оператора, который Координатор просит доставить в пространство клиента.

    Одна ручка на реплику и на состояние намеренно: заявка часто и отвечает, и
    двигается одним действием оператора, а два вызова на одно действие — это два
    места, где связь может оборваться посередине.
    """

    partner_code: str
    body: str = ""
    author_name: str | None = None
    author_email: str | None = None
    external_id: str | None = None
    # Обращение, в которое отвечаем, и его состояние у нас. Пусто — переписка
    # «обо всём», как было до обращений.
    topic: str | None = None
    state: str | None = None
    number: str | None = None


class NewTopic(BaseModel):
    """Обращение, которое человек открывает в соседнем пространстве."""

    title: str
    body: str
    subject_kind: str | None = None
    subject_ref: str | None = None
    subject_label: str | None = None


class TopicState(BaseModel):
    """Состояние обращения, названное той стороной, которая ведёт по нему работу."""

    topic: str
    state: str | None = None
    number: str | None = None


@router.post("/eco/partner/message")
async def accept_partner_message(
    request: Request,
    x_eco_space: str | None = Header(None, alias="X-Eco-Space"),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять сообщение от другого пространства.

    Отправитель называет себя заголовком `X-Eco-Space` — кодом, под которым он у
    нас заведён. Незнакомого не принимаем: ключ доказывает, что стучится свой, но
    не говорит, чей это разговор, а класть переписку в чужую ленту нельзя.
    """
    payload = await request.json()
    code = (x_eco_space or payload.get("space") or "").strip()
    if not code:
        raise HTTPException(400, "Не указано пространство отправителя (X-Eco-Space)")

    partner = await partner_bridge.get_partner(db, company.id, code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{code}» здесь не заведено")
    if not str(payload.get("body") or "").strip():
        raise HTTPException(400, "Пустое сообщение")

    row, is_new = await partner_bridge.record_incoming(db, company.id, partner, payload)
    # Пришло клиенту — это ответ поддержки, и ему довольно ленты. Пришло НАМ —
    # это обращение, и оно должно встать в очередь оператора рядом со звонками.
    if partner.role == "client" and row.mirror_pending:
        await support_mirror.deliver_pending(db, datetime.now(UTC), message_id=row.id)
    if is_new and row.topic_id is not None:
        await _return_ball(db, company.id, row.topic_id)
    return {"status": "accepted" if is_new else "duplicate", "id": str(row.id)}


async def _topic_tasks(db: AsyncSession, company_id: uuid.UUID, topic: PartnerTopic):
    """Задания, связанные с обращением, — с обеих сторон разговора.

    Связь бывает двух видов, и обе законные. У поддержки задача заводится ПО
    обращению и держит его предметом (`partner_topic:<id>`). У клиента наоборот:
    задание уже есть, и обращение заводится ИЗ его карточки — тогда предмет
    хранит обращение (`subject_kind='task'`). Искать надо оба, иначе мяч
    возвращается только одной стороне.
    """
    refs = [f"partner_topic:{topic.id}"]
    stmt = select(Task).where(Task.company_id == company_id)
    if topic.subject_kind == "task" and topic.subject_ref:
        try:
            return (await db.execute(stmt.where(or_(
                Task.subject_ref.in_(refs),
                Task.id == uuid.UUID(topic.subject_ref))))).scalars().all()
        except (ValueError, TypeError):
            pass
    return (await db.execute(stmt.where(Task.subject_ref.in_(refs)))).scalars().all()


async def _return_ball(db: AsyncSession, company_id: uuid.UUID, topic_id: uuid.UUID) -> None:
    """Ответила та сторона — мяч возвращается нам.

    Задание, отданное в обращение, ждало внешних (`waiting_for`), и пока мяч там,
    оно не попадает в «На мне». Ответ пришёл — значит ждать больше нечего, и
    исполнитель должен увидеть работу у себя, а не искать её в «Ждём внешних».
    Событие в ленте задания обязательно: иначе непонятно, отчего оно вернулось.
    """
    topic = await db.get(PartnerTopic, topic_id)
    if topic is None:
        return
    changed = False
    for task in await _topic_tasks(db, company_id, topic):
        if task.waiting_for != "external":
            continue
        task.waiting_for = None
        db.add(TaskEvent(task_id=task.id, kind="external_stage", user_id=None,
                         actor_name="Обращение", to_value="ответ получен"))
        changed = True
    if changed:
        await db.commit()


@router.post("/eco/partner/topic-state")
async def accept_topic_state(
    payload: TopicState,
    x_eco_space: str | None = Header(None, alias="X-Eco-Space"),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Состояние обращения на стороне соседа: «принято», «в работе», «решено».

    Отдельно от реплики, потому что это не разговор: человек этих строк не писал,
    и в ленте им не место. Неизвестное обращение — не ошибка настройки, а
    рассинхрон: сообщение могло не дойти, а состояние дойти. Отвечаем честно,
    чтобы у звавшего это было видно, но своей записи не заводим.
    """
    code = (x_eco_space or "").strip()
    if not code:
        raise HTTPException(400, "Не указано пространство отправителя (X-Eco-Space)")
    partner = await partner_bridge.get_partner(db, company.id, code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{code}» здесь не заведено")

    topic = await partner_bridge.apply_state(
        db, partner, payload.topic.strip(), state=payload.state, number=payload.number)
    if topic is None:
        raise HTTPException(404, "Обращение с таким кодом здесь не заведено")
    return {"status": "applied", "state": topic.state}


@router.post("/eco/partner/outgoing")
async def support_reply(
    payload: SupportReply,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ответ поддержки — в пространство клиента.

    Обращение клиента доезжает до очереди Координатора зеркалом, и отвечает
    оператор там же, где отвечает на звонки и письма. Но связь с чужим
    пространством — адрес, ключ и лента — живёт в Ядре, и второй такой связи у
    Координатора нет и заводить её незачем: он просит доставить, Ядро доставляет.

    Зовут отсюда очередью с ретраями, поэтому `external_id` обязателен по смыслу:
    без него повтор положит клиенту ту же реплику второй раз.
    """
    body = payload.body.strip()
    topic_code = (payload.topic or "").strip()
    if not body and not (topic_code and (payload.state or payload.number)):
        raise HTTPException(400, "Пустое сообщение")
    partner = await partner_bridge.get_partner(db, company.id, payload.partner_code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{payload.partner_code}» здесь не заведено")

    self_code = (await db.execute(
        select(Company.slug).where(Company.id == company.id))).scalar_one()

    topic = None
    if topic_code:
        topic = await partner_bridge.apply_state(
            db, partner, topic_code, state=payload.state, number=payload.number)
        if topic is None:
            raise HTTPException(404, "Обращение с таким кодом здесь не заведено")

    if body:
        row = await partner_bridge.send(
            db, company.id, partner, self_code=self_code, body=body,
            author_email=payload.author_email, author_name=payload.author_name,
            external_id=payload.external_id, topic=topic,
        )
        # Недоставленное — не отказ приёма: реплика записана в ленте, и повтор её не
        # продублирует. Но звавшему говорим правду, чтобы очередь попробовала снова.
        if row.delivery_error:
            raise HTTPException(502, row.delivery_error)
        # Состояние вдогонку репликой не уедет — оно едет своим путём, и делать это
        # надо ПОСЛЕ сообщения: иначе клиент увидит «решено» раньше, чем ответ.
        if topic is not None and payload.state:
            error = await partner_bridge.send_state(partner, self_code, topic)
            if error:
                raise HTTPException(502, error)
        return {"status": "sent", "id": str(row.id)}

    error = await partner_bridge.send_state(partner, self_code, topic)
    if error:
        raise HTTPException(502, error)
    return {"status": "state", "state": topic.state}


def _uuid_or_400(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(400, "Неверный идентификатор")


async def _partner_for_user(
    db: AsyncSession, company_id: str, code: str, user: User,
) -> tuple[uuid.UUID, PartnerSpace]:
    cid = await assert_company_member(company_id, user, db)
    partner = await partner_bridge.get_partner(db, cid, code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{code}» не заведено")
    return cid, partner


@router.get("/partner-space/spaces")
async def partner_spaces(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """С какими пространствами связано это: кто они нам и включена ли связь."""
    cid = await assert_company_member(company_id, user, db)
    res = await db.execute(select(PartnerSpace).where(
        PartnerSpace.company_id == cid).order_by(PartnerSpace.name))
    return {"items": [{
        "code": p.code, "name": p.name or p.code, "role": p.role,
        "baseUrl": p.base_url, "isActive": p.is_active,
        # Ключ не показываем и показывать не будем — только то, включена ли связь.
        "linked": bool(p.base_url and partner_bridge.partner_key(p)),
        "lastSeenAt": p.last_seen_at.isoformat() if p.last_seen_at else None,
    } for p in res.scalars().all()]}


def _partner_view(partner: PartnerSpace) -> dict[str, Any]:
    return {"code": partner.code, "name": partner.name or partner.code,
            "role": partner.role,
            "linked": bool(partner.base_url and partner_bridge.partner_key(partner))}


@router.get("/partner-space/{code}/feed")
async def partner_feed(
    code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Переписка с этим пространством."""
    cid, partner = await _partner_for_user(db, company_id, code, user)
    return {
        "partner": _partner_view(partner),
        "messages": await partner_bridge.feed(db, cid, partner),
    }


@router.get("/partner-space/topics")
async def all_topics(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Все обращения компании — с кем бы ни шёл разговор.

    Ручка по коду партнёра требует знать код, а спрашивающий («что с моим
    обращением?») его не знает и знать не должен: у клиента поставщик один, у
    поддержки клиентов много, и в обоих случаях человеку нужен список, а не
    навигация по реестру. Отсюда общий список — им же пользуется агент
    пространства.
    """
    cid = await assert_company_member(company_id, user, db)
    res = await db.execute(
        select(PartnerTopic, PartnerSpace.code, PartnerSpace.name, PartnerSpace.role)
        .join(PartnerSpace, PartnerSpace.id == PartnerTopic.partner_id)
        .where(PartnerTopic.company_id == cid)
        .order_by(PartnerTopic.last_message_at.desc().nullslast())
        .limit(200))
    return {"items": [{
        "code": topic.code, "title": topic.title, "state": topic.state,
        "number": topic.external_number, "subjectLabel": topic.subject_label,
        "partnerCode": partner_code, "partnerName": partner_name or partner_code,
        # `vendor` — разговор с нашим поставщиком программы, `client` — с тем,
        # кого обслуживаем мы. Слова в ответе человеку от этого разные.
        "partnerRole": role,
        "createdAt": topic.created_at.isoformat() if topic.created_at else None,
        "lastMessageAt": (topic.last_message_at.isoformat()
                          if topic.last_message_at else None),
    } for topic, partner_code, partner_name, role in res.all()]}


@router.get("/partner-space/subject-topics")
async def subject_topics(
    kind: str = Query(...),
    ref: str = Query(...),
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что уже спрашивали по этому предмету — во всех соседних пространствах.

    Карточка должна показывать это рядом с кнопкой «Спросить поддержку»: иначе
    один и тот же документ уезжает третьим обращением, а первые два висят
    открытыми у оператора.
    """
    cid = await assert_company_member(company_id, user, db)
    res = await db.execute(
        select(PartnerTopic, PartnerSpace.code, PartnerSpace.name)
        .join(PartnerSpace, PartnerSpace.id == PartnerTopic.partner_id)
        .where(PartnerTopic.company_id == cid,
               PartnerTopic.subject_kind == kind, PartnerTopic.subject_ref == ref)
        .order_by(PartnerTopic.last_message_at.desc().nullslast())
        .limit(20))
    return {"items": [{
        "code": topic.code, "title": topic.title, "state": topic.state,
        "number": topic.external_number,
        "partnerCode": partner_code, "partnerName": partner_name or partner_code,
        "lastMessageAt": (topic.last_message_at.isoformat()
                          if topic.last_message_at else None),
    } for topic, partner_code, partner_name in res.all()]}


@router.get("/partner-space/{code}/topics")
async def partner_topics(
    code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Обращения к этому пространству: о чём спрашивали и чем кончилось.

    `general` — сколько сообщений в переписке «обо всём», которая велась до
    обращений. Ноль — старой ленты нет, и показывать её пунктом незачем.
    """
    cid, partner = await _partner_for_user(db, company_id, code, user)
    general = await db.scalar(select(func.count()).select_from(PartnerMessage).where(
        PartnerMessage.company_id == cid, PartnerMessage.partner_id == partner.id,
        PartnerMessage.topic_id.is_(None)))
    return {
        "partner": _partner_view(partner),
        "items": await partner_bridge.topics(db, cid, partner),
        "general": int(general or 0),
    }


@router.post("/partner-space/{code}/topics")
async def partner_topic_open(
    code: str,
    payload: NewTopic,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Открыть обращение: заголовок, первое сообщение и, если есть, предмет.

    Код обращения присваиваем мы как зачинатель, и он же уезжает соседу — по нему
    ответ вернётся в эту ветку, а не заведёт у нас вторую.
    """
    cid, partner = await _partner_for_user(db, company_id, code, user)
    title = payload.title.strip()
    body = payload.body.strip()
    if not title or not body:
        raise HTTPException(400, "Нужны тема обращения и текст")

    topic = await partner_bridge.ensure_topic(
        db, cid, partner, uuid.uuid4().hex, title=title,
        subject_kind=payload.subject_kind, subject_ref=payload.subject_ref,
        # Предмет соседу называется словами, а не идентификатором: данные за ним
        # мостом не ходят (docs/BRIDGE.md §4.2).
        subject_label=(payload.subject_label or "").strip()[:300] or None,
        opened_by_id=user.id)
    # Обращение из карточки задания — это и есть «передать его поддержке»: мяч
    # уходит наружу, и задание перестаёт числиться на своём исполнителе, пока
    # ответа нет. Возврат мяча сделает приёмник моста, когда придёт ответ.
    if payload.subject_kind == "task" and payload.subject_ref:
        try:
            task = await db.get(Task, uuid.UUID(payload.subject_ref))
        except (ValueError, TypeError):
            task = None
        if task is not None and task.company_id == cid:
            task.waiting_for = "external"
            db.add(TaskEvent(task_id=task.id, kind="external_stage", user_id=user.id,
                             actor_name=user.name or user.email,
                             to_value=f"передано в {partner.name or partner.code}",
                             note=title[:2000]))

    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    row = await partner_bridge.send(
        db, cid, partner, self_code=self_code, body=body,
        author_email=user.email, author_name=user.name or user.email,
        subject_kind=payload.subject_kind, subject_ref=payload.subject_ref,
        topic=topic,
    )
    return {"code": topic.code, "state": topic.state,
            "delivered": row.delivered_at is not None, "error": row.delivery_error}


async def _topic_for_user(
    db: AsyncSession, company_id: str, code: str, topic_code: str, user: User,
):
    cid, partner = await _partner_for_user(db, company_id, code, user)
    topic = (await db.execute(select(PartnerTopic).where(
        PartnerTopic.partner_id == partner.id,
        PartnerTopic.code == topic_code))).scalars().first()
    if topic is None:
        raise HTTPException(404, "Обращение не найдено")
    return cid, partner, topic


@router.get("/partner-space/{code}/topics/{topic_code}/feed")
async def partner_topic_feed(
    code: str,
    topic_code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Переписка внутри обращения."""
    cid, partner, topic = await _topic_for_user(db, company_id, code, topic_code, user)
    return {
        "partner": _partner_view(partner),
        "topic": {"code": topic.code, "title": topic.title, "state": topic.state,
                  "number": topic.external_number, "subjectLabel": topic.subject_label},
        "messages": await partner_bridge.feed(db, cid, partner, topic=topic),
    }


@router.post("/partner-space/{code}/topics/{topic_code}/message")
async def partner_topic_send(
    code: str,
    topic_code: str,
    payload: OutgoingMessage,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Реплика в обращение — от своего имени, в ту же ветку."""
    cid, partner, topic = await _topic_for_user(db, company_id, code, topic_code, user)
    if not payload.body.strip():
        raise HTTPException(400, "Пустое сообщение")
    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    row = await partner_bridge.send(
        db, cid, partner, self_code=self_code, body=payload.body,
        author_email=user.email, author_name=user.name or user.email,
        topic=topic,
    )
    return {"id": str(row.id), "delivered": row.delivered_at is not None,
            "error": row.delivery_error}


@router.post("/partner-space/{code}/message")
async def partner_send(
    code: str,
    payload: OutgoingMessage,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Написать в другое пространство от своего имени."""
    cid, partner = await _partner_for_user(db, company_id, code, user)
    if not payload.body.strip():
        raise HTTPException(400, "Пустое сообщение")
    # Свой код пространства — им получатель нас узнаёт. Берём slug компании,
    # он же код стека: другого имени у пространства нет.
    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    row = await partner_bridge.send(
        db, cid, partner, self_code=self_code, body=payload.body,
        author_email=user.email, author_name=user.name or user.email,
        subject_kind=payload.subject_kind, subject_ref=payload.subject_ref,
    )
    return {
        "id": str(row.id),
        "delivered": row.delivered_at is not None,
        # Ошибку доставки отдаём человеку сразу: он должен знать, что сообщение
        # осталось у нас, а не думать, что оно ушло.
        "error": row.delivery_error,
    }


@router.post("/partner-space/{code}/topics/{topic_code}/attach")
async def partner_topic_attach(
    code: str,
    topic_code: str,
    company_id: str = Query(...),
    note: str = Query(""),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Приложить файл к обращению: скриншот, выгрузка, акт.

    Файл уезжает целиком, а не ссылкой: ссылка в чужое пространство не откроется,
    и «доступ по ссылке» был бы дыркой в изоляции. Реплика создаётся всегда —
    вложение без строки в ленте выглядит как пропавшее сообщение.
    """
    cid, partner, topic = await _topic_for_user(db, company_id, code, topic_code, user)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    if len(content) > partner_bridge.MAX_FILE_BYTES:
        raise HTTPException(413, "Файл больше 10 МБ — так мост не возит")

    stored = file_store.put(db, cid, content,
                            file_name=file.filename or "файл",
                            mime=file.content_type or "application/octet-stream")
    await db.flush()
    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    row = await partner_bridge.send(
        db, cid, partner, self_code=self_code,
        body=(note.strip() or f"Файл: {stored.file_name}"),
        author_email=user.email, author_name=user.name or user.email, topic=topic,
        files=[{
            "id": str(stored.id), "name": stored.file_name, "mime": stored.mime_type,
            "contentBase64": base64.b64encode(content).decode(),
        }])
    db.add(PartnerAttachment(company_id=cid, message_id=row.id, file_id=stored.id,
                             external_id=str(stored.id)))
    await db.commit()
    return {"id": str(row.id), "name": stored.file_name, "size": stored.size,
            "delivered": row.delivered_at is not None, "error": row.delivery_error}


@router.get("/partner-space/attachments/{attachment_id}")
async def partner_attachment(
    attachment_id: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отдать вложение реплики. Только своей компании: файл пришёл в её разговор."""
    cid = await assert_company_member(company_id, user, db)
    link = await db.get(PartnerAttachment, _uuid_or_400(attachment_id))
    if link is None or link.company_id != cid:
        raise HTTPException(404, "Вложение не найдено")
    stored = await db.get(SourceFile, link.file_id)
    if stored is None:
        raise HTTPException(404, "Файл не найден")
    try:
        data = file_store.read(stored)
    except OSError:
        raise HTTPException(410, "Файл больше не хранится")
    return Response(content=data, media_type=stored.mime_type or "application/octet-stream",
                    headers={"Content-Disposition":
                             f'attachment; filename="{quote(stored.file_name)}"'})


@router.post("/partner-space/{code}/visit")
async def partner_visit(
    code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Выписать себе пропуск в пространство клиента.

    Инженер работает у клиента своей учётной записью, а не заведённой в его
    контуре: учёток столько же, сколько клиентов, и каждая живёт своей жизнью —
    человек ушёл, а доступ остался. Пропуск живёт две минуты и выписывается на
    одно пространство: открытый к одному клиенту, он не откроет дверь к другому.
    """
    cid, partner = await _partner_for_user(db, company_id, code, user)
    # Пропуск выписывают своим. Внешний участник допущен в НАШЕ пространство, а не
    # в пространство нашего клиента: там он никто, и открывать ему дверь нечем.
    membership = await db.get(UserCompany, (user.id, cid))
    if membership is not None and membership.party_type == "partner":
        raise HTTPException(403, "Пропуск выписывается сотрудникам пространства")
    if not partner.is_active:
        raise HTTPException(409, "Связь с этим пространством выключена")
    if not partner.base_url:
        raise HTTPException(409, "У пространства не задан адрес")

    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    token = sso.sign_visit_token(user=user, space_code=partner.code, self_code=self_code)
    if not token:
        raise HTTPException(503, "Единый вход не настроен: нет ключа подписи")

    # Кто и куда ходил — вопрос, который задаст заказчик, и ответ на него должен
    # быть у нас, а не только у него.
    await log_audit(db, actor=user, company_id=cid, action="partner.visit",
                    target=partner.code)
    await db.commit()
    base = partner.base_url.rstrip("/")
    return {
        "url": f"{base}{partner_bridge.VISIT_PATH}#token={token}&space={self_code}",
        "space": partner.code,
        "name": partner.name or partner.code,
    }


@router.post("/eco/partner/visit")
async def accept_visit(
    payload: GuestVisit,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Впустить сотрудника партнёра по его пропуску.

    Сессии здесь нет и быть не может — человек как раз за ней и пришёл. Доверие
    держится на двух вещах: пропуск подписан ключом того пространства, которое у
    нас заведено, и заведено оно нами же, с ролью поставщика. Выключили запись —
    вход закрылся, и заводить у себя учётки для этого не нужно.

    Учётка гостя всё же появляется — иначе его действия некому приписать в
    журнале. Но заводит её вход, а не человек руками, и помечена она как инженер
    платформы: в составе пространства такой участник виден отдельной группой.
    """
    code = payload.space.strip()
    if not code:
        raise HTTPException(400, "Не указано пространство, выдавшее пропуск")

    partner = (await db.execute(select(PartnerSpace).where(
        PartnerSpace.code == code, PartnerSpace.role == "vendor",
        PartnerSpace.is_active.is_(True),
    ))).scalars().first()
    if partner is None:
        raise HTTPException(403, f"Пространство «{code}» здесь не заведено как поставщик")

    company = await db.get(Company, partner.company_id)
    keys = await partner_bridge.partner_jwks(partner)
    claims = _verify_visit(payload.token, keys, audience=f"space:{company.slug}")

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "В пропуске нет адреса сотрудника")

    guest = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if guest is None:
        # Пароля у такой учётки нет по смыслу: входят по пропуску, а не паролем.
        # Случайный хеш вместо пустого — чтобы «войти никак» не значило «войти без пароля».
        guest = User(email=email, name=claims.get("name") or email, role="user",
                     password_hash=hash_password(secrets.token_urlsafe(24)))
        db.add(guest)
        await db.flush()

    membership = await db.get(UserCompany, (guest.id, company.id))
    if membership is None:
        membership = UserCompany(user_id=guest.id, company_id=company.id, role="user",
                                 party_type="vendor")
        db.add(membership)
    elif membership.party_type != "vendor":
        # Человека могли завести здесь и руками. Права его при этом не трогаем:
        # что клиент выдал, то и остаётся, — но принадлежность говорим честно.
        membership.party_type = "vendor"

    await log_audit(db, actor=guest, company_id=company.id, action="partner.guest_in",
                    target=partner.code)
    await db.commit()
    return {
        "access_token": create_access_token(str(guest.id), guest.email),
        "token_type": "bearer",
        "company_id": str(company.id),
        "space": company.slug,
        "name": guest.name,
    }


def _verify_visit(token: str, jwks: dict[str, Any], *, audience: str) -> dict[str, Any]:
    """Проверить пропуск публичным ключом выдавшего пространства."""
    from jwt import PyJWTError, decode, get_unverified_header
    from jwt.algorithms import RSAAlgorithm

    try:
        kid = get_unverified_header(token).get("kid")
    except PyJWTError as e:
        raise HTTPException(400, f"Пропуск не читается: {e}") from e
    keys = jwks.get("keys") or []
    # Ключ по kid, а при единственном — он же: `kid` у стеков совпадает по
    # соглашению имени, и упереться в него значило бы не пустить никого.
    jwk = next((k for k in keys if k.get("kid") == kid), keys[0] if len(keys) == 1 else None)
    if jwk is None:
        raise HTTPException(403, "Ключ, которым подписан пропуск, у пространства не найден")
    try:
        return decode(token, RSAAlgorithm.from_jwk(json.dumps(jwk)),
                      algorithms=["RS256"], audience=audience)
    except PyJWTError as e:
        raise HTTPException(403, f"Пропуск отклонён: {e}") from e


@router.post("/eco/support/mail-reply")
async def support_mail_reply(
    payload: MailReply,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Отправить ответ оператора письмом.

    Обращение пришло письмом, и ответ обязан уйти письмом — но почтовые ящики,
    подписи и нити переписки живут в Ядре. Координатор просит отправить, Ядро
    отправляет с того ящика, на который письмо пришло: человек получит ответ там
    же, где писал, а копия ляжет в переписку компании.
    """
    from app.models import MailAccount
    from app.services import mail_send

    to = payload.to.strip()
    body = payload.body.strip()
    if "@" not in to or not body:
        raise HTTPException(400, "Нужен адрес получателя и непустой текст")

    stmt = select(MailAccount).where(
        MailAccount.company_id == company.id,
        MailAccount.is_active.is_(True),
        MailAccount.mode != "in",
    )
    if payload.inbox:
        stmt = stmt.where(MailAccount.address == payload.inbox)
    account = (await db.execute(stmt)).scalars().first()
    if account is None:
        raise HTTPException(409, "В пространстве нет ящика для отправки")

    subject = payload.subject.strip() or "Ответ поддержки"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    result = await mail_send.send_message(
        db, company.id, account_id=account.id, to=[to],
        subject=subject[:300], body=body, author="support")
    if "error" in result:
        # Очередь Координатора повторит: письмо не ушло, и молчать об этом нельзя.
        raise HTTPException(502, str(result["error"]))
    await db.commit()
    return {"status": "sent", "messageId": result.get("messageId")}
