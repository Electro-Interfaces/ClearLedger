"""
Тесты оси договор↔точки (Фаза 2): охват договора (company/locations/unassigned),
двунаправленная навигация контрагент→точки и точка→договоры.

Запуск: cd server && py -3 -m pytest tests/test_contract_scope.py -v
"""
import pytest
from httpx import AsyncClient

LOC1 = "loc-scope-201"
LOC2 = "loc-scope-202"


async def _post(client: AsyncClient, url: str, body: dict) -> dict:
    r = await client.post(url, json=body)
    assert r.status_code in (200, 201), f"{url}: {r.text}"
    return r.json()


async def _organization(client: AsyncClient) -> str:
    """Юрлицо компании: договор ссылается на него по идентификатору.

    Раньше в тесте стояла строка «org-x» — поле было свободным. Теперь это
    ссылка на справочник юрлиц, и произвольная строка до базы не доезжает.
    """
    import uuid as _uuid

    tail = _uuid.uuid4().hex[:6]
    response = await client.post("/api/references/organizations", json={
        "company_id": "gig", "name": f"Юрлицо {tail}",
        "inn": f"78{_uuid.uuid4().int % 10 ** 8:08d}", "prefix": "Ю",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio(loop_scope="session")
async def test_contract_scope_and_navigation(auth_client: AsyncClient):
    org_id = await _organization(auth_client)
    # Две точки
    for lid, code in [(LOC1, "201"), (LOC2, "202")]:
        await _post(auth_client, "/api/locations", {
            "company_id": "gig", "id": lid, "code": code,
            "name": f"АЗС {code}", "type": "fuel_station",
        })
    # Контрагент-арендодатель (ручной → external_ref пуст, связь по нашему UUID)
    cp = await _post(auth_client, "/api/references/counterparties", {
        "company_id": "gig", "inn": "7800000099", "name": "Арендодатель ООО",
    })
    cp_id = cp["id"]

    # Договор аренды (потом охват = LOC1) + договор поставки на всю компанию
    rent = await _post(auth_client, "/api/references/contracts", {
        "company_id": "gig", "number": "АР-1", "date": "2026-02-01",
        "counterpartyId": cp_id, "organizationId": org_id, "type": "СПоставщиком",
    })
    assert rent["scopeType"] == "unassigned"   # дефолт
    supply = await _post(auth_client, "/api/references/contracts", {
        "company_id": "gig", "number": "ПОСТ-1", "date": "2026-02-02",
        "counterpartyId": cp_id, "organizationId": org_id, "type": "СПоставщиком",
        "scopeType": "company",
    })
    assert supply["scopeType"] == "company"

    # Выставить охват аренды = LOC1
    r = await auth_client.put(f"/api/references/contracts/{rent['id']}/scope", json={
        "scopeType": "locations", "locationIds": [LOC1],
    })
    assert r.status_code == 200, r.text
    assert r.json()["scopeType"] == "locations"

    # Точки договора аренды = {LOC1}
    locs = (await auth_client.get(f"/api/references/contracts/{rent['id']}/locations")).json()
    assert {loc["id"] for loc in locs} == {LOC1}

    # Где работает контрагент: есть company-договор → «Вся компания»
    cl = (await auth_client.get(f"/api/references/counterparties/{cp_id}/locations")).json()
    assert cl["scope"] == "company"
    assert cl["contractsCount"] >= 2

    # Договоры точки LOC1: адресный (аренда) + общекомпанейский (поставка)
    lc1 = (await auth_client.get(f"/api/references/locations/{LOC1}/contracts")).json()
    nums1 = {c["number"] for c in lc1["contracts"]}
    assert "АР-1" in nums1 and "ПОСТ-1" in nums1
    assert any(c["companyWide"] for c in lc1["contracts"])           # поставка помечена
    assert any(c["counterpartyName"] == "Арендодатель ООО" for c in lc1["contracts"])

    # Договоры точки LOC2: только общекомпанейский (адресной аренды нет)
    lc2 = (await auth_client.get(f"/api/references/locations/{LOC2}/contracts")).json()
    nums2 = {c["number"] for c in lc2["contracts"]}
    assert "ПОСТ-1" in nums2 and "АР-1" not in nums2


@pytest.mark.asyncio(loop_scope="session")
async def test_scope_company_clears_locations(auth_client: AsyncClient):
    """Смена охвата на company очищает набор точек."""
    org_id = await _organization(auth_client)
    await _post(auth_client, "/api/locations", {
        "company_id": "gig", "id": "loc-scope-301", "code": "301",
        "name": "АЗС 301", "type": "fuel_station",
    })
    cp = await _post(auth_client, "/api/references/counterparties", {
        "company_id": "gig", "inn": "7800000100", "name": "Поставщик-2 ООО",
    })
    ct = await _post(auth_client, "/api/references/contracts", {
        "company_id": "gig", "number": "СМ-1", "date": "2026-03-01",
        "counterpartyId": cp["id"], "organizationId": org_id, "type": "СПоставщиком",
    })
    # сначала locations
    await auth_client.put(f"/api/references/contracts/{ct['id']}/scope", json={
        "scopeType": "locations", "locationIds": ["loc-scope-301"],
    })
    locs = (await auth_client.get(f"/api/references/contracts/{ct['id']}/locations")).json()
    assert len(locs) == 1
    # затем company → точки очищены
    await auth_client.put(f"/api/references/contracts/{ct['id']}/scope", json={
        "scopeType": "company", "locationIds": [],
    })
    locs2 = (await auth_client.get(f"/api/references/contracts/{ct['id']}/locations")).json()
    assert locs2 == []


@pytest.mark.asyncio(loop_scope="session")
async def test_contract_dimensions(auth_client: AsyncClient):
    """Обобщённые грани договора по разрезам (Фаза 3): номенклатура, каналы."""
    cp = await _post(auth_client, "/api/references/counterparties", {
        "company_id": "gig", "inn": "7800000200", "name": "Поставщик-дим ООО",
    })
    ct = await _post(auth_client, "/api/references/contracts", {
        "company_id": "gig", "number": "ДИМ-1", "date": "2026-04-01",
        "counterpartyId": cp["id"], "organizationId": org_id, "type": "Поставка",
    })
    # изначально граней нет
    d0 = (await auth_client.get(f"/api/references/contracts/{ct['id']}/dimensions")).json()
    assert d0["dimensions"] == {}

    # ограничить договор номенклатурой (напр. только ДТ и АИ-92)
    r = await auth_client.put(
        f"/api/references/contracts/{ct['id']}/dimensions/nomenclature",
        json={"refs": ["nom-AI92", "nom-DT", "nom-DT"]},  # дубль схлопнётся
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["dimensions"]["nomenclature"]) == {"nom-AI92", "nom-DT"}

    # + ограничить каналом
    await auth_client.put(
        f"/api/references/contracts/{ct['id']}/dimensions/channel", json={"refs": ["ch-1"]})
    d = (await auth_client.get(f"/api/references/contracts/{ct['id']}/dimensions")).json()
    assert set(d["dimensions"]["nomenclature"]) == {"nom-AI92", "nom-DT"}
    assert d["dimensions"]["channel"] == ["ch-1"]

    # обратная навигация: договоры по элементу разреза
    by_dt = (await auth_client.get(
        "/api/references/dimensions/nomenclature/contracts",
        params={"ref": "nom-DT", "company_id": "gig"})).json()
    assert any(c["id"] == ct["id"] for c in by_dt)
    by_ch = (await auth_client.get(
        "/api/references/dimensions/channel/contracts",
        params={"ref": "ch-1", "company_id": "gig"})).json()
    assert any(c["id"] == ct["id"] for c in by_ch)

    # снять ограничение по номенклатуре (пусто) — канал остаётся
    await auth_client.put(
        f"/api/references/contracts/{ct['id']}/dimensions/nomenclature", json={"refs": []})
    d2 = (await auth_client.get(f"/api/references/contracts/{ct['id']}/dimensions")).json()
    assert "nomenclature" not in d2["dimensions"]
    assert d2["dimensions"]["channel"] == ["ch-1"]
