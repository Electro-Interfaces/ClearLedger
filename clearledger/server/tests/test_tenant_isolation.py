"""
Тест мультитенантной изоляции: пользователь компании A не должен видеть/менять
данные компании B. Проверяет единый механизм tenant-scoping (assert_company_member
/ get_owned) на представительных эндпоинтах + список компаний и /auth/me.

Запуск: cd server && py -3 -m pytest tests/test_tenant_isolation.py -v
"""
import uuid

import pytest
from httpx import AsyncClient


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, company: str) -> str:
    """Регистрирует не-суперадмина с членством в company, возвращает токен.
    Если email уже есть (повторный прогон в сессии) — логинится."""
    r = await client.post("/api/auth/register", json={
        "email": email, "name": email.split("@")[0],
        "password": "secret123", "company_id": company,
    })
    if r.status_code == 409:
        r = await client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code in (200, 201), r.text
    return r.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_cross_company_isolation(client: AsyncClient):
    # Два не-суперадмина: A в npk, B в gig.
    a = await _register(client, "iso_a@test.ru", "npk")
    b = await _register(client, "iso_b@test.ru", "gig")

    # /auth/me: A видит только npk и не суперадмин.
    me = (await client.get("/api/auth/me", headers=_h(a))).json()
    assert me["is_superadmin"] is False
    assert [c["slug"] for c in me["companies"]] == ["npk"]

    # --- A создаёт объекты в npk ---
    entry = await client.post("/api/entries", headers=_h(a), json={
        "title": "iso-entry", "category_id": "primary", "subcategory_id": "x",
        "company_id": "npk",
    })
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]

    source = await client.post("/api/sources", headers=_h(a), json={
        "company_id": "npk", "source_type": "sts", "name": "iso-src", "config": {},
    })
    assert source.status_code == 200, source.text
    source_id = source.json()["id"]

    channel = await client.post("/api/channels", headers=_h(a), json={
        "company_id": "npk", "name": "iso-chan",
    })
    assert channel.status_code == 200, channel.text
    channel_id = channel.json()["id"]

    loc_id = uuid.uuid4().hex[:10]
    location = await client.post("/api/locations", headers=_h(a), json={
        "id": loc_id, "company_id": "npk", "code": "ISO1", "name": "iso-loc",
        "type": "fuel_station", "status": "active",
    })
    assert location.status_code == 200, location.text

    mapping = await client.post("/api/reconcile/mappings", headers=_h(a), json={
        "company_id": "npk", "kind": "fuel", "source_key": "iso-k", "target_ref": "ref1",
    })
    assert mapping.status_code == 201, mapping.text
    mapping_id = mapping.json()["id"]

    # --- B (другая компания) НЕ должен достучаться по id → 404 ---
    assert (await client.get(f"/api/entries/{entry_id}", headers=_h(b))).status_code == 404
    assert (await client.patch(f"/api/entries/{entry_id}", headers=_h(b), json={"title": "hack"})).status_code == 404
    assert (await client.post(f"/api/entries/{entry_id}/verify", headers=_h(b))).status_code == 404
    assert (await client.get(f"/api/entries/{entry_id}/lineage", headers=_h(b))).status_code == 404
    assert (await client.get(f"/api/sources/{source_id}", headers=_h(b))).status_code == 404
    assert (await client.patch(f"/api/sources/{source_id}", headers=_h(b), json={"name": "hack"})).status_code == 404
    assert (await client.delete(f"/api/sources/{source_id}", headers=_h(b))).status_code == 404
    assert (await client.get(f"/api/channels/{channel_id}", headers=_h(b))).status_code == 404
    assert (await client.patch(f"/api/channels/{channel_id}", headers=_h(b), json={"status": "paused"})).status_code == 404
    assert (await client.delete(f"/api/channels/{channel_id}", headers=_h(b))).status_code == 404
    assert (await client.patch(f"/api/locations/{loc_id}", headers=_h(b), json={"name": "hack"})).status_code == 404
    assert (await client.delete(f"/api/locations/{loc_id}", headers=_h(b))).status_code == 404
    assert (await client.patch(f"/api/reconcile/mappings/{mapping_id}", headers=_h(b), json={"target_ref": "hack"})).status_code == 404
    assert (await client.delete(f"/api/reconcile/mappings/{mapping_id}", headers=_h(b))).status_code == 404

    # --- B запрашивает списки/создание с чужим company_id=npk → 403 ---
    assert (await client.get("/api/entries", headers=_h(b), params={"company_id": "npk"})).status_code == 403
    assert (await client.get("/api/sources", headers=_h(b), params={"company_id": "npk"})).status_code == 403
    assert (await client.get("/api/channels", headers=_h(b), params={"company_id": "npk"})).status_code == 403
    assert (await client.get("/api/locations", headers=_h(b), params={"company_id": "npk"})).status_code == 403
    assert (await client.get("/api/reconcile/mappings", headers=_h(b), params={"company_id": "npk"})).status_code == 403
    assert (await client.post("/api/entries", headers=_h(b), json={
        "title": "x", "category_id": "primary", "subcategory_id": "x", "company_id": "npk",
    })).status_code == 403

    # --- transfer чужих записей → молча пропущены (count 0) ---
    tr = await client.post("/api/entries/transfer", headers=_h(b), json={"ids": [entry_id]})
    assert tr.status_code == 200 and tr.json()["count"] == 0

    # --- список компаний и доступ к компании ---
    comps_b = (await client.get("/api/companies", headers=_h(b))).json()
    assert [c["slug"] for c in comps_b] == ["gig"]
    assert (await client.get("/api/companies/npk", headers=_h(b))).status_code == 404
    # B не суперадмин → не может создавать компании
    assert (await client.post("/api/companies", headers=_h(b), json={
        "name": "X", "slug": "xco", "profile_id": "fuel",
    })).status_code == 403

    # --- A над своими объектами работает (позитив-контроль) ---
    assert (await client.get(f"/api/entries/{entry_id}", headers=_h(a))).status_code == 200
    assert (await client.get(f"/api/sources/{source_id}", headers=_h(a))).status_code == 200
    assert (await client.get("/api/sources", headers=_h(a), params={"company_id": "npk"})).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_superadmin_sees_all(client: AsyncClient, auth_client: AsyncClient):
    """Демо-админ (суперадмин) видит все компании."""
    me = (await auth_client.get("/api/auth/me")).json()
    assert me["is_superadmin"] is True
    slugs = {c["slug"] for c in me["companies"]}
    assert {"gig", "npk", "rti"}.issubset(slugs)
