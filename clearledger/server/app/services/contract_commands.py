"""Создание уже сопоставленной импортной карточки договора.

Caller владеет компанией, допуском, matcher, locks и адаптацией значений.
Команда не выбирает стороны, не делает upsert и не завершает транзакцию.
"""
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contract
from app.services.reference_identity import ContractIndex


async def create_imported_contract(
    db: AsyncSession, company_id: UUID | str, index: ContractIndex, *,
    number: str, date: str, counterparty_id: UUID | str,
    organization_id: UUID | str, type: str, kind: str,
    basis: str | None, scope_type: str, raw: dict[str, Any],
) -> Contract:
    """Создать паспорт из готовых полей и опубликовать после успешного flush.

    Колонки и исходный raw передаются раздельно без нормализации и усечения.
    Отказ flush не публикует новую карточку; при rollback всего caller ранее
    опубликованные записи его индекса автоматически не очищаются.
    """
    contract = Contract(
        company_id=company_id, number=number, date=date,
        counterparty_id=counterparty_id, organization_id=organization_id,
        type=type, kind=kind, basis=basis, scope_type=scope_type, raw=raw,
    )
    db.add(contract)
    await db.flush()
    index.add(contract)
    return contract
