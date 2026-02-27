"""Тесты статистики /api/stats/*."""

from httpx import AsyncClient


async def test_kpi_returns_structure(auth_client: AsyncClient):
    resp = await auth_client.get(
        "/api/stats/kpi", params={"company_id": "npk"}
    )
    assert resp.status_code == 200
    data = resp.json()
    # API возвращает snake_case (populate_by_name=True, но сериализация по alias зависит от настройки)
    expected_keys = {"uploaded_today", "total_verified", "in_processing", "errors", "transferred_today"}
    alt_keys = {"uploadedToday", "totalVerified", "inProcessing", "errors", "transferredToday"}
    assert expected_keys <= set(data) or alt_keys <= set(data)


async def test_category_stats(auth_client: AsyncClient):
    resp = await auth_client.get(
        "/api/stats/categories", params={"company_id": "npk"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


async def test_kpi_no_auth(client: AsyncClient):
    resp = await client.get(
        "/api/stats/kpi", params={"company_id": "npk"}
    )
    assert resp.status_code in (401, 403)
