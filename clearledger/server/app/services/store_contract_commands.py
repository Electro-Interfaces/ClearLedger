"""Store-адаптер паспорта договора; HTTP-допуск и commit остаются у роутера.

Entry требует сессию без pending writes. Для mixed CREATE подготовка вызывается
до первого db.add/flush Counterparty и записи edge.partner. RefComposite B ещё
не подключён: здесь только действующие legacy barriers CP → contract.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Contract, Organization
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
class StorePartnerContractPlan:
    organization_id: UUID
    fields: StoreContractFields


async def _lock_store_references(db, company_id, *, contract=True):
    # До первого ref/card mutation, в общем порядке с ручными CP writers.
    await lock_manual_creation(db, company_id, "counterparty")
    if contract:
        await lock_manual_creation(db, company_id, "contract")


async def prepare_store_partner_contract(db, company_id, payload):
    """Точный mixed entrypoint для будущего B: до любых CP/edge writes.

    Новая CP ещё не существует: её tenant задаёт сам роутер. Существующую
    Organization проверяем сейчас; обе сохранённые стороны дополнительно
    проходят общий validator перед созданием паспорта.
    """
    await _lock_store_references(db, company_id, contract=bool(payload))
    if not payload:
        return None
    organization_id = payload.get("organization_id")
    if not organization_id:
        raise HTTPException(400, "у договора должна быть организация")
    org_id = _parse_uuid(str(organization_id), "организации")
    org = await db.get(Organization, org_id)
    if org is None or id_key(org.company_id) != id_key(company_id):
        raise HTTPException(400, "Организация не найдена в справочнике пространства")
    title = str(payload.get("name") or payload.get("title") or "Основной договор").strip()
    number = str(payload.get("number") or "").strip()
    return StorePartnerContractPlan(org_id, StoreContractFields(
        number=number or title,
        date=str(payload.get("signed_on") or payload.get("date") or "")[:10],
        title=title, type="поставка", kind="СПоставщиком", currency="RUB", comment=None,
    ))


async def _reject_duplicates(db, company_id, cp_id, org_id, fields, *, current=None):
    identity = contract_identity(fields.number, fields.date, fields.type)
    if identity is None:
        return  # Неполные реквизиты не доказывают тождество обязательств.
    duplicates = await find_contract_card_duplicates(db, company_id, cp_id, org_id, identity)
    if any(current is None or id_key(c.id) != id_key(current) for c in duplicates):
        raise HTTPException(409, "Договор с такими реквизитами уже существует")


async def _create_store_card(db, company_id, cp_id, org_id, fields):
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
    # Типизированные ORM setters: title varchar и raw JSONB имеют разные binders.
    c.title = fields.title
    c.raw = {"source": "center_manual", "name": fields.title}
    return c


async def create_store_partner_contract(db, company_id, counterparty_id, plan):
    """Исполнить подготовленный mixed plan; caller уже держит оба барьера."""
    cp_id, org_id = await _validate_contract_parties(
        db, company_id, counterparty_id, plan.organization_id,
    )
    await _reject_duplicates(db, company_id, cp_id, org_id, plan.fields)
    return await _create_store_card(db, company_id, cp_id, org_id, plan.fields)


async def save_store_contract(db, company_id, payload):
    """CREATE/UPDATE Store: без auth, commit, rollback и смены сторон UPDATE."""
    cp_input, org_input = payload.get("counterparty_id"), payload.get("organization_id")
    title = str(payload.get("title") or payload.get("name") or "").strip()
    number = str(payload.get("number") or "").strip()
    if not cp_input or not org_input:
        raise HTTPException(400, "нужны контрагент и организация")
    if not title and not number:
        raise HTTPException(400, "нужно наименование договора или его номер")
    fields = StoreContractFields(
        number=number or title, date=str(payload.get("date") or "")[:10],
        title=title or f"Договор {number}", type=str(payload.get("type") or "поставка"),
        kind=str(payload.get("kind") or "СПоставщиком"),
        currency=str(payload.get("currency") or "RUB"),
        comment=str(payload.get("comment") or "").strip() or None,
    )
    await _lock_store_references(db, company_id)
    if payload.get("id"):
        uid = _parse_uuid(str(payload["id"]))
        c = (await db.execute(select(Contract).where(
            Contract.id == uid, Contract.company_id == company_id,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if c is None:
            raise HTTPException(404, "Не найдено")
        cp_id, org_id = await _validate_contract_parties(
            db, company_id, c.counterparty_id, c.organization_id,
        )
        # Legacy UPDATE не менял cp/org/type. Matcher видит сохраняемый type.
        actual = StoreContractFields(
            fields.number, fields.date, fields.title, c.type,
            fields.kind, fields.currency, fields.comment,
        )
        await _reject_duplicates(db, company_id, cp_id, org_id, actual, current=c.id)
        c.number, c.date, c.title = fields.number, fields.date, fields.title
        c.kind, c.currency, c.comment = fields.kind, fields.currency, fields.comment
        # raw и manual_overrides прежней карточки остаются прежними.
        return c
    cp_id, org_id = await _validate_contract_parties(db, company_id, cp_input, org_input)
    await _reject_duplicates(db, company_id, cp_id, org_id, fields)
    return await _create_store_card(db, company_id, cp_id, org_id, fields)
