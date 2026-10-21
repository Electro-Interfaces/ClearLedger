"""Ручки Ядра для узла «Телефонии»: кто звонит и что у него сейчас (Я-1, Я-2).

Узел стоит у заказчика и до ответа оператора спрашивает Ядро его пространства, кто
звонит и что у этого клиента происходит, чтобы оператор увидел карточку, а не
голый номер (ContactHub node/src/adapters/core.ts, отчёт research/10 §7).

Доступ — именной входящий ключ с областью `voice.identify` (`auth.KEY_SCOPES`):
его выдаёт администратор компании отдельно для узла, и общий ключ машинных ручек
сюда не проходит, потому что ответ — ПДн звонящего. У компании должна быть
включена «Телефония». Номер приходит в теле POST, а не в адресе: адрес оседает в
журналах кромки стека. В ответе номер только маской.

Журнал обращений к ПДн ведёт узел (он знает, какой звонок и какой оператор), Ядро
отмечает только время последнего обращения по ключу (`last_used_at`).

Порядок кандидатов — от самого точного к общему, первый лучший:
  1. клиент ЭЗС из витрины АСУиМ (`ezs_customers`): водитель или представитель
     организации, если у клиента есть `organization_ext_id`;
  2. корпоративный клиент ЭЗС по телефону договора (`corporate_clients`);
  3. контактное лицо контрагента (`counterparty_contacts.phone_e164`);
  4. сам контрагент по телефону из карточки (`counterparties.phone_e164`);
  5. человек пространства по мобильному или рабочему (`users.phone_*_e164`):
     свой сотрудник — `staff`, представитель партнёра — `organization`. Инженеры
     поддержки платформы (`vendor`) клиентами заказчика не бывают и пропускаются.
Имени физлица у клиента ЭЗС нет (решение МАГа 08.08.2026: из витрины берётся
только телефон), поэтому `name` у водителя пустое — узел покажет «Водитель».
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import CompanyByKeyScope, _named_key, assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    ChargeSession, Company, CorporateClient, Counterparty, CounterpartyContact,
    EzsCustomer, ServiceLocation, SpaceInboundKey, User, UserCompany,
)
from app.services import sso
from app.services.app_registry import company_apps
from app.services.app_roles import app_roles
from app.services.phone_e164 import mask, to_e164

router = APIRouter(prefix="/eco", tags=["Экосистема: «Телефония»"])
# Ключи внешних систем заказчика для API узла — экран «Ключи систем» в «Телефонии».
keys_router = APIRouter(prefix="/voice", tags=["«Телефония»: ключи систем"])

MAX_CANDIDATES = 5
# Время сессий ЭЗС в базе — московское без зоны («Начало сессии по МСК»).
MSK = timezone(timedelta(hours=3))


class IdentifyIn(BaseModel):
    channel: str = Field("phone", pattern="^phone$")
    value: str = Field(..., min_length=3, max_length=40)


class SummaryIn(BaseModel):
    phone: str = Field(..., min_length=3, max_length=40)
    # Кандидат из ответа /identify: `ezs:<id>` уточняет, чьи сессии брать.
    ref: str | None = Field(None, max_length=80)
    limit: int = Field(5, ge=1, le=20)


class SupportContextIn(BaseModel):
    supportCompanyId: uuid.UUID
    phone: str = Field(..., min_length=3, max_length=40)
    phones: list[str] = Field(default_factory=list, max_length=20)
    ref: str | None = Field(None, max_length=80)
    limit: int = Field(300, ge=1, le=1000)
    detail: bool = False
    # Opt-in для сборщика v1: кандидат не становится выбранным человеком.
    strictSelection: bool = False
    cursor: str | None = Field(None, max_length=4096)


class VoiceKnowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{0,59}$")
    limit: int = Field(3, ge=1, le=3)


async def _voice_on(db: AsyncSession, company_id) -> None:
    if not any(a["code"] == "voice" and a["enabled"] for a in await company_apps(db, company_id)):
        raise HTTPException(403, "«Телефония» не подключена компании")


async def voice_company(
    dep=Depends(CompanyByKeyScope("voice.identify")),
    db: AsyncSession = Depends(get_db),
) -> Company:
    """Компания ключа узла — если ей включена «Телефония»."""
    company, _key = dep
    await _voice_on(db, company.id)
    return company


@router.get("/voice/connection")
async def check_node_connection(response: Response, company: Company = Depends(voice_company)):
    """Узел проверяет свой именной ключ и компанию без передачи данных звонящего."""
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ok", "company_id": str(company.id)}


def _num(v) -> float | None:
    return None if v is None else float(v)


def _iso(dt: datetime | None, naive_tz=None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None and naive_tz is not None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.isoformat()


def _candidate(kind: str, source: str, ref: str, *, name=None, org_name=None, account=None,
               balance=None, active=None, registered_at=None, object_ref=None,
               address=None) -> dict[str, Any]:
    return {
        "kind": kind, "source": source, "ref": ref, "name": name, "orgName": org_name,
        "account": account, "balance": _num(balance), "active": active,
        "registeredAt": registered_at, "objectRef": object_ref, "address": address,
    }


async def find_candidates(db: AsyncSession, company_id: uuid.UUID, e164: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_orgs: set[str] = set()   # ext_id корпклиентов, уже названных через клиента ЭЗС

    customers = (await db.execute(
        select(EzsCustomer).where(EzsCustomer.company_id == company_id, EzsCustomer.phone == e164)
        .order_by(EzsCustomer.is_active.desc().nulls_last(), EzsCustomer.registered_at.desc().nulls_last())
        .limit(MAX_CANDIDATES)
    )).scalars().all()
    org_ids = {c.organization_ext_id for c in customers if c.organization_ext_id}
    orgs = {o.ext_id: o for o in (await db.execute(
        select(CorporateClient).where(CorporateClient.company_id == company_id,
                                      CorporateClient.ext_id.in_(org_ids))
    )).scalars().all()} if org_ids else {}
    for c in customers:
        org = orgs.get(c.organization_ext_id) if c.organization_ext_id else None
        if c.organization_ext_id:
            seen_orgs.add(c.organization_ext_id)
        out.append(_candidate(
            "organization" if c.organization_ext_id else "driver", "ezs_customer",
            f"ezs:{c.customer_ext_id}", org_name=org.name if org else None,
            account=c.customer_ext_id, balance=c.balance, active=c.is_active,
            registered_at=_iso(c.registered_at, MSK)))

    for o in (await db.execute(
        select(CorporateClient).where(CorporateClient.company_id == company_id,
                                      CorporateClient.phone == e164)
        .order_by(CorporateClient.name).limit(MAX_CANDIDATES)
    )).scalars().all():
        if o.ext_id and o.ext_id in seen_orgs:
            continue
        out.append(_candidate("organization", "corporate_client", f"corp:{o.id}",
                              org_name=o.name, account=o.inn,
                              # «Действующая» — как в реестре «Организации» (corporate_service).
                              active=(o.status.strip().lower() == "действующая") if o.status else None))

    for contact, cp in (await db.execute(
        select(CounterpartyContact, Counterparty)
        .join(Counterparty, Counterparty.id == CounterpartyContact.counterparty_id)
        .where(CounterpartyContact.company_id == company_id, CounterpartyContact.phone_e164 == e164)
        .order_by(CounterpartyContact.name).limit(MAX_CANDIDATES)
    )).all():
        out.append(_candidate("organization", "counterparty_contact", f"cpc:{contact.id}",
                              name=contact.name, org_name=cp.short_name or cp.name, account=cp.inn,
                              address=cp.actual_address))

    for cp in (await db.execute(
        select(Counterparty).where(Counterparty.company_id == company_id,
                                   Counterparty.phone_e164 == e164,
                                   Counterparty.is_group.is_(False))
        .order_by(Counterparty.name).limit(MAX_CANDIDATES)
    )).scalars().all():
        out.append(_candidate("organization", "counterparty", f"cp:{cp.id}",
                              org_name=cp.short_name or cp.name, account=cp.inn,
                              address=cp.actual_address))

    people = (await db.execute(
        select(User, UserCompany)
        .join(UserCompany, and_(UserCompany.user_id == User.id, UserCompany.company_id == company_id))
        .where(or_(User.phone_mobile_e164 == e164, User.phone_office_e164 == e164),
               UserCompany.party_type != "vendor")
        .order_by(User.name).limit(MAX_CANDIDATES)
    )).all()
    org_names = {}
    partner_orgs = {m.organization_id for _u, m in people if m.organization_id}
    if partner_orgs:
        org_names = {cp.id: cp.short_name or cp.name for cp in (await db.execute(
            select(Counterparty).where(Counterparty.company_id == company_id,
                                      Counterparty.id.in_(partner_orgs)))).scalars().all()}
    for u, m in people:
        partner = m.party_type == "partner"
        out.append(_candidate("organization" if partner else "staff", "user", f"user:{u.id}",
                              name=u.name, org_name=org_names.get(m.organization_id)))
    return out[:MAX_CANDIDATES]


@router.post("/identify")
async def identify(
    body: IdentifyIn,
    company: Company = Depends(voice_company),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Кто звонит по номеру. Пустой список — номер в пространстве не знают."""
    e164 = to_e164(body.value)
    if not e164:
        return {"channel": "phone", "phoneMasked": "—", "candidates": []}
    return {"channel": "phone", "phoneMasked": mask(e164),
            "candidates": await find_candidates(db, company.id, e164)}


async def _customer_summary_data(
    body: SummaryIn,
    company: Company,
    db: AsyncSession,
    *, as_of: datetime | None = None,
) -> dict[str, Any]:
    """Последние зарядные сессии клиента (новые первыми), их станции и счёт за 30 дней.

    Сессии берутся по телефону сессии (`charge_sessions.user_id`) и, если узел
    передал клиента ЭЗС (`ref=ezs:<id>`), ещё по владельцу карты: заправка по
    RFID-карте приходит без телефона водителя.
    """
    e164 = to_e164(body.phone)
    conds = []
    if e164:
        conds.append(ChargeSession.user_id == e164)
    if body.ref and body.ref.startswith("ezs:"):
        ext_id = body.ref[4:]
        known = (await db.execute(
            select(EzsCustomer.customer_ext_id).where(EzsCustomer.company_id == company.id,
                                                      EzsCustomer.customer_ext_id == ext_id)
        )).scalar_one_or_none()
        if known:
            conds.append(ChargeSession.card_owner_ext_id == ext_id)
    empty = {"sessions": [], "objects": [], "stats": {"sessions30d": 0, "failed30d": 0}}
    if not conds:
        return empty
    where = and_(ChargeSession.company_id == company.id, or_(*conds))
    if as_of is not None:
        where = and_(where, ChargeSession.started_at <= as_of.replace(tzinfo=None))

    rows = (await db.execute(
        select(ChargeSession).where(where, ChargeSession.started_at.is_not(None))
        .order_by(ChargeSession.started_at.desc()).limit(body.limit)
    )).scalars().all()
    since = (as_of or datetime.now(MSK)).replace(tzinfo=None) - timedelta(days=30)
    total, failed = (await db.execute(
        select(func.count(), func.count().filter(ChargeSession.energy_kwh <= 0))
        .where(where, ChargeSession.started_at >= since)
    )).one()

    loc_ids = list(dict.fromkeys(s.location_id for s in rows if s.location_id))
    locs = {loc.id: loc for loc in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company.id,
                                      ServiceLocation.id.in_(loc_ids))
    )).scalars().all()} if loc_ids else {}
    return {
        "sessions": [{
            "ref": s.session_ext_id,
            "objectRef": s.location_id if s.location_id in locs else None,
            "startedAt": _iso(s.started_at, MSK),
            "result": s.result or "",
            "failed": float(s.energy_kwh or 0) <= 0,
            "energyKwh": _num(s.energy_kwh),
            "amount": _num(s.amount),
        } for s in rows],
        "objects": [{
            "ref": loc.id, "code": loc.station_number or loc.code, "name": loc.name,
            "address": loc.address, "status": loc.operational_status,
        } for loc in (locs[i] for i in loc_ids if i in locs)],
        "stats": {"sessions30d": int(total or 0), "failed30d": int(failed or 0)},
    }


@router.post("/ezs/customer-summary")
async def customer_summary(
    body: SummaryIn,
    company: Company = Depends(voice_company),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.voice_support_context import support_tickets

    summary = await _customer_summary_data(body, company, db)
    tickets, availability = await support_tickets(
        db, company.id, phone=body.phone, core_party_ref=body.ref,
        object_refs=[o["ref"] for o in summary["objects"]], limit=body.limit,
    )
    return {**summary, "tickets": tickets, "ticketAvailability": availability}


@router.post("/support/knowledge")
async def voice_knowledge(
    body: VoiceKnowledgeIn,
    response: Response,
    company: Company = Depends(voice_company),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Три опубликованных статьи своей компании по коду темы, без текста разговора."""
    from app.services.voice_support_context import support_knowledge

    response.headers["Cache-Control"] = "no-store"
    return await support_knowledge(db, company.id, topic=body.topic, limit=body.limit)


@router.post("/support/customer-context")
async def support_customer_context(
    body: SupportContextIn,
    company: Company = Depends(voice_company),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Данные клиента для Поддержки; карта и ключ фиксируют одну компанию.

    Здесь нет обратного вызова в Поддержку: её заявки читаются там же, где живут.
    """
    from app.services.support_scope import support_company_id
    from app.services.voice_support_context import charging_context, decode_source_cursor

    mapped = await support_company_id(db, company.id)
    if mapped != str(body.supportCompanyId):
        raise HTTPException(403, "Компания Поддержки не соответствует ключу пространства")
    if not any(a["code"] == "support" and a["enabled"] for a in await company_apps(db, company.id)):
        raise HTTPException(403, "«Поддержка» не подключена компании")
    e164 = to_e164(body.phone)
    candidates = await find_candidates(db, company.id, e164) if e164 else []
    caller = next((c for c in candidates if c["ref"] == body.ref), None)
    if body.strictSelection:
        if body.ref and caller is None:
            raise HTTPException(404, "Выбранный человек не относится к этому поиску")
    else:
        caller = caller or (candidates[0] if candidates else None)
    party_ref = caller["ref"] if caller else None
    as_of = datetime.now(MSK) if body.strictSelection else None
    page = None
    if body.cursor:
        if not body.strictSelection or not body.detail:
            raise HTTPException(400, "Курсор требует strictSelection/detail")
        page = decode_source_cursor(body.cursor, company.id, [body.phone, *body.phones], party_ref)
        as_of = datetime.fromisoformat(page["asOf"])
    summary = await _customer_summary_data(
        SummaryIn(phone="unknown" if body.strictSelection and party_ref else body.phone,
                  ref=party_ref, limit=min(body.limit, 20)), company, db, as_of=as_of,
    )
    charging = await charging_context(
        db, company.id, phones=[body.phone, *body.phones], ref=party_ref,
        limit=body.limit, detail=body.detail, strict_ref=body.strictSelection and bool(party_ref),
        strict_selection=body.strictSelection, as_of=as_of, page=page,
    )
    if body.strictSelection and not party_ref:
        charging["ezs"] = None
    strict_fields = ({"candidates": candidates,
                      "identityState": "operator_selected" if caller else
                          "ambiguous" if len(candidates) > 1 else "candidate" if candidates else "unknown",
                      "historyIdentity": "core_person" if caller else "phone"}
                     if body.strictSelection else {})
    return {
        "supportCompanyId": str(body.supportCompanyId), "coreCompanyId": str(company.id),
        "corePartyRef": party_ref, "caller": caller, **summary, **charging,
        "availability": "available", **strict_fields,
    }


# ─── Ключи систем: доступ внешних систем к API узла без ПДн ─────────────────────
#
# Мониторинг или BI заказчика читает статистику и здоровье узла (`voice.stats`) или
# журнал доступа (`voice.audit`). Ключ живёт в Ядре — тот же именной входящий ключ
# (`space_inbound_keys`) с областью, — а в узел система идёт служебным токеном
# Ядра: меняет ключ на токен `aud=voice` на 120 секунд (`/eco/voice/token`). Узел
# ключей не хранит и проверяет только подпись по JWKS пространства, как у экранов.
# Ключ отдаётся один раз при выдаче; отзыв мгновенный: следующий обмен не пройдёт,
# а выданный токен доживает свои две минуты.

VOICE_KEY_SCOPES = set(sso.VOICE_SERVICE_SCOPES)


class VoiceKeyCreate(BaseModel):
    company_id: str
    consumer: str = Field(min_length=2, max_length=200)
    scopes: list[str] = Field(min_length=1)


class VoiceTokenIn(BaseModel):
    # Без области — единственная область ключа.
    scope: str | None = None


async def _voice_admin(company_ref: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Администратор «Телефонии» компании: администратор компании или тот, кому роль
    `admin` в «Телефонии» назначили явно (`services/app_roles.py`)."""
    cid = await assert_company_member(company_ref, user, db)
    await _voice_on(db, cid)
    if user.is_superadmin:
        return cid
    m = await db.get(UserCompany, (user.id, cid))
    if (m is not None and m.role == "admin") or "admin" in await app_roles(db, user, cid, "voice"):
        return cid
    raise HTTPException(403, "Требуются права администратора «Телефонии»")


def _voice_scopes(k: SpaceInboundKey) -> list[str]:
    return [x for x in (k.scopes or []) if x in VOICE_KEY_SCOPES]


def _iso_or_none(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@keys_router.get("/keys")
async def list_voice_keys(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cid = await _voice_admin(company_id, user, db)
    rows = (await db.execute(
        select(SpaceInboundKey).where(SpaceInboundKey.company_id == cid,
                                      SpaceInboundKey.scopes.is_not(None))
        .order_by(SpaceInboundKey.created_at.desc())
    )).scalars().all()
    return {"keys": [{
        "id": str(k.id), "consumer": k.consumer, "prefix": k.key_prefix,
        "scopes": _voice_scopes(k),
        "created_at": _iso_or_none(k.created_at),
        "last_used_at": _iso_or_none(k.last_used_at),
        "revoked_at": _iso_or_none(k.revoked_at),
    } for k in rows if _voice_scopes(k)]}


@keys_router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_voice_key(
    payload: VoiceKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Выдать ключ системе. Сам ключ — только в этом ответе, дальше лишь хеш."""
    cid = await _voice_admin(payload.company_id, user, db)
    scopes = sorted(set(payload.scopes))
    unknown = [x for x in scopes if x not in VOICE_KEY_SCOPES]
    if unknown:
        raise HTTPException(422, f"Неизвестная область ключа: {', '.join(unknown)}")
    raw = secrets.token_urlsafe(32)
    key = SpaceInboundKey(
        id=uuid.uuid4(), company_id=cid, consumer=payload.consumer.strip(), actor_kind="partner",
        key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:8], scopes=scopes,
    )
    db.add(key)
    await log_audit(db, actor=user, company_id=cid, action="voice_key.create",
                    target=key.consumer, details={"scopes": scopes})
    # Фиксация до ответа: get_db коммитит уже после отправки ответа, а ключ из ответа
    # должен работать сразу (и отзыв ниже — не пропускать обмен следующей же секундой).
    await db.commit()
    return {"id": str(key.id), "consumer": key.consumer, "key": raw,
            "prefix": key.key_prefix, "scopes": scopes}


@keys_router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_voice_key(
    key_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Отозвать ключ: строка остаётся в списке с отметкой — история выдач видна."""
    cid = await _voice_admin(company_id, user, db)
    try:
        kid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(400, "Невалидный ID")
    key = await db.get(SpaceInboundKey, kid)
    # Здесь отзываются только ключи «Телефонии»: остальные — в «Управлении».
    if key is None or key.company_id != cid or not _voice_scopes(key):
        raise HTTPException(404, "Ключ не найден")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await log_audit(db, actor=user, company_id=cid, action="voice_key.revoke",
                        target=key.consumer)
        await db.commit()


@router.post("/voice/token")
async def exchange_voice_key(
    body: VoiceTokenIn,
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Обменять ключ системы на служебный токен Ядра для API узла (`aud=voice`).

    Токен — на одну область (`svc`), компанию ключа (`cid`), с `jti` и на 120 секунд;
    в `actor` — имя системы из ключа: узел пишет его в журнал доступа как имя того,
    кто ходил (node/src/space.ts)."""
    named = await _named_key(x_cloud_api_key, db) if x_cloud_api_key else None
    if named is None:
        raise HTTPException(401, "Невалидный API-ключ")
    own = _voice_scopes(named)
    scope = body.scope or (own[0] if len(own) == 1 else None)
    if scope is None:
        raise HTTPException(422, "Укажите область токена: у ключа их несколько")
    if scope not in VOICE_KEY_SCOPES:
        raise HTTPException(422, f"Неизвестная область «Телефонии»: {scope}")
    if scope not in own:
        raise HTTPException(403, f"Ключ выдан без области {scope}")
    await _voice_on(db, named.company_id)
    token = sso.sign_voice_service_token(scope=scope, company_id=str(named.company_id),
                                         actor_id=named.consumer)
    if not token:
        raise HTTPException(503, "Единый вход не настроен: нет ключа подписи")
    named.last_used_at = datetime.now(timezone.utc)
    # Фиксация до ответа, как у выдачи и отзыва: get_db коммитит уже после отправки
    # ответа, а экран «Ключи систем» показывает время обмена сразу.
    await db.commit()
    return {"token": token, "token_type": "bearer", "expires_in": 120, "scope": scope}


# Отдельный namespace и auth, зарегистрирован до штатного create_all. Старые
# /identify, /customer-summary и /support/customer-context остаются совместимы.
from app.routers.support_context_router import router as support_context_router

router.include_router(support_context_router)
