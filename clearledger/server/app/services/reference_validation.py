"""Прежняя native валидация справочников; один владелец для CREATE/PATCH.

Тела helpers перенесены без изменения правил, статусов и порядка обработки.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Counterparty, Organization
from app.services.reference_identity import id_key


def _parse_uuid(val: str, label: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Невалидный {label}")


_CONTRACT_REQ_FIELDS = {
    "signed": "signed", "signedAt": "signed_at", "paymentTermDays": "payment_term_days",
    "isStateContract": "is_state_contract", "igk": "igk", "responsibleId": "responsible_id",
    "signerOur": "signer_our", "signerOurPosition": "signer_our_position", "signerCp": "signer_cp",
    "signerCpPosition": "signer_cp_position", "signerCpBasis": "signer_cp_basis",
}


def _req_val(api: str, v):
    # Пустая строка — очистка поля; ответственный — UUID пользователя.
    if v == "" or v is None:
        return None
    return _parse_uuid(v) if api == "responsibleId" else v


async def _check_type_code(db: AsyncSession, code: str | None) -> str | None:
    """Вид договора — только из справочника contract_types."""
    if not code:
        return None
    from sqlalchemy import text as _t
    ok = (await db.execute(_t("SELECT 1 FROM contract_types WHERE code = :c AND is_active"), {"c": code})).first()
    if not ok:
        raise HTTPException(status_code=422, detail=f"Неизвестный вид договора: {code}")
    return code


async def _validate_contract_parties(db, company_id, counterparty_id, organization_id):
    cp_id = _parse_uuid(str(counterparty_id), "контрагента")
    org_id = _parse_uuid(str(organization_id), "организации")
    cp = await db.get(Counterparty, cp_id)
    if cp is None or id_key(cp.company_id) != id_key(company_id):
        raise HTTPException(400, "Контрагент не найден в справочнике пространства")
    org = await db.get(Organization, org_id)
    if org is None or id_key(org.company_id) != id_key(company_id):
        raise HTTPException(400, "Организация не найдена в справочнике пространства")
    return cp_id, org_id
