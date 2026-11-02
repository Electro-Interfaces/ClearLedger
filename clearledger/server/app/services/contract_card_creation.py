"""Общие операции над паспортом договора с подготовленными значениями.

Caller проверяет допуск, стороны, вид и реквизиты, владеет блокировками,
повторами намерения и завершением транзакции. Здесь нет собственной policy.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contract
from app.services.reference_identity import contract_identity


@dataclass(frozen=True, kw_only=True)
class ContractCardValues:
    """Все явно задаваемые при создании колонки, без новых defaults."""

    company_id: UUID
    creation_key: UUID | None
    creation_actor_id: UUID | None
    creation_request_hash: str | None
    number: str
    date: str
    counterparty_id: UUID
    organization_id: UUID
    type: str
    type_code: str | None
    amount_limit: float | None
    kind: str | None
    currency: str | None
    valid_until: str | None
    vat_rate: str | None
    amount_incl_vat: bool | None
    settlement_kind: str | None
    comment: str | None
    basis: str | None
    is_closed: bool
    scope_type: str
    signed: bool | None
    signed_at: str | None
    payment_term_days: int | None
    is_state_contract: bool | None
    igk: str | None
    responsible_id: UUID | None
    signer_our: str | None
    signer_our_position: str | None
    signer_cp: str | None
    signer_cp_position: str | None
    signer_cp_basis: str | None


async def find_contract_card_duplicates(
    db: AsyncSession, company_id: UUID, counterparty_id: UUID,
    organization_id: UUID, identity: tuple[str, str, str],
) -> list[Contract]:
    """Вернуть все совпадения готовой полной identity в точных сторонах/tenant.

    Caller решает, когда полная identity допускает проверку, и как сообщить
    конфликт. Чтение не заменяет общий барьер между проверкой и INSERT.
    """
    candidates = (await db.execute(select(Contract).where(
        Contract.company_id == company_id, Contract.counterparty_id == counterparty_id,
        Contract.organization_id == organization_id,
    ))).scalars().all()
    duplicates = [c for c in candidates if contract_identity(c.number, c.date, c.type) == identity]
    return duplicates


async def create_contract_card(db: AsyncSession, values: ContractCardValues) -> Contract:
    """Создать и flush паспорт; commit/rollback и связанные строки у caller."""
    c = Contract(
        company_id=values.company_id,
        creation_key=values.creation_key,
        creation_actor_id=values.creation_actor_id,
        creation_request_hash=values.creation_request_hash,
        number=values.number,
        date=values.date,
        counterparty_id=values.counterparty_id,
        organization_id=values.organization_id,
        type=values.type,
        type_code=values.type_code,
        amount_limit=values.amount_limit,
        kind=values.kind,
        currency=values.currency,
        valid_until=values.valid_until,
        vat_rate=values.vat_rate,
        amount_incl_vat=values.amount_incl_vat,
        settlement_kind=values.settlement_kind,
        comment=values.comment,
        basis=values.basis,
        is_closed=values.is_closed,
        scope_type=values.scope_type,
        signed=values.signed,
        signed_at=values.signed_at,
        payment_term_days=values.payment_term_days,
        is_state_contract=values.is_state_contract,
        igk=values.igk,
        responsible_id=values.responsible_id,
        signer_our=values.signer_our,
        signer_our_position=values.signer_our_position,
        signer_cp=values.signer_cp,
        signer_cp_position=values.signer_cp_position,
        signer_cp_basis=values.signer_cp_basis,
    )
    db.add(c)
    await db.flush()
    return c
