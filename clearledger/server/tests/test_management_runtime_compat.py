"""Management adapter: original runtime chat ACL, Unicode and fail-closed errors."""
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import chat_router
from test_management_api import headers, management_data  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_chat_scope_uses_original_router_acl(management_data, monkeypatch):
    """The pre-extraction demo helper and the modern wrapper use the same hook."""
    seen = []

    async def original_scope(user, cid, db):
        seen.append((user.id, cid))
        return "support"

    monkeypatch.setattr(chat_router, "_chat_scope", original_scope)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/overview", headers=headers(management_data),
                                    params={"kind": "chats"})
    assert response.status_code == 200
    assert seen and all(pair == (management_data["reader"].id, management_data["cid"]) for pair in seen)
    assert {row["title"] for row in response.json()["items"]} == {"joined-direct"}


@pytest.mark.parametrize("missing", [False, True])
async def test_missing_or_denied_chat_acl_never_opens_rooms(management_data, monkeypatch, missing):
    async def denied(*args):
        raise HTTPException(403, "private runtime ACL diagnostic")

    if missing:
        monkeypatch.delattr(chat_router, "_chat_scope")
    else:
        monkeypatch.setattr(chat_router, "_chat_scope", denied)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/overview", headers=headers(management_data),
                                    params={"kind": "chats"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["sources"][0]["state"] == ("error" if missing else "forbidden")
    assert "private runtime ACL diagnostic" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("kind", ["tasks", "calendar", "chats"])
@pytest.mark.parametrize("length,status", [(200, 200), (201, 422)])
async def test_unicode_limit_is_codepoints(management_data, kind, length, status):
    params = {"kind": kind, "query": "😀" * length}
    if kind == "calendar":
        params.update(date_from="2026-10-24", date_to="2026-10-24", time_zone="UTC")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/overview", headers=headers(management_data), params=params)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    if status == 200:
        assert response.json()["items"] == []
        assert response.json()["sources"][0]["state"] == "ok"
