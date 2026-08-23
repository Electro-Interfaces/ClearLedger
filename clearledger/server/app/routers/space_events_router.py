"""Подписки на исходящие события пространства и витрина очереди доставки.

Шина уже умеет издавать и доставлять (`services/space_events.py`), но завести
подписку было нечем: строки в `eco_event_subscriptions` пришлось бы вписывать в
базу руками. Здесь — управление ими и ответ на вопрос «почему подписчику не
дошло», без которого очередь остаётся чёрным ящиком.

Секрет генерирует сервер и отдаёт ОДИН раз при создании — как именной входящий
ключ. Принимать секрет от клиента значило бы разрешить ему слабый: подписью
защищён поток данных о документах компании, и её стойкость не должна зависеть от
того, что подписчик придумал.

Права — администратор компании. Подписка это выдача потока данных о документах
наружу, и права на сам продукт для такого мало: читать документы в «Треке» и
раздавать их поток чужой системе — решения разного веса.
"""
from __future__ import annotations

import base64
import secrets as _secrets
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import App, EventSubscription, OutboxEvent, User, UserCompany
from app.services import space_events

router = APIRouter(prefix="/eco", tags=["Экосистема: исходящие события"])

# Издаются пока только события «Трека» — продуктовый гейт по нему же.
_PRODUCT = "docs"
_OUTBOX_STATUSES = ("pending", "done", "failed", "expired", "cancelled")
_QUEUE_LIMIT = 500


# ── Помощники ────────────────────────────────────────────────────────────────


def _uuid_or_400(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неверный {field}")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _admin(company_ref: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Компания, продукт и права администратора — одной проверкой на все ручки."""
    cid = await assert_company_product(company_ref, user, db, _PRODUCT)
    if user.is_superadmin:
        return cid
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Подписки на события пространства ведёт администратор компании")
    return cid


def _check_types(types: list[str]) -> list[str]:
    """Сверка с каталогом. Неизвестный тип — отказ, а не тихий отсев.

    Отфильтровать молча значило бы завести подписку, которая никогда не сработает,
    и оставить человека в уверенности, что он подписался.
    """
    if not types:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Укажите хотя бы один тип события")
    unknown = [t for t in types if t not in space_events.EVENT_TYPES]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Система не издаёт такие события: {', '.join(unknown)}")
    return list(dict.fromkeys(types))


def _check_shape(kind: str, app_code: str | None, url: str | None,
                 has_secret: bool) -> None:
    """Те же правила, что в CHECK на таблице, но словами.

    Повтор намеренный: из базы прилетит IntegrityError и 500-я, из которой
    человек не поймёт, чего именно не хватило.
    """
    if kind == "app":
        if not app_code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Для приложения пространства укажите его код")
        if url:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Адрес приложения знает реестр — здесь он не задаётся")
        return
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Нужен адрес вида http://… или https://…")
    if not has_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Внешнему подписчику нужен секрет: подписывать нечем")


async def _check_target(db: AsyncSession, kind: str, app_code: str | None,
                        url: str | None, has_secret: bool) -> None:
    _check_shape(kind, app_code, url, has_secret)
    if kind != "app":
        return
    known = (await db.execute(
        select(App.id).where(App.code == app_code))).scalar_one_or_none()
    if known is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Приложения «{app_code}» нет в реестре экосистемы")


def _new_secret() -> tuple[str, str, str]:
    """Секрет, шифротекст для хранения и хвост для опознания.

    Формат `whsec_<24 байта в base64>` — чужой, standard-webhooks: подписчик
    кладёт строку в готовую библиотеку как есть, а `sign()` берёт из неё те же
    байты. Свой формат означал бы разбор ключа руками на той стороне.
    """
    raw = "whsec_" + base64.b64encode(_secrets.token_bytes(24)).decode()
    enc = space_events.encrypt_secret(raw)
    if enc is None:
        # Открытым секрет не ляжет: это ровно та доктрина, что записана у
        # реквизитов источников, и нарушать её в собственной шине незачем.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Ключ шифрования стека не задан — хранить секрет подписки негде")
    return raw, enc, raw[-6:]


async def _assert_label_free(db: AsyncSession, cid: uuid.UUID, label: str,
                             exclude: uuid.UUID | None = None) -> None:
    stmt = select(EventSubscription.id).where(
        EventSubscription.company_id == cid, EventSubscription.label == label)
    if exclude is not None:
        stmt = stmt.where(EventSubscription.id != exclude)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Подписка с таким названием уже есть")


def _sub_out(s: EventSubscription) -> dict[str, Any]:
    """Наружу — всё, кроме секрета: он ушёл подписчику при создании и второй раз
    не показывается никому, включая администратора. Для опознания есть хвост."""
    return {
        "id": str(s.id), "label": s.label, "target_kind": s.target_kind,
        "app_code": s.app_code, "path": s.path, "url": s.url,
        "secret_hint": s.secret_hint,
        "event_types": list(s.event_types or []),
        "stop_day_count": s.stop_day_count, "enabled": s.enabled,
        "last_delivery_at": _iso(s.last_delivery_at),
        "last_status": s.last_status, "last_error": s.last_error,
        "failure_streak": s.failure_streak,
        "failing_since": _iso(s.failing_since),
        "disabled_reason": s.disabled_reason,
        "disabled_at": _iso(s.disabled_at),
        "created_at": _iso(s.created_at),
    }


async def _sub_or_404(db: AsyncSession, cid: uuid.UUID,
                      sub_id: str) -> EventSubscription:
    row = (await db.execute(select(EventSubscription).where(
        EventSubscription.company_id == cid,
        EventSubscription.id == _uuid_or_400(sub_id, "sub_id"),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подписка не найдена")
    return row


# ── Подписки ─────────────────────────────────────────────────────────────────


class SubscriptionIn(BaseModel):
    company_id: str
    label: str = Field(..., min_length=2, max_length=200)
    target_kind: str = Field("app", pattern="^(app|url)$")
    app_code: str | None = Field(None, max_length=40)
    path: str = Field("/api/v1/eco/events", min_length=1, max_length=200)
    url: str | None = Field(None, max_length=500)
    event_types: list[str] = Field(..., min_length=1)
    stop_day_count: int = Field(30, ge=1, le=999)
    enabled: bool = True


class SubscriptionPatch(BaseModel):
    company_id: str
    label: str | None = Field(None, min_length=2, max_length=200)
    target_kind: str | None = Field(None, pattern="^(app|url)$")
    app_code: str | None = Field(None, max_length=40)
    path: str | None = Field(None, min_length=1, max_length=200)
    url: str | None = Field(None, max_length=500)
    event_types: list[str] | None = None
    stop_day_count: int | None = Field(None, ge=1, le=999)
    enabled: bool | None = None


@router.get("/subscriptions/spec")
async def delivery_spec(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Как подписчику убедиться, что событие прислали мы.

    Алгоритм отдаёт система, а не письмо интегратору: письмо разойдётся с кодом
    в первый же день, когда поменяется код.
    """
    sample = space_events.envelope(
        uuid.UUID("00000000-0000-0000-0000-000000000001"), "doc.registered",
        "<идентификатор документа>", datetime(2026, 1, 1, tzinfo=timezone.utc),
        {"doc": {"id": "…", "kindCode": "doc_in", "regNumber": "ВХ-000123",
                 "status": "registered"},
         "actor": {"kind": "user", "id": "…", "name": "…"}})
    demo = "whsec_" + base64.b64encode(b"example-secret--").decode()
    return {
        "envelope": "CloudEvents 1.0 (JSON)",
        "signature": {
            "scheme": "standard-webhooks",
            "headers": ["webhook-id", "webhook-timestamp", "webhook-signature"],
            "algorithm": "HMAC-SHA256, base64",
            "signed_content": "{webhook-id}.{webhook-timestamp}.{тело запроса}",
            "header_format": "v1,<подпись>",
            "secret_format": "whsec_<24 случайных байта в base64>",
            "example_signature": space_events.sign(
                demo, "evt_example", 1767225600, "{}"),
        },
        "event_types": [{"type": t, "title": name}
                        for t, name in space_events.EVENT_TYPES.items()],
        "example_body": sample,
        "notes": [
            "Подпись считается по тем байтам, что пришли: пересобранный на вашей "
            "стороне JSON даст другую подпись.",
            "`webhook-id` стабилен на все попытки — по нему отсеивайте повтор.",
            "Метка времени в секундах; событие старше 5 минут считайте "
            "подозрительным.",
            f"2xx — доставлено. Другой код или таймаут "
            f"{int(space_events.DELIVERY_TIMEOUT)} с — повтор с растущей паузой, "
            f"до {space_events.MAX_ATTEMPTS} попыток.",
            "Событие старше срока ожидания подписки не доставляется, а подписка, "
            "молчащая дольше этого срока, выключается.",
        ],
    }


@router.get("/subscriptions")
async def list_subscriptions(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Подписки компании и каталог событий — одним запросом.

    Каталог рядом со списком потому, что экран подписки без него не собрать, а
    отдельный круг за пятью строчками справочника ничего не экономит.
    """
    cid = await _admin(company_id, current_user, db)
    rows = (await db.execute(select(EventSubscription).where(
        EventSubscription.company_id == cid,
    ).order_by(EventSubscription.label))).scalars().all()
    return {
        "subscriptions": [_sub_out(s) for s in rows],
        "event_types": [{"type": t, "title": name}
                        for t, name in space_events.EVENT_TYPES.items()],
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Завести подписку. Секрет виден только в этом ответе — дальше лишь хвост."""
    cid = await _admin(payload.company_id, current_user, db)
    label = payload.label.strip()
    await _assert_label_free(db, cid, label)
    types = _check_types(payload.event_types)
    url = (payload.url or "").strip() or None

    # Приложению пространства секрет не заводим: служебный канал уже подписан
    # токеном единого входа, и второй общий секрет там нечего охранять.
    raw = enc = hint = None
    if payload.target_kind == "url":
        raw, enc, hint = _new_secret()
    await _check_target(db, payload.target_kind, payload.app_code, url,
                        has_secret=bool(enc))

    sub = EventSubscription(
        company_id=cid, label=label, target_kind=payload.target_kind,
        app_code=payload.app_code, path=payload.path, url=url,
        secret_enc=enc, secret_hint=hint, event_types=types,
        stop_day_count=payload.stop_day_count, enabled=payload.enabled,
        created_by=current_user.id)
    db.add(sub)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="event_subscription.create", target=label,
                    details={"target": url or payload.app_code,
                             "event_types": types})
    await db.flush()
    return {**_sub_out(sub), "secret": raw}


@router.patch("/subscriptions/{sub_id}")
async def update_subscription(
    sub_id: str,
    payload: SubscriptionPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Правка подписки: адрес, набор событий, срок ожидания, включённость."""
    cid = await _admin(payload.company_id, current_user, db)
    sub = await _sub_or_404(db, cid, sub_id)
    data = payload.model_dump(exclude_unset=True, exclude={"company_id"})
    # `null` в теле для необнуляемого поля — это «не меняем», а не «сотри»:
    # подписки без названия, типов событий и срока ожидания не бывает, и падать
    # 500-й из NOT NULL на такой правке не за что.
    data = {k: v for k, v in data.items()
            if v is not None or k in ("app_code", "url")}
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нечего менять")

    if "label" in data:
        data["label"] = data["label"].strip()
        await _assert_label_free(db, cid, data["label"], exclude=sub.id)
    if "event_types" in data:
        data["event_types"] = _check_types(data["event_types"] or [])
    if "url" in data:
        data["url"] = (data["url"] or "").strip() or None

    kind = data.get("target_kind", sub.target_kind)
    app_code = data.get("app_code", sub.app_code)
    if kind == "app":
        # Адрес приложения живёт в реестре: оставить старый URL значило бы
        # хранить вторую копию адреса, которая разъедется с первой.
        data["url"] = None
    url = data["url"] if "url" in data else sub.url
    # Переезд с приложения на внешний адрес: секрета у такой подписки ещё нет,
    # а без него внешнего подписчика не завести — выдаём здесь же.
    raw = None
    if kind == "url" and not sub.secret_enc:
        raw, sub.secret_enc, sub.secret_hint = _new_secret()
    await _check_target(db, kind, app_code, url, has_secret=bool(sub.secret_enc))

    if data.get("enabled") and not sub.enabled:
        # Включили заново — снимаем и след молчания. Иначе фоновой проход увидит
        # старую `failing_since`, сравнит со сроком ожидания и погасит подписку
        # на первом же тике, не сделав ни одной попытки.
        sub.failure_streak = 0
        sub.failing_since = None
        sub.disabled_at = None
        sub.disabled_reason = None
    for field, value in data.items():
        setattr(sub, field, value)

    await log_audit(db, actor=current_user, company_id=cid,
                    action="event_subscription.update", target=sub.label,
                    details=dict(data))
    await db.flush()
    return {**_sub_out(sub), "secret": raw}


@router.delete("/subscriptions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    sub_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Без аннотации возврата намеренно: при `from __future__ import annotations`
    # она приезжает строкой, FastAPI 0.115 (версия образа) резолвит её в
    # NoneType и считает, что у ответа есть тело — а 204 тела иметь не может,
    # и приложение не стартует вовсе. На 0.135, под которой писался модуль,
    # такой проверки нет, поэтому локально всё выглядело исправным.
    """Снять подписку вместе с её недоставленной очередью (каскад в БД).

    Очередь уходит намеренно: адресата больше нет, доставлять некому, а строки
    без подписки только копили бы «вечно ожидающие» события в витрине.
    """
    cid = await _admin(company_id, current_user, db)
    sub = await _sub_or_404(db, cid, sub_id)
    await db.delete(sub)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="event_subscription.delete", target=sub.label)


# ── Очередь доставки ─────────────────────────────────────────────────────────


def _row_out(row: OutboxEvent, label: str) -> dict[str, Any]:
    return {
        "id": str(row.id), "event_id": str(row.event_id),
        "subscription_id": str(row.subscription_id), "subscription": label,
        "type": row.type,
        "type_title": space_events.EVENT_TYPES.get(row.type, row.type),
        "subject": row.subject, "status": row.status, "attempts": row.attempts,
        "occurred_at": _iso(row.occurred_at),
        "next_attempt_at": _iso(row.next_attempt_at),
        "delivered_at": _iso(row.delivered_at),
        "last_error": row.last_error,
        "correlation_id": row.correlation_id,
    }


async def _row_or_404(db: AsyncSession, cid: uuid.UUID,
                      row_id: str) -> OutboxEvent:
    row = (await db.execute(select(OutboxEvent).where(
        OutboxEvent.company_id == cid,
        OutboxEvent.id == _uuid_or_400(row_id, "row_id"),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    return row


@router.get("/outbox")
async def list_outbox(
    company_id: str = Query(...),
    subject: str | None = Query(None, description="Идентификатор документа"),
    status_filter: str | None = Query(None, alias="status"),
    subscription_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=_QUEUE_LIMIT),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что уходило подписчикам и чем кончилось.

    Отбор по документу здесь главный: вопрос почти всегда звучит как «что ушло по
    этому документу и почему не дошло», а не «покажи всю очередь».
    """
    cid = await _admin(company_id, current_user, db)
    if status_filter and status_filter not in _OUTBOX_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Статус: {', '.join(_OUTBOX_STATUSES)}")
    stmt = (select(OutboxEvent, EventSubscription.label)
            .join(EventSubscription,
                  EventSubscription.id == OutboxEvent.subscription_id)
            .where(OutboxEvent.company_id == cid))
    if subject:
        stmt = stmt.where(OutboxEvent.subject == subject)
    if status_filter:
        stmt = stmt.where(OutboxEvent.status == status_filter)
    if subscription_id:
        stmt = stmt.where(OutboxEvent.subscription_id
                          == _uuid_or_400(subscription_id, "subscription_id"))
    rows = (await db.execute(
        stmt.order_by(OutboxEvent.occurred_at.desc()).limit(limit))).all()
    return {"events": [_row_out(r, label) for r, label in rows], "limit": limit}


@router.post("/outbox/{row_id}/retry")
async def retry_delivery(
    row_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Вернуть событие в очередь: попытки с нуля, отправка на ближайшем проходе.

    Только то, что сдалось или было снято. Протухшее не возвращаем: оно старше
    срока ожидания подписки и на первом же проходе протухнет снова — кнопка
    «повторить», которая ничего не повторяет, хуже её отсутствия.
    """
    cid = await _admin(company_id, current_user, db)
    row = await _row_or_404(db, cid, row_id)
    if row.status not in ("failed", "cancelled"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Повторить можно событие со статусом «failed» или «cancelled»")
    sub = await db.get(EventSubscription, row.subscription_id)
    if sub is None or not sub.enabled:
        # Иначе фоновой проход тут же снимет событие обратно, и человек будет
        # жать кнопку, не видя настоящей причины — выключенной подписки.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала включите подписку: иначе фоновой проход "
                            "снимет событие обратно")
    row.status = "pending"
    row.attempts = 0
    row.next_attempt_at = datetime.now(timezone.utc)
    row.last_error = None
    await log_audit(db, actor=current_user, company_id=cid,
                    action="event_outbox.retry", target=sub.label,
                    details={"event_id": str(row.event_id),
                             "type": row.type, "subject": row.subject})
    return {"id": str(row.id), "status": row.status}


@router.post("/outbox/{row_id}/cancel")
async def cancel_delivery(
    row_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Снять событие с доставки. Строка остаётся: след того, что не поехало."""
    cid = await _admin(company_id, current_user, db)
    row = await _row_or_404(db, cid, row_id)
    if row.status not in ("pending", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Снять можно только ожидающее или сдавшееся событие")
    row.status = "cancelled"
    row.last_error = f"снято вручную ({current_user.name or current_user.email})"
    await log_audit(db, actor=current_user, company_id=cid,
                    action="event_outbox.cancel", target=row.type,
                    details={"event_id": str(row.event_id),
                             "subject": row.subject})
    return {"id": str(row.id), "status": row.status}
