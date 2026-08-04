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

    async def fake_send(to, token, company_name, inviter, role, expires_at=None):
        sent["token"] = token
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    # Приглашаем нового сотрудника в rushydro с ролью admin.
    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "rushydro", "email": "newhire@test.ru", "role": "admin",
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
    lst = await client.get("/api/invitations", headers=_h(admin), params={"company_id": "rushydro"})
    assert any(i["email"] == "newhire@test.ru" for i in lst.json())

    # Accept нового пользователя → автологин-токен, роль admin В rushydro.
    a = await client.post(f"/api/invitations/accept/{token}",
                          json={"name": "New Hire", "password": "secret123"})
    assert a.status_code == 200, a.text
    new_token = a.json()["access_token"]
    me = (await client.get("/api/auth/me", headers=_h(new_token))).json()
    roles = {c["slug"]: c["role"] for c in me["companies"]}
    assert roles.get("rushydro") == "admin"

    # Токен одноразовый — повторный accept → 410 «приглашение уже принято».
    a2 = await client.post(f"/api/invitations/accept/{token}",
                           json={"name": "x", "password": "secret123"})
    assert a2.status_code == 410

    # Приглашение уже-члена → 409.
    dup = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "rushydro", "email": "newhire@test.ru", "role": "user",
    })
    assert dup.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_invitation_permissions_and_revoke(client: AsyncClient, monkeypatch):
    sent = {}

    async def fake_send(to, token, company_name, inviter, role, expires_at=None):
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
    # Отозванное приглашение — 410 с причиной, а не безликое «не найдено».
    assert (await client.get(f"/api/invitations/accept/{tok}")).status_code == 410


@pytest.mark.asyncio(loop_scope="session")
async def test_принадлежность_партнёра_доезжает_из_приглашения_в_членство(
    client: AsyncClient, monkeypatch,
):
    """Приглашённый партнёр должен попасть в раздел «Компании», а не в «Сотрудники».

    Ломалось так: принадлежность ставили ПОСЛЕ входа, поэтому принявший приглашение
    представитель подрядчика появлялся среди сотрудников организации и оставался там,
    пока кто-нибудь не переключит ему тип вручную.
    """
    sent = {}

    async def fake_send(to, token, company_name, inviter, role, expires_at=None):
        sent["token"] = token
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "rushydro", "email": "partner-rep@test.ru", "role": "user",
        "party_type": "partner",
    })
    assert r.status_code == 201, r.text
    assert r.json()["party_type"] == "partner"

    # Список приглашений тоже отдаёт принадлежность — иначе в таблице не видно,
    # кого именно ждём: своего сотрудника или человека со стороны.
    lst = (await client.get("/api/invitations", headers=_h(admin),
                            params={"company_id": "rushydro"})).json()
    assert any(i["email"] == "partner-rep@test.ru" and i["party_type"] == "partner" for i in lst)

    a = await client.post(f"/api/invitations/accept/{sent['token']}",
                          json={"name": "Partner Rep", "password": "secret123"})
    assert a.status_code == 200, a.text

    members = (await client.get("/api/users", headers=_h(admin),
                                params={"company_id": "rushydro"})).json()
    rep = next(m for m in members if m["email"] == "partner-rep@test.ru")
    assert rep["party_type"] == "partner"


@pytest.mark.asyncio(loop_scope="session")
async def test_чужая_организация_в_приглашении_отбивается(client: AsyncClient, monkeypatch):
    """`resolve_org_id` не даёт привязать участника к контрагенту чужого пространства:
    иначе внешний человек был бы подписан в чатах организацией, которой в его компании
    не существует."""
    async def fake_send(to, token, company_name, inviter, role, expires_at=None):
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "rushydro", "email": "ghost-org@test.ru", "role": "user",
        "party_type": "partner",
        "organization_id": "00000000-0000-0000-0000-000000000001",
    })
    assert r.status_code == 404, r.text


@pytest.mark.asyncio(loop_scope="session")
async def test_приглашённый_не_упирается_в_неверный_пароль(client: AsyncClient, monkeypatch):
    """Человек, которого пригласили, но который не прошёл по ссылке, в системе ещё не
    существует. Раньше вход отвечал ему «неверный email или пароль», а восстановление
    пароля молчало — тупик, из которого выводил только администратор."""
    sent = {}

    async def fake_send(to, token, company_name, inviter, role, expires_at=None):
        sent["token"] = token
        return False

    monkeypatch.setattr(email_service, "send_invite", fake_send)
    admin = await _admin(client)

    r = await client.post("/api/invitations", headers=_h(admin), json={
        "company_id": "rushydro", "email": "waiting@test.ru", "role": "user",
    })
    assert r.status_code == 201, r.text
    first_token = sent["token"]

    # Вход: вместо «неверный email или пароль» — что делать дальше.
    login = await client.post("/api/auth/login", json={
        "email": "waiting@test.ru", "password": "любой",
    })
    assert login.status_code == 401
    assert "приглашение" in login.json()["detail"].lower()

    # «Забыли пароль?» высылает приглашение заново, новой ссылкой.
    sent.clear()
    f = await client.post("/api/auth/forgot-password", json={"email": "waiting@test.ru"})
    assert f.status_code == 200
    assert sent.get("token") and sent["token"] != first_token
    assert (await client.get(f"/api/invitations/accept/{sent['token']}")).status_code == 200
    assert (await client.get(f"/api/invitations/accept/{first_token}")).status_code == 404
