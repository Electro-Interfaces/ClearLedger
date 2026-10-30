"""Native use case создания паспорта договора.

Принимает валидированный native ввод и настоящего native User. Не адаптер
partner principal: отдельная partner policy здесь не реализована. Возвращает
ORM-карточку; сериализация и завершение транзакции принадлежат caller.
"""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member
from app.models import Contract, User
from app.schemas import ContractCreate
from app.services.reference_identity import contract_identity, lock_manual_creation
from app.services.reference_validation import (
    _CONTRACT_REQ_FIELDS, _check_type_code, _req_val, _validate_contract_parties,
)


async def create_native_contract(
    db: AsyncSession, body: ContractCreate, current_user: User,
) -> Contract:
    cid = await assert_company_member(body.company_id, current_user, db)
    cp_id, org_id = await _validate_contract_parties(
        db, cid, body.counterpartyId, body.organizationId)
    identity = contract_identity(body.number, body.date, body.type)
    request_hash = hashlib.sha256(json.dumps(
        body.model_dump(mode="json", exclude={"company_id", "creationKey"}),
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest() if body.creationKey else None
    if identity or body.creationKey:
        await lock_manual_creation(db, cid, "contract")
    if body.creationKey:
        previous = (await db.execute(select(Contract).where(
            Contract.company_id == cid, Contract.creation_key == body.creationKey,
        ))).scalar_one_or_none()
        if previous is not None:
            if previous.creation_actor_id != current_user.id or previous.creation_request_hash != request_hash:
                raise HTTPException(409, "Ключ создания договора уже использован с другими реквизитами")
            return previous
    if identity:
        candidates = (await db.execute(select(Contract).where(
            Contract.company_id == cid, Contract.counterparty_id == cp_id,
            Contract.organization_id == org_id,
        ))).scalars().all()
        duplicates = [c for c in candidates if contract_identity(c.number, c.date, c.type) == identity]
        if duplicates:
            raise HTTPException(409, "Договор с такими сторонами и реквизитами уже существует: "
                                + ", ".join(sorted(str(c.id) for c in duplicates)))
    c = Contract(
        company_id=cid,
        creation_key=body.creationKey,
        creation_actor_id=current_user.id if body.creationKey else None,
        creation_request_hash=request_hash,
        number=body.number,
        date=body.date,
        counterparty_id=cp_id,
        organization_id=org_id,
        type=body.type,
        type_code=await _check_type_code(db, body.typeCode),
        amount_limit=body.amountLimit,
        kind=body.kind,
        currency=body.currency,
        valid_until=body.validUntil,
        vat_rate=body.vatRate,
        amount_incl_vat=body.amountInclVat,
        settlement_kind=body.settlementKind,
        comment=body.comment,
        basis=body.basis,
        is_closed=body.isClosed,
        scope_type=body.scopeType,
        **{col: _req_val(api, getattr(body, api)) for api, col in _CONTRACT_REQ_FIELDS.items()},
    )
    db.add(c)
    await db.flush()
    return c
