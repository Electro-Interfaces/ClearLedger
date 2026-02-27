"""Тесты CRUD и жизненного цикла DataEntry /api/entries/*."""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY_PAYLOAD = {
    "title": "Тестовый документ",
    "category_id": "fuel-purchase",
    "subcategory_id": "fuel-purchase-invoice",
    "company_id": "npk",
    "source": "manual",
    "source_label": "Ручной ввод",
    "metadata": {},
}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_entry(auth_client: AsyncClient):
    resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Тестовый документ"
    assert data["status"] == "new"
    assert data["source"] == "manual"
    assert "id" in data


async def test_list_entries(auth_client: AsyncClient):
    resp = await auth_client.get("/api/entries", params={"company_id": "npk"})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= 1


async def test_get_entry(auth_client: AsyncClient):
    # Создаём запись
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    # Получаем по ID
    resp = await auth_client.get(f"/api/entries/{entry_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == entry_id


async def test_update_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    resp = await auth_client.patch(
        f"/api/entries/{entry_id}",
        json={"title": "Обновлённый документ"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Обновлённый документ"


async def test_delete_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    resp = await auth_client.delete(f"/api/entries/{entry_id}")
    assert resp.status_code == 204

    # Проверяем что удалена
    resp = await auth_client.get(f"/api/entries/{entry_id}")
    assert resp.status_code == 404


async def test_create_entry_no_auth(client: AsyncClient):
    resp = await client.post("/api/entries", json=_ENTRY_PAYLOAD)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_verify_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    resp = await auth_client.post(f"/api/entries/{entry_id}/verify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "verified"


async def test_reject_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    resp = await auth_client.post(
        f"/api/entries/{entry_id}/reject",
        json={"reason": "Некорректные данные"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


async def test_archive_and_restore_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    # Архивировать
    resp = await auth_client.post(f"/api/entries/{entry_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    # Восстановить
    resp = await auth_client.post(f"/api/entries/{entry_id}/restore")
    assert resp.status_code == 200
    assert resp.json()["status"] == "new"


async def test_exclude_and_include_entry(auth_client: AsyncClient):
    create_resp = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
    entry_id = create_resp.json()["id"]

    # Верифицируем сначала
    await auth_client.post(f"/api/entries/{entry_id}/verify")

    # Исключить
    resp = await auth_client.post(f"/api/entries/{entry_id}/exclude")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    # Вернуть
    resp = await auth_client.post(f"/api/entries/{entry_id}/include")
    assert resp.status_code == 200
    assert resp.json()["status"] == "verified"


async def test_transfer_entries(auth_client: AsyncClient):
    # Создаём и верифицируем 2 записи
    ids = []
    for _ in range(2):
        r = await auth_client.post("/api/entries", json=_ENTRY_PAYLOAD)
        eid = r.json()["id"]
        await auth_client.post(f"/api/entries/{eid}/verify")
        ids.append(eid)

    resp = await auth_client.post("/api/entries/transfer", json={"ids": ids})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert set(data["transferred"]) == set(ids)


async def test_get_nonexistent_entry(auth_client: AsyncClient):
    resp = await auth_client.get(
        "/api/entries/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_invalid_entry_id(auth_client: AsyncClient):
    resp = await auth_client.get("/api/entries/not-a-uuid")
    assert resp.status_code == 400
