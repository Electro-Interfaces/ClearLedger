import asyncio
import uuid

import pytest


@pytest.mark.asyncio(loop_scope="session")
async def test_contract_creation_key_replays_one_intention_and_preserves_business_conflicts(auth_client):
    async def post(path, data):
        result = await auth_client.post(f"/api/references/{path}", json=data)
        assert result.status_code == 201, result.text
        return result.json()

    cp = await post("counterparties", {"company_id": "gig", "name": "Тест намерения", "inn": ""})
    org = await post("organizations", {"company_id": "gig", "name": "Своя сторона теста", "inn": "", "prefix": "Т"})
    body = {"company_id": "gig", "number": uuid.uuid4().hex, "date": "2026-01-01", "type": "Аренда",
            "counterpartyId": cp["id"], "organizationId": org["id"], "creationKey": str(uuid.uuid4())}
    results = await asyncio.gather(*[
        auth_client.post("/api/references/contracts", json=body) for _ in range(2)])
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert results[0].json()["id"] == results[1].json()["id"]
    repeated = await post("contracts", body)
    assert repeated["id"] == results[0].json()["id"]
    changed = await auth_client.post("/api/references/contracts", json={**body, "number": "Другой"})
    assert changed.status_code == 409
    duplicate = await auth_client.post("/api/references/contracts", json={**body, "creationKey": str(uuid.uuid4())})
    assert duplicate.status_code == 409  # Другой ключ не разрешает второй паспорт.
