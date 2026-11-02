"""Regression пустого ИНН: настоящие native producers, SQL и HTTP.

Файл копируется без изменений на immutable be5da264 для failed baseline.
Тесты не подменяют command, matcher, SQL или обработку IntegrityError.
"""
import os
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_COUNTERPARTY_COMMAND_TESTS") != "1":
    pytest.skip("Требуется RUN_COUNTERPARTY_COMMAND_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_COUNTERPARTY_COMMAND_TESTS"):
    raise RuntimeError(error)

from sqlalchemy import select

from app.models import Contract, CorporateClient, DataEntry
from app.services.counterparty_commands import create_imported_counterparty
from app.services.reference_identity import CounterpartyIndex
from tests.test_counterparty_commands import http_world, imported, link, parties, world

pytestmark = pytest.mark.asyncio(loop_scope="session")

NAMES = ['ООО «Новый участник»', 'АО «Новый участник»']


async def references(w):
    """Наблюдаемые идентификаторы/значения вокруг импорта, без проверок helper."""
    contracts = (await w.db.execute(select(Contract).where(Contract.company_id == w.cid))).scalars().all()
    entries = (await w.db.execute(select(DataEntry).where(DataEntry.company_id == w.cid))).scalars().all()
    return (
        {c.id: (c.counterparty_id, c.organization_id, c.number, c.date, c.type, c.amount_limit)
         for c in contracts},
        {e.id: (e.source_id, e.source_label, e.layer, e.derived_from_entry_id) for e in entries},
    )


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_native_import_two_new_legal_forms_without_inn_and_replay(world, producer):
    w = world
    result = await imported(w, producer, NAMES)
    assert result["counterparties"] == 2
    saved = await parties(w)
    assert len(saved) == 2 and {p.name for p in saved} == set(NAMES)
    assert all(p.inn is None and p.kpp is None for p in saved)
    ids = {p.name: p.id for p in saved}
    raw = {p.id: p.raw for p in saved}
    assert all(p.raw == {"referenceIdentity": {"name": p.name, "inn": ""}} for p in saved)
    before = await references(w)
    result = await imported(w, producer, NAMES)
    assert result.get("counterparties", 0) == 0
    saved = await parties(w)
    assert {p.name: p.id for p in saved} == ids and {p.id: p.raw for p in saved} == raw
    assert await references(w) == before
    await w.db.rollback()


async def test_native_link_two_new_legal_forms_without_inn_and_replay(http_world):
    w = http_world
    w.membership.role = "admin"
    w.client_row.name = NAMES[0]
    other = CorporateClient(company_id=w.cid, name=NAMES[1], phone="+70000000001", ext_id=uuid.uuid4().hex)
    w.db.add(other)
    await w.db.commit()
    response = await link(w, apply="true", only="corporate_client")
    assert response.status_code == 200, response.text
    assert response.json()["totals"] == {"created": 2, "linked": 2}
    saved = await parties(w)
    assert len(saved) == 2 and {p.name for p in saved} == set(NAMES)
    assert all(p.inn is None and p.kpp is None for p in saved)
    ids = {p.name: p.id for p in saved}
    raw = {p.id: p.raw for p in saved}
    assert all(p.raw == {"referenceIdentity": {"name": p.name, "inn": ""}} for p in saved)
    await w.db.refresh(w.client_row)
    await w.db.refresh(other)
    assert (w.client_row.counterparty_id, other.counterparty_id) == (ids[NAMES[0]], ids[NAMES[1]])
    response = await link(w, apply="true", only="corporate_client")
    assert response.status_code == 200 and response.json()["totals"] == {"created": 0, "linked": 0}
    saved = await parties(w)
    assert {p.name: p.id for p in saved} == ids and {p.id: p.raw for p in saved} == raw


@pytest.mark.parametrize("source", ["", " ", "0", "неизвестно", "7712345678", "1" * 25])
async def test_creation_converts_only_exact_empty_inn_and_preserves_full_source(world, source):
    w = world
    row = await create_imported_counterparty(
        w.db, w.cid, CounterpartyIndex(), name="ООО Источник", inn=source,
        cp_type="ЮЛ", alias=None,
    )
    await w.db.refresh(row)
    assert row.inn == (None if source == "" else source[:20])
    assert row.raw == {"referenceIdentity": {"name": "ООО Источник", "inn": source}}
    await w.db.rollback()
