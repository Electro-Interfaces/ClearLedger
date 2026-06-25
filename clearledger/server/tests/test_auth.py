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


async def test_register_requires_superadmin(client: AsyncClient):
    # Саморегистрация закрыта — без авторизации 401/403.
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "x@test.com", "password": "secret123",
            "name": "X", "company_id": "npk",
        },
    )
    assert resp.status_code in (401, 403)


async def test_register_new_user(auth_client: AsyncClient):
    # Суперадмин (admin@clearledger.ru) может регистрировать.
    resp = await auth_client.post(
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


async def test_register_duplicate_email(auth_client: AsyncClient):
    resp = await auth_client.post(
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


# ---------------------------------------------------------------------------
# Нормализация email (регистр + пробелы) — единый канон во всех точках
# ---------------------------------------------------------------------------


async def test_register_normalizes_email(auth_client: AsyncClient):
    # Заглавные буквы и пробелы по краям → сохраняется нормализованным.
    resp = await auth_client.post(
        "/api/auth/register",
        json={
            "email": "  MixedCase@Test.COM ",
            "password": "secret123",
            "name": "Mixed Case",
            "company_id": "npk",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] == "mixedcase@test.com"


async def test_login_email_case_insensitive(client: AsyncClient):
    # Тот же аккаунт (создан выше) логинится при любом регистре.
    resp = await client.post(
        "/api/auth/login",
        json={"email": "MIXEDCASE@TEST.com", "password": "secret123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "mixedcase@test.com"


async def test_register_duplicate_email_case_insensitive(auth_client: AsyncClient):
    # Повторная регистрация в другом регистре — тот же email → 409, не дубль.
    resp = await auth_client.post(
        "/api/auth/register",
        json={
            "email": "MixedCase@test.com",
            "password": "secret123",
            "name": "Dup",
            "company_id": "npk",
        },
    )
    assert resp.status_code == 409


async def test_forgot_password_case_insensitive(client: AsyncClient):
    # Разный регистр не должен ломать поиск пользователя; ответ всегда 200.
    resp = await client.post(
        "/api/auth/forgot-password",
        json={"email": "ADMIN@clearledger.RU"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
