"""Поручение по сообщению чата.

Половина работы рождается в разговоре без всякого шаблона: «сделай,
пожалуйста». Ловим то, что молча ломается: сообщение теряет связь с работой
(причину потом не найти); одно и то же сообщение превращается в два поручения;
пустое сообщение становится поручением без названия.
"""
import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _room(client: AsyncClient, cid: str) -> dict:
    r = await client.post("/api/chat/rooms", json={
        "company_id": cid, "type": "group",
        "name": f"Обсуждение {uuid.uuid4().hex[:6]}", "member_ids": []})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _say(client: AsyncClient, room_id: str, text: str) -> dict:
    r = await client.post(f"/api/chat/rooms/{room_id}/messages",
                          json={"content": text, "type": "text"})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def test_поручение_из_сообщения_ставится_и_отвечает_в_чат(
        auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    room = await _room(auth_client, cid)
    msg = await _say(auth_client, room["id"], "Починить выгрузку в БП до пятницы")

    r = await auth_client.post(f"/api/chat/messages/{msg['id']}/task", json={
        "title": "Починить выгрузку в БП", "assigneeId": me["id"]})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["number"] and made["title"] == "Починить выгрузку в БП"

    # Задача существует и знает, откуда взялась: в описании остаётся разговор.
    card = (await auth_client.get(f"/api/tasks/{made['taskId']}",
                                  params={"company_id": cid})).json()
    assert card["assignee_id"] == me["id"]
    assert "обсуждения" in (card["description"] or ""), card["description"]

    # В чате остаётся ссылка: разговор и работа связаны с обеих сторон.
    messages = (await auth_client.get(f"/api/chat/rooms/{room['id']}/messages")).json()
    rows = messages["messages"] if isinstance(messages, dict) else messages
    assert any(str(made["number"]) in (m.get("content") or "") for m in rows), rows

    # Второй раз то же сообщение не превращается во второе поручение.
    r = await auth_client.post(f"/api/chat/messages/{msg['id']}/task", json={
        "title": "Починить выгрузку в БП"})
    assert r.status_code == 409, r.text


async def test_пустое_сообщение_поручением_не_становится(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    room = await _room(auth_client, cid)
    msg = await _say(auth_client, room["id"], "ок")

    # «ок» — не поручение: заголовок короче трёх знаков отбивается с причиной.
    r = await auth_client.post(f"/api/chat/messages/{msg['id']}/task", json={})
    assert r.status_code == 400, r.text
