"""Контакты объекта: реестр людей общий, ответственность — на назначении."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.deps import get_owned
from app.models import Contract, ContractLocation, Counterparty, CounterpartyContact, LocationContact, ServiceLocation, User
from app.scope import resolve_object_scope

router = APIRouter(prefix="/references/locations", tags=["Контакты объекта"])


class AssignmentIn(BaseModel):
    responsibility: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


async def context(location_id, user, db):
    location = await get_owned(ServiceLocation, location_id, user, db)
    restricted = bool(await resolve_object_scope(user, location.company_id, db))
    return location, restricted


def related_counterparty(location):
    """Договорная сторона объекта, включая явно общие договоры компании."""
    return exists(select(Contract.id).where(
        Contract.company_id == location.company_id,
        Contract.counterparty_id == Counterparty.id,
        or_(Contract.scope_type == "company", exists(select(ContractLocation.id).where(
            ContractLocation.contract_id == Contract.id,
            ContractLocation.company_id == location.company_id,
            ContractLocation.location_id == location.id)))))


def assigned_counterparty(location):
    return exists(select(LocationContact.contact_id).join(
        CounterpartyContact, CounterpartyContact.id == LocationContact.contact_id).where(
        LocationContact.company_id == location.company_id,
        LocationContact.location_id == location.id,
        CounterpartyContact.company_id == location.company_id,
        CounterpartyContact.counterparty_id == Counterparty.id))


def assigned_contact(location):
    return exists(select(LocationContact.contact_id).where(
        LocationContact.company_id == location.company_id,
        LocationContact.location_id == location.id,
        LocationContact.contact_id == CounterpartyContact.id))


def contact_query(location):
    return select(CounterpartyContact, Counterparty).join(
        Counterparty, Counterparty.id == CounterpartyContact.counterparty_id).where(
        Counterparty.company_id == location.company_id,
        CounterpartyContact.company_id == location.company_id)


def response(contact, cp, responsibility=None):
    return dict(id=str(contact.id), counterpartyId=str(cp.id), counterpartyName=cp.name,
                name=contact.name, position=contact.position, role=contact.role,
                phone=contact.phone, email=contact.email, notes=contact.notes,
                responsibility=responsibility)


@router.get("/{location_id}/contacts")
async def contacts(location_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    location, restricted = await context(location_id, user, db)
    query = contact_query(location).add_columns(LocationContact.responsibility).join(
        LocationContact, and_(LocationContact.contact_id == CounterpartyContact.id,
                              LocationContact.company_id == location.company_id,
                              LocationContact.location_id == location.id))
    assigned = (await db.execute(query.order_by(Counterparty.name, CounterpartyContact.name))).all()
    # Только связанные организации. Эти люди НЕ становятся ответственными за объект.
    general = (await db.execute(contact_query(location).where(
        related_counterparty(location), ~exists(select(LocationContact.contact_id).where(
            LocationContact.location_id == location.id,
            LocationContact.contact_id == CounterpartyContact.id,
            LocationContact.company_id == location.company_id))).order_by(
                Counterparty.name, CounterpartyContact.name))).all()
    return dict(assigned=[response(c, cp, role) for c, cp, role in assigned],
                organizationContacts=[response(c, cp) for c, cp in general], canEditContacts=not restricted)


@router.get("/{location_id}/contact-options")
async def options(location_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    location, restricted = await context(location_id, user, db)
    allowed = or_(related_counterparty(location), assigned_counterparty(location))
    cp_query = select(Counterparty).where(Counterparty.company_id == location.company_id)
    query = contact_query(location)
    # Участник с ограничением по объектам не получает телефонную книгу всей сети.
    if restricted:
        cp_query = cp_query.where(allowed)
        query = query.where(or_(related_counterparty(location), assigned_contact(location)))
    counterparties = (await db.execute(cp_query.order_by(Counterparty.name))).scalars().all()
    people = (await db.execute(query.order_by(Counterparty.name, CounterpartyContact.name))).all()
    return dict(counterparties=[dict(id=str(c.id), name=c.name) for c in counterparties],
                contacts=[response(c, cp) for c, cp in people], canEditContacts=not restricted)


@router.put("/{location_id}/contacts/{contact_id}")
async def assign(location_id: str, contact_id: uuid.UUID, body: AssignmentIn,
                 db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    location, restricted = await context(location_id, user, db)
    query = contact_query(location).where(CounterpartyContact.id == contact_id)
    if restricted:
        query = query.where(or_(related_counterparty(location), assigned_contact(location)))
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(404, "Контакт не найден")
    statement = insert(LocationContact).values(location_id=location.id, contact_id=contact_id,
        company_id=location.company_id, responsibility=body.responsibility)
    await db.execute(statement.on_conflict_do_update(
        index_elements=[LocationContact.location_id, LocationContact.contact_id],
        set_={"responsibility": body.responsibility},
        where=LocationContact.company_id == location.company_id))
    return response(*row, responsibility=body.responsibility)


@router.delete("/{location_id}/contacts/{contact_id}", status_code=204)
async def unassign(location_id: str, contact_id: uuid.UUID,
                   db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    location, _ = await context(location_id, user, db)
    await db.execute(delete(LocationContact).where(LocationContact.company_id == location.company_id,
        LocationContact.location_id == location.id, LocationContact.contact_id == contact_id))
