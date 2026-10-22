import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Company, Counterparty
from app.services.onec.sync_service import OneCSyncService


@pytest.mark.asyncio(loop_scope="session")
async def test_explicit_null_clears_nullable_fields_and_survives_onec(auth_client, db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    company_id = company.id
    name = f"Тест очистки {uuid.uuid4().hex[:8]}"
    response = await auth_client.post("/api/references/counterparties", json={
        "company_id": "gig", "name": name, "inn": "7712345678", "kpp": "771201001",
        "shortName": "Краткое", "fullName": "Полное", "phone": "+79991234567", "email": "test@example.com",
    })
    assert response.status_code == 201, response.text
    party_id = uuid.UUID(response.json()["id"])
    row = {"Ref_Key": str(uuid.uuid4()), "Description": name,
           "ИНН": "7712345678", "КПП": "771201001", "НаименованиеПолное": "Полное из 1С"}

    class Source:
        async def iter_entity(self, entity, **kwargs):
            yield row

    connection = SimpleNamespace(id=uuid.uuid4(), company_id=company_id)
    def log():
        return SimpleNamespace(items_processed=0, items_created=0, items_updated=0, items_errors=0)

    await OneCSyncService(db)._sync_counterparties(Source(), connection, log())
    await db.commit()
    fields = {"kpp": None, "shortName": None, "fullName": None, "phone": None, "email": None}
    response = await auth_client.patch(f"/api/references/counterparties/{party_id}", json=fields)
    assert response.status_code == 200, response.text
    assert all(response.json()[field] is None for field in fields)
    await db.rollback()
    stats = await OneCSyncService(db)._sync_counterparties(Source(), connection, log())
    assert stats["created"] == 0 and stats["updated"] == 1
    party = await db.get(Counterparty, party_id)
    assert party.kpp is None and party.full_name is None
    assert {"kpp", "short_name", "full_name", "phone", "email"} <= set(party.manual_overrides)
