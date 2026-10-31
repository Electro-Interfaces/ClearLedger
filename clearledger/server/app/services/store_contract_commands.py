"""Store-адаптер паспорта договора; HTTP-допуск и commit остаются у роутера.

Entry требует сессию без pending writes. Для mixed CREATE подготовка вызывается
до первого db.add/flush Counterparty и записи edge.partner. Полный scoped plan
предшествует действующим legacy barriers CP → contract; root завершает caller.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Company, Contract, Organization
from app.services.contract_write_locks import (
    CompanyKey, RefCompositeKey, LockMode, LockRequest, LockPlan,
    ScopedLockCapability, ScopedLockError, acquire_scoped_locks_async,
    require_scoped_locks,
)
from app.services.contract_card_creation import (
    ContractCardValues, create_contract_card, find_contract_card_duplicates,
)
from app.services.reference_identity import contract_identity, id_key, lock_manual_creation
from app.services.reference_validation import _parse_uuid, _validate_contract_parties


@dataclass(frozen=True)
class StoreContractFields:
    number: str
    date: str
    title: str
    type: str
    kind: str
    currency: str
    comment: str | None


@dataclass(frozen=True)
class PreparedStoreContractWrite:
    company_id: UUID
    capability: ScopedLockCapability


def reject_store_pending_writes(db):
    """До любого discovery, способного autoflush; ничего не очищать/flush."""
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Store requires clean entry; roll back the entire root")


def _store_lock_requests(company_id):
    # company_id получен сервером из проверенного Store access, не из payload.
    return (LockRequest(CompanyKey(company_id), LockMode.SHARED),
            LockRequest(RefCompositeKey(company_id), LockMode.EXCLUSIVE))


def require_store_contract_write(db, company_id, prepared):
    # Dataclass не выдаёт authority: actual helper проверяет issuer/root/connection.
    if type(prepared) is not PreparedStoreContractWrite or prepared.company_id != company_id:
        raise ScopedLockError("Prepared Store company mismatch; roll back the entire root")
    require_scoped_locks(db.sync_session, prepared.capability, _store_lock_requests(company_id))


async def _prepare_store_contract_write(db, company_id):
    reject_store_pending_writes(db)
    capability = await acquire_scoped_locks_async(db, LockPlan(_store_lock_requests(company_id)))
    prepared = PreparedStoreContractWrite(company_id, capability)
    require_store_contract_write(db, company_id, prepared)
    # Повторное чтение после ожидания на той же root, без старого identity-map snapshot.
    company = await db.get(Company, company_id, populate_existing=True)
    require_store_contract_write(db, company_id, prepared)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    await _lock_store_references(db, company_id, prepared=prepared)
    return prepared


@dataclass(frozen=True)
class StorePartnerContractPlan:
    organization_id: UUID
    fields: StoreContractFields
    prepared: PreparedStoreContractWrite


async def _lock_store_references(db, company_id, *, contract=True, prepared=None):
    # До первого ref/card mutation, в общем порядке с ручными CP writers.
    if contract:
        require_store_contract_write(db, company_id, prepared)
    await lock_manual_creation(db, company_id, "counterparty")
    if contract:
        require_store_contract_write(db, company_id, prepared)
    if contract:
        await lock_manual_creation(db, company_id, "contract")
        require_store_contract_write(db, company_id, prepared)


async def prepare_store_partner_contract(db, company_id, payload):
    """Mixed entrypoint до любых CP/edge writes.

    Новая CP ещё не существует: её tenant задаёт сам роутер. Существующую
    Organization проверяем сейчас; обе сохранённые стороны дополнительно
    проходят общий validator перед созданием паспорта.
    """
    reject_store_pending_writes(db)
    if not payload:
        # Прежний CP-only pipeline: не добавлять широкий B gate.
        await _lock_store_references(db, company_id, contract=False)
        return None
    prepared = await _prepare_store_contract_write(db, company_id)
    organization_id = payload.get("organization_id")
    if not organization_id:
        raise HTTPException(400, "у договора должна быть организация")
    org_id = _parse_uuid(str(organization_id), "организации")
    org = await db.get(Organization, org_id, populate_existing=True)
    require_store_contract_write(db, company_id, prepared)
    if org is None or id_key(org.company_id) != id_key(company_id):
        raise HTTPException(400, "Организация не найдена в справочнике пространства")
    title = str(payload.get("name") or payload.get("title") or "Основной договор").strip()
    number = str(payload.get("number") or "").strip()
    return StorePartnerContractPlan(org_id, StoreContractFields(
        number=number or title,
        date=str(payload.get("signed_on") or payload.get("date") or "")[:10],
        title=title, type="поставка", kind="СПоставщиком", currency="RUB", comment=None,
    ), prepared)


async def _reject_duplicates(db, company_id, cp_id, org_id, fields, *, current=None):
    identity = contract_identity(fields.number, fields.date, fields.type)
    if identity is None:
        return  # Неполные реквизиты не доказывают тождество обязательств.
    duplicates = await find_contract_card_duplicates(db, company_id, cp_id, org_id, identity)
    if any(current is None or id_key(c.id) != id_key(current) for c in duplicates):
        raise HTTPException(409, "Договор с такими реквизитами уже существует")


async def _create_store_card(db, company_id, cp_id, org_id, fields, prepared):
    require_store_contract_write(db, company_id, prepared)
    c = await create_contract_card(db, ContractCardValues(
        company_id=company_id, creation_key=None, creation_actor_id=None,
        creation_request_hash=None, number=fields.number, date=fields.date,
        counterparty_id=cp_id, organization_id=org_id, type=fields.type,
        kind=fields.kind, currency=fields.currency, comment=fields.comment,
        type_code=None, amount_limit=None, valid_until=None, vat_rate=None,
        amount_incl_vat=None, settlement_kind=None, basis=None,
        is_closed=False, scope_type="unassigned", signed=None, signed_at=None,
        payment_term_days=None, is_state_contract=None, igk=None, responsible_id=None,
        signer_our=None, signer_our_position=None, signer_cp=None,
        signer_cp_position=None, signer_cp_basis=None,
    ))
    require_store_contract_write(db, company_id, prepared)
    # Типизированные ORM setters: title varchar и raw JSONB имеют разные binders.
    c.title = fields.title
    c.raw = {"source": "center_manual", "name": fields.title}
    return c


async def create_store_partner_contract(db, company_id, counterparty_id, plan):
    """Исполнить подготовленный mixed plan; caller уже держит оба барьера."""
    require_store_contract_write(db, company_id, plan.prepared)
    cp_id, org_id = await _validate_contract_parties(
        db, company_id, counterparty_id, plan.organization_id,
    )
    require_store_contract_write(db, company_id, plan.prepared)
    await _reject_duplicates(db, company_id, cp_id, org_id, plan.fields)
    require_store_contract_write(db, company_id, plan.prepared)
    return await _create_store_card(db, company_id, cp_id, org_id, plan.fields, plan.prepared)


def _store_contract_fields(payload):
    cp_input, org_input = payload.get("counterparty_id"), payload.get("organization_id")
    title = str(payload.get("title") or payload.get("name") or "").strip()
    number = str(payload.get("number") or "").strip()
    if not cp_input or not org_input:
        raise HTTPException(400, "нужны контрагент и организация")
    if not title and not number:
        raise HTTPException(400, "нужно наименование договора или его номер")
    return StoreContractFields(
        number=number or title, date=str(payload.get("date") or "")[:10],
        title=title or f"Договор {number}", type=str(payload.get("type") or "поставка"),
        kind=str(payload.get("kind") or "СПоставщиком"),
        currency=str(payload.get("currency") or "RUB"),
        comment=str(payload.get("comment") or "").strip() or None,
    )


async def prepare_store_contract(db, company_id, payload):
    """Required400 до планирования; затем единственный полный acquire."""
    _store_contract_fields(payload)
    return await _prepare_store_contract_write(db, company_id)


async def save_store_contract(db, company_id, payload, *, prepared):
    """CREATE/UPDATE: explicit capability, без late acquire/commit/rollback."""
    fields = _store_contract_fields(payload)
    require_store_contract_write(db, company_id, prepared)
    cp_input, org_input = payload.get("counterparty_id"), payload.get("organization_id")
    if payload.get("id"):
        uid = _parse_uuid(str(payload["id"]))
        c = (await db.execute(select(Contract).where(
            Contract.id == uid, Contract.company_id == company_id,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        require_store_contract_write(db, company_id, prepared)
        if c is None:
            raise HTTPException(404, "Не найдено")
        cp_id, org_id = await _validate_contract_parties(
            db, company_id, c.counterparty_id, c.organization_id,
        )
        require_store_contract_write(db, company_id, prepared)
        # Legacy UPDATE не менял cp/org/type. Matcher видит сохраняемый type.
        actual = StoreContractFields(
            fields.number, fields.date, fields.title, c.type,
            fields.kind, fields.currency, fields.comment,
        )
        await _reject_duplicates(db, company_id, cp_id, org_id, actual, current=c.id)
        require_store_contract_write(db, company_id, prepared)
        c.number, c.date, c.title = fields.number, fields.date, fields.title
        c.kind, c.currency, c.comment = fields.kind, fields.currency, fields.comment
        # raw и manual_overrides прежней карточки остаются прежними.
        return c
    cp_id, org_id = await _validate_contract_parties(db, company_id, cp_input, org_input)
    require_store_contract_write(db, company_id, prepared)
    await _reject_duplicates(db, company_id, cp_id, org_id, fields)
    require_store_contract_write(db, company_id, prepared)
    return await _create_store_card(db, company_id, cp_id, org_id, fields, prepared)
