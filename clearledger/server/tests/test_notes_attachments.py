"""Приложенный файл виден в строке записи, а не только в карточке.

В записной книжке скриншот и есть содержание записи («вот это письмо», «вот эта
ошибка»). Пока список задач отдавал строку без вложений, лента не могла показать
ни миниатюры, ни даже признака, что к записи что-то приложено, — узнать это можно
было только открыв карточку.
"""
import pytest
from httpx import AsyncClient
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_вложение_записи_приходит_в_строке_списка(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Запись со скриншотом", "visibility": "personal"})
    assert r.status_code == 201, r.text
    note = r.json()

    # Однопиксельный PNG: важен mime, по нему лента решает — миниатюра или строка файла.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d763f8cfc00000030101002d0d0a2d0000000049454e44ae426082")
    r = await auth_client.post(
        f"/api/tasks/{note['id']}/attachments?company_id={cid}",
        files={"file": ("снимок.png", png, "image/png")})
    assert r.status_code == 201, r.text

    rows = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "visibility": "personal"})).json()["tasks"]
    строка = next(t for t in rows if t["id"] == note["id"])

    assert [f["file_name"] for f in строка["attachments"]] == ["снимок.png"]
    assert строка["attachments"][0]["mime_type"] == "image/png"
    assert строка["attachments"][0]["size"] == len(png)


async def test_запись_без_файлов_отдаёт_пустой_список(auth_client: AsyncClient):
    """Отсутствие ключа заставило бы каждую строку списка проверять `?? []`."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Запись без файлов", "visibility": "personal"})
    assert r.status_code == 201, r.text

    rows = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "visibility": "personal"})).json()["tasks"]
    строка = next(t for t in rows if t["id"] == r.json()["id"])

    assert строка["attachments"] == []
