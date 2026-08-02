"""Тесты CRUD компаний /api/companies/*."""

from httpx import AsyncClient


async def test_list_companies(auth_client: AsyncClient):
    resp = await auth_client.get("/api/companies")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Сид держит ровно тот каталог, что в seed.COMPANIES: legacy-компании
    # (НПК, РТИ, ТС-94, ОФ ПТК) убраны 2026-06-27 и не воскресают.
    assert len(data) >= 2
    slugs = {c["slug"] for c in data}
    assert {"gig", "rushydro"} <= slugs


async def test_get_company_by_slug(auth_client: AsyncClient):
    resp = await auth_client.get("/api/companies/gig")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "gig"
    assert data["name"] == "ООО ГИГ (ГазИнвестГрупп)"
    assert data["profile_id"] == "fuel"


async def test_get_company_by_uuid(auth_client: AsyncClient):
    # Получаем UUID из списка
    list_resp = await auth_client.get("/api/companies")
    company = list_resp.json()[0]
    uid = company["id"]

    resp = await auth_client.get(f"/api/companies/{uid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == uid


async def test_create_company(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/companies",
        json={
            "name": "Тест Компания",
            "slug": "test-co",
            "profile_id": "general",
            "color": "#ff0000",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-co"
    assert data["name"] == "Тест Компания"


async def test_create_duplicate_slug(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/companies",
        json={
            "name": "Дубликат",
            "slug": "gig",
            "profile_id": "fuel",
        },
    )
    assert resp.status_code == 409


async def test_update_company(auth_client: AsyncClient):
    resp = await auth_client.patch(
        "/api/companies/gig",
        json={"color": "#0000ff"},
    )
    assert resp.status_code == 200
    assert resp.json()["color"] == "#0000ff"


async def test_get_nonexistent_company(auth_client: AsyncClient):
    resp = await auth_client.get("/api/companies/nonexistent-slug")
    assert resp.status_code == 404
