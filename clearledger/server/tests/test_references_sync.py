"""
Тесты универсального pull контрагентов и договоров (Фаза 1 оси контрагент/договор):
- хелперы маппинга типа и очистки ссылок (без БД);
- _sync_counterparties / _sync_contracts: промо-колонки + raw-снимок, резолв
  владельца договора → контрагент (GUID), scope_type=unassigned по умолчанию и
  его СОХРАНЕНИЕ при ресинхронизации (наш слой охвата, не из 1С).

Запуск: cd server && py -3 -m pytest tests/test_references_sync.py -v
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Company, Contract, Counterparty
from app.services.onec.odata_client import ENTITY_CONTRACTS, ENTITY_COUNTERPARTIES
from app.services.onec.sync_service import (
    OneCSyncService,
    _clean_ref,
    _resolve_cp_type,
)

OWNER = "11111111-1111-1111-1111-111111111111"
CONTRACT_REF = "22222222-2222-2222-2222-222222222222"
ORG = "33333333-3333-3333-3333-333333333333"
EMPTY = "00000000-0000-0000-0000-000000000000"

CP_ROWS = [{
    "Ref_Key": OWNER, "DeletionMark": False, "Description": "Ромашка ООО",
    "НаименованиеПолное": 'ООО "Ромашка"', "ИНН": "7800000001", "КПП": "780001001",
    "КодПоОКПО": "12345678", "ЮридическоеФизическоеЛицо": "ЮридическоеЛицо",
    "ГоловнойКонтрагент_Key": EMPTY,
}]
CONTRACT_ROWS = [{
    "Ref_Key": CONTRACT_REF, "DeletionMark": False, "Номер": "Д-1",
    "Дата": "2026-02-01T00:00:00", "Owner_Key": OWNER, "Организация_Key": ORG,
    "ВидДоговора": "СПоставщиком", "СрокДействия": "2027-01-01T00:00:00",
    "ДоговорЗакрыт": False, "Сумма": 0,
}]


class _FakeClient:
    """Мини-клиент 1С: отдаёт заранее заданные строки по имени сущности."""

    def __init__(self, data: dict) -> None:
        self._data = data

    async def iter_entity(self, entity, *, select=None, orderby=None,
                          filter_expr=None, page_size=500):
        for row in self._data.get(entity, []):
            yield row


def _log():
    return SimpleNamespace(items_processed=0, items_created=0, items_updated=0, items_errors=0)


# ─── чистые хелперы (без БД) ────────────────────────────────────────

def test_resolve_cp_type():
    assert _resolve_cp_type({"ЮридическоеФизическоеЛицо": "ЮридическоеЛицо"}) == "ЮЛ"
    assert _resolve_cp_type({"ЮридическоеФизическоеЛицо": "ФизическоеЛицо"}) == "ФЛ"
    assert _resolve_cp_type({"ИндивидуальныйПредприниматель": True}) == "ИП"
    assert _resolve_cp_type({}) == "ЮЛ"


def test_clean_ref():
    assert _clean_ref(EMPTY) is None
    assert _clean_ref("") is None
    assert _clean_ref(None) is None
    assert _clean_ref("  abc  ") == "abc"


# ─── pull в БД ──────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_sync_counterparties_and_contracts(db):
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    assert company is not None
    conn = SimpleNamespace(company_id=company.id)
    svc = OneCSyncService(db)
    client = _FakeClient({ENTITY_COUNTERPARTIES: CP_ROWS, ENTITY_CONTRACTS: CONTRACT_ROWS})

    await svc._sync_counterparties(client, conn, _log())
    await svc._sync_contracts(client, conn, _log())
    await db.flush()

    cp = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == company.id,
        Counterparty.external_ref == OWNER,
    ))).scalars().first()
    assert cp is not None
    assert cp.full_name == 'ООО "Ромашка"'      # промо
    assert cp.okpo == "12345678"
    assert cp.type == "ЮЛ"
    assert cp.kind == "external"
    assert cp.head_ref is None                    # пустой GUID занулён
    assert cp.raw and cp.raw["ИНН"] == "7800000001"  # полный снимок L1

    ct = (await db.execute(select(Contract).where(
        Contract.company_id == company.id,
        Contract.external_ref == CONTRACT_REF,
    ))).scalars().first()
    assert ct is not None
    assert ct.counterparty_id == OWNER            # резолв владельца → GUID контрагента
    assert ct.organization_id == ORG
    assert ct.kind == "СПоставщиком"
    assert ct.valid_until == "2027-01-01"
    assert ct.is_closed is False
    assert ct.scope_type == "unassigned"          # дефолт, наш слой охвата
    assert ct.raw and ct.raw["ВидДоговора"] == "СПоставщиком"


@pytest.mark.asyncio(loop_scope="session")
async def test_resync_preserves_scope_type(db):
    """Пользователь проставил охват договора — ресинхронизация из 1С его не трёт."""
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    conn = SimpleNamespace(company_id=company.id)
    svc = OneCSyncService(db)
    client = _FakeClient({ENTITY_CONTRACTS: CONTRACT_ROWS})

    await svc._sync_contracts(client, conn, _log())
    await db.flush()
    ct = (await db.execute(select(Contract).where(
        Contract.external_ref == CONTRACT_REF,
    ))).scalars().first()
    assert ct is not None
    ct.scope_type = "company"                     # пользователь задал охват
    await db.flush()

    await svc._sync_contracts(client, conn, _log())  # повторный pull
    await db.flush()
    await db.refresh(ct)
    assert ct.scope_type == "company"             # сохранилось
