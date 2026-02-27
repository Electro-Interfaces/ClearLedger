"""Тесты аутентификации /api/auth/*."""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def test_login_success(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "admin@clearledger.ru", "password": "admin123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "admin@clearledger.ru"
    assert data["user"]["role"] == "admin"


async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "admin@clearledger.ru", "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_email(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "test"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


async def test_register_new_user(client: AsyncClient):
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "secret123",
            "name": "Тестовый Пользователь",
            "company_id": "npk",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "newuser@test.com"
    assert data["user"]["name"] == "Тестовый Пользователь"


async def test_register_duplicate_email(client: AsyncClient):
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "admin@clearledger.ru",
            "password": "any123",
            "name": "Дубль",
            "company_id": "npk",
        },
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Me / Refresh
# ---------------------------------------------------------------------------


async def test_get_me_authenticated(auth_client: AsyncClient):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@clearledger.ru"
    assert data["role"] == "admin"


async def test_get_me_no_auth(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


async def test_refresh_token(auth_client: AsyncClient):
    resp = await auth_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@clearledger.ru"
