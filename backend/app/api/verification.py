"""Серверная верификация документа против справочников."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Entry, Counterparty, Contract, User
from app.api.deps import get_current_user
from app.services.normalization import fuzzy_match_counterparty

router = APIRouter(prefix="/verification", tags=["verification"])


class VerificationCheckOut(BaseModel):
    field: str
    check_type: str
    status: str  # pass | fail | warning | info
    confidence: int
    message: str
    suggestion: str | None = None


class VerificationResultOut(BaseModel):
    entry_id: str
    checks: list[VerificationCheckOut]
    overall_status: str  # approved | needs_review | rejected
    overall_confidence: int
    enrichment: dict[str, str] | None = None


@router.post("/{entry_id}", response_model=VerificationResultOut)
async def verify_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Верифицировать запись против справочников НСИ."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Запись не найдена")

    meta = entry.metadata_ or {}
    checks: list[VerificationCheckOut] = []
    counterparty_id: UUID | None = None

    inn = (meta.get("inn") or "").strip()
    counterparty_name = meta.get("counterparty") or meta.get("contractor") or ""

    # 1. counterparty_known
    if inn:
        cp_result = await db.execute(
            select(Counterparty)
            .where(Counterparty.company_id == entry.company_id)
            .where(Counterparty.inn == inn)
        )
        cp = cp_result.scalar_one_or_none()
        if cp:
            counterparty_id = cp.id
            checks.append(VerificationCheckOut(
                field="counterparty", check_type="counterparty_known",
                status="pass", confidence=100,
                message=f"Контрагент найден: {cp.name}",
            ))
        else:
            # Fuzzy по имени
            if counterparty_name:
                match = await fuzzy_match_counterparty(db, entry.company_id, counterparty_name)
                if match:
                    counterparty_id = match.id
                    checks.append(VerificationCheckOut(
                        field="counterparty", check_type="counterparty_known",
                        status="warning", confidence=70,
                        message=f"Возможное совпадение: {match.name}",
                        suggestion=f"Проверьте: {match.name} (ИНН: {match.inn})",
                    ))
                else:
                    checks.append(VerificationCheckOut(
                        field="counterparty", check_type="counterparty_known",
                        status="info", confidence=0,
                        message="Контрагент не найден в справочнике",
                    ))

    # 2. inn_checksum
    if inn:
        valid = _validate_inn(inn)
        checks.append(VerificationCheckOut(
            field="inn", check_type="inn_checksum",
            status="pass" if valid else "fail",
            confidence=100,
            message="ИНН корректен" if valid else "Некорректный ИНН",
        ))

    # 3. contract_exists
    if counterparty_id:
        ctr_result = await db.execute(
            select(func.count(Contract.id))
            .where(Contract.company_id == entry.company_id)
            .where(Contract.counterparty_id == counterparty_id)
        )
        ctr_count = ctr_result.scalar() or 0
        if ctr_count > 0:
            checks.append(VerificationCheckOut(
                field="contract", check_type="contract_exists",
                status="pass", confidence=100,
                message=f"Найден договор ({ctr_count})",
            ))
        else:
            checks.append(VerificationCheckOut(
                field="contract", check_type="contract_exists",
                status="warning", confidence=60,
                message="Договор не найден",
            ))

    # Scoring
    fails = sum(1 for c in checks if c.status == "fail")
    warnings = sum(1 for c in checks if c.status == "warning")
    passes = sum(1 for c in checks if c.status == "pass")

    if fails >= 2:
        overall = "rejected"
    elif fails >= 1 or warnings >= 3:
        overall = "needs_review"
    else:
        overall = "approved"

    total = len(checks) or 1
    confidence = round((passes / total) * 100)

    return VerificationResultOut(
        entry_id=str(entry_id),
        checks=checks,
        overall_status=overall,
        overall_confidence=confidence,
    )


def _validate_inn(inn: str) -> bool:
    import re
    if not re.match(r"^\d{10}$|^\d{12}$", inn):
        return False
    digits = [int(d) for d in inn]
    if len(digits) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        s = sum(w[i] * digits[i] for i in range(9))
        return (s % 11) % 10 == digits[9]
    w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    s1 = sum(w1[i] * digits[i] for i in range(10))
    s2 = sum(w2[i] * digits[i] for i in range(11))
    return (s1 % 11) % 10 == digits[10] and (s2 % 11) % 10 == digits[11]
