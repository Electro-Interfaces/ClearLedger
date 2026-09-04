"""Предмет комнаты: разговор по проекту и работа, из него рождённая.

Ловим то, из-за чего сопряжение «Чаты ↔ Трек ↔ Проекты» молча разваливалось:
комната находилась только по совпадению имени (переименовали проект — завелась
вторая, переписка осталась в первой), а поручение из сообщения теряло предмет и
в ленту проекта не попадало — связь с проектом жила лишь в тексте описания.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _site(db: AsyncSession, cid: uuid.UUID) -> EzsSite:
    site = EzsSite(company_id=cid, title=f"Площадка {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="negotiation")
    db.add(site)
    await db.commit()
    return site


async def test_работа_из_разговора_возвращается_в_проект(
        auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    site = await _site(db, cid)
    ref = f"site:{site.id}"

    room = await auth_client.post("/api/chat/rooms", json={
        "type": "group", "name": "Переписка с собственником",
        "participantIds": [], "scopeProduct": "projects", "scopeRef": ref})
    assert room.status_code in (200, 201), room.text
    assert room.json()["scopeRef"] == ref

    msg = await auth_client.post(f"/api/chat/rooms/{room.json()['id']}/messages",
                                 json={"content": "Собственник просит выехать на замер",
                                       "type": "text"})
    assert msg.status_code in (200, 201), msg.text

    made = await auth_client.post(f"/api/chat/messages/{msg.json()['id']}/task",
                                  json={"title": "Выехать на замер"})
    assert made.status_code == 201, made.text

    # Главное: поручение видно в ленте проекта, а не только в общем списке.
    body = (await auth_client.get(f"/api/sites/{site.id}/track",
                                  params={"company_id": str(cid)})).json()
    assert "Выехать на замер" in {i["title"] for i in body["items"]}, body


async def test_комната_проекта_находится_предметом(auth_client: AsyncClient,
                                                   db: AsyncSession):
    """Отбор идёт по предмету, а не по имени: имя правится в паспорте проекта."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    site = await _site(db, cid)
    ref = f"site:{site.id}"

    made = await auth_client.post("/api/chat/rooms", json={
        "type": "group", "name": "Проект ЭЗС-2026-0001",
        "participantIds": [], "scopeRef": ref})
    assert made.status_code in (200, 201), made.text

    rooms = (await auth_client.get("/api/chat/rooms", params={"ref": ref})).json()
    assert [r["id"] for r in rooms] == [made.json()["id"]], rooms

    # Чужой предмет своих чатов не забирает.
    other = (await auth_client.get("/api/chat/rooms",
                                   params={"ref": f"site:{uuid.uuid4()}"})).json()
    assert other == []


async def test_предмет_комнаты_проверяется(auth_client: AsyncClient):
    """Комната с несуществующим проектом молча уехала бы в никуда: формально
    строка верна, а карточка проекта её никогда не покажет."""
    made = await auth_client.post("/api/chat/rooms", json={
        "type": "group", "name": "Комната в никуда", "participantIds": [],
        "scopeRef": f"site:{uuid.uuid4()}"})
    assert made.status_code == 404, made.text
