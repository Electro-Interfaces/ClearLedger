"""
Тесты приглашений сотрудников по email (роль-на-компанию).
SMTP не настроен → dev-режим; сырой токен перехватываем monkeypatch'ем
email_service.send_invite (в ответе/БД его нет — только в письме).
"""
import pytest
from httpx import AsyncClient

from app.services import email_service


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _admin(client: AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={
        "email": "admin@clearledger.ru", "password": "admin123",
    })
    return r.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_invitation_flow(client: AsyncClient, monkeypatch):
    sent = {}

    async def fake_send(to, token, company_name, inviter, role):
        sent["token"] = token
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    # Приглашаем нового сотрудника в npk с ролью admin.
    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "npk", "email": "newhire@test.ru", "role": "admin",
    })
    assert r.status_code == 201, r.text
    token = sent["token"]
    assert token

    # Preview публичен и корректен.
    p = (await client.get(f"/api/invitations/accept/{token}")).json()
    assert p["email"] == "newhire@test.ru"
    assert p["role"] == "admin"
    assert p["user_exists"] is False
    assert p["company_name"]

    # Список pending у админа компании.
    lst = await client.get("/api/invitations", headers=_h(admin), params={"company_id": "npk"})
    assert any(i["email"] == "newhire@test.ru" for i in lst.json())

    # Accept нового пользователя → автологин-токен, роль admin В npk.
    a = await client.post(f"/api/invitations/accept/{token}",
                          json={"name": "New Hire", "password": "secret123"})
    assert a.status_code == 200, a.text
    new_token = a.json()["access_token"]
    me = (await client.get("/api/auth/me", headers=_h(new_token))).json()
    roles = {c["slug"]: c["role"] for c in me["companies"]}
    assert roles.get("npk") == "admin"

    # Токен одноразовый — повторный accept → 404.
    a2 = await client.post(f"/api/invitations/accept/{token}",
                           json={"name": "x", "password": "secret123"})
    assert a2.status_code == 404

    # Приглашение уже-члена → 409.
    dup = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "npk", "email": "newhire@test.ru", "role": "user",
    })
    assert dup.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_invitation_permissions_and_revoke(client: AsyncClient, monkeypatch):
    sent = {}

    async def fake_send(to, token, company_name, inviter, role):
        sent["token"] = token
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    # Обычный сотрудник gig не может приглашать.
    await client.post("/api/users", headers=_h(admin), json={
        "company_id": "gig", "email": "plain2@test.ru", "name": "Plain",
        "password": "secret123", "role": "user",
    })
    plain = (await client.post("/api/auth/login", json={
        "email": "plain2@test.ru", "password": "secret123",
    })).json()["access_token"]
    bad = await client.post("/api/invitations", headers=_h(plain), json={
        "company_id": "gig", "email": "x2@test.ru", "role": "user",
    })
    assert bad.status_code == 403

    # Отзыв приглашения → токен недействителен.
    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "gig", "email": "tobe@test.ru", "role": "user",
    })
    rid = r.json()["id"]
    tok = sent["token"]
    assert (await client.get(f"/api/invitations/accept/{tok}")).status_code == 200
    assert (await client.delete(f"/api/invitations/{rid}", headers=_h(admin))).status_code == 204
    assert (await client.get(f"/api/invitations/accept/{tok}")).status_code == 404
