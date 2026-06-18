"""
Тесты каталога типов точек (location_types):
встроенный набор, CRUD кастомных типов, запрет удаления встроенных,
права (не-админ → 403) и изоляция между компаниями.

Запуск: cd server && py -3 -m pytest tests/test_location_types.py -v
"""
import pytest
from httpx import AsyncClient


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _admin_token(client: AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={
        "email": "admin@clearledger.ru", "password": "admin123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _create_user(client: AsyncClient, admin: str, email: str, company: str, role: str) -> str:
    r = await client.post("/api/users", headers=_h(admin), json={
        "company_id": company, "email": email, "name": email.split("@")[0],
        "password": "secret123", "role": role,
    })
    assert r.status_code in (200, 201), r.text
    lr = await client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert lr.status_code == 200, lr.text
    return lr.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_builtin_types_listed(auth_client: AsyncClient):
    r = await auth_client.get("/api/location-types", params={"company_id": "gig"})
    assert r.status_code == 200, r.text
    types = r.json()
    by_code = {t["code"]: t for t in types}
    # Полный встроенный набор присутствует и помечен встроенным.
    for code in ("fuel_station", "ev_charging", "retail", "food", "warehouse", "office", "other"):
        assert code in by_code, f"нет встроенного типа {code}"
        assert by_code[code]["is_builtin"] is True
        assert by_code[code]["company_id"] is None
    # ЭЗС несёт энергетические поля и единицу кВт·ч.
    ev = by_code["ev_charging"]
    assert ev["unit"] == "кВт·ч"
    assert ev["nomenclature_kind"] == "energy"
    field_keys = {f["key"] for f in ev["fields"]}
    assert {"serialNumber", "maxPowerKw", "connectorTypes"}.issubset(field_keys)


@pytest.mark.asyncio(loop_scope="session")
async def test_create_update_delete_custom(auth_client: AsyncClient):
    # Создание кастомного типа.
    r = await auth_client.post("/api/location-types", json={
        "company_id": "gig", "code": "lpg_station", "name": "АГЗС",
        "icon": "Flame", "unit": "л", "nomenclature_kind": "fuel",
        "fields": [{"key": "pressure", "label": "Давление", "type": "number", "unit": "бар"}],
        "sort_order": 15,
    })
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["is_builtin"] is False
    assert created["company_id"] is not None
    type_id = created["id"]

    # Появился в списке компании.
    lst = (await auth_client.get("/api/location-types", params={"company_id": "gig"})).json()
    assert any(t["id"] == type_id for t in lst)

    # Правка названия.
    r = await auth_client.patch(f"/api/location-types/{type_id}", json={"name": "АГЗС (газ)"})
    assert r.status_code == 200 and r.json()["name"] == "АГЗС (газ)"

    # Удаление кастомного.
    r = await auth_client.delete(f"/api/location-types/{type_id}")
    assert r.status_code == 200, r.text
    lst2 = (await auth_client.get("/api/location-types", params={"company_id": "gig"})).json()
    assert not any(t["id"] == type_id for t in lst2)


@pytest.mark.asyncio(loop_scope="session")
async def test_builtin_not_deletable(auth_client: AsyncClient):
    lst = (await auth_client.get("/api/location-types", params={"company_id": "gig"})).json()
    builtin = next(t for t in lst if t["code"] == "fuel_station")
    r = await auth_client.delete(f"/api/location-types/{builtin['id']}")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio(loop_scope="session")
async def test_permissions_and_isolation(client: AsyncClient):
    admin = await _admin_token(client)
    # Обычный пользователь gig (роль user) и пользователь npk.
    user_gig = await _create_user(client, admin, "lt_user@test.ru", "gig", "user")
    user_npk = await _create_user(client, admin, "lt_npk@test.ru", "npk", "user")

    # Член компании читает каталог.
    assert (await client.get("/api/location-types", headers=_h(user_gig),
                             params={"company_id": "gig"})).status_code == 200
    # Не-админ не может создавать тип → 403.
    assert (await client.post("/api/location-types", headers=_h(user_gig), json={
        "company_id": "gig", "code": "x_custom", "name": "X",
    })).status_code == 403
    # Не-член чужой компании не читает её каталог → 403.
    assert (await client.get("/api/location-types", headers=_h(user_npk),
                             params={"company_id": "gig"})).status_code == 403

    # Изоляция: кастомный тип gig не виден в каталоге npk.
    cr = await client.post("/api/location-types", headers=_h(admin), json={
        "company_id": "gig", "code": "gig_only", "name": "Только ГИГ",
    })
    assert cr.status_code == 200, cr.text
    npk_types = (await client.get("/api/location-types", headers=_h(admin),
                                  params={"company_id": "npk"})).json()
    assert not any(t["code"] == "gig_only" for t in npk_types)
    # А в gig — виден.
    gig_types = (await client.get("/api/location-types", headers=_h(admin),
                                  params={"company_id": "gig"})).json()
    assert any(t["code"] == "gig_only" for t in gig_types)
