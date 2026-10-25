"""Границы чатов, которые держались не везде (проверка 25.10.2026).

Четыре правила, каждое из которых уже было записано в коде, но обходилось:

  • позванному «с чистого листа» прошлое закрыто — в ленте закрывалось, а поиск
    отдавал его целиком, с текстом и автором;
  • сторонний участник чаты не заводит — «свой» определялся по `users.company_id`,
    который проставляют КАЖДОМУ при заведении и при приёме приглашения;
  • системный чат пространства не архивируют — запрет перечислял две комнаты из трёх,
    и «Обновления платформы» прятались у всех участников;
  • папка чатов переживает переименование — `PATCH` без состава её опустошал.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import Company, User, UserCompany

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "chat-bounds-123"


async def _человек(db: AsyncSession, cid: uuid.UUID, name: str,
                   party: str = "internal") -> User:
    """Человек пространства: свой сотрудник или внешний участник."""
    user = User(company_id=cid, email=f"bounds-{uuid.uuid4().hex}@example.org",
                name=name, password_hash=hash_password(PASSWORD))
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid, role="company", party_type=party))
    await db.commit()
    return user


async def _вход(client: AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _компания(db: AsyncSession) -> Company:
    company = (await db.execute(select(Company).order_by(Company.created_at))).scalars().first()
    assert company is not None
    return company


async def test_поиск_не_отдаёт_прошлое_позванному_с_чистого_листа(
        client: AsyncClient, db: AsyncSession):
    company = await _компания(db)
    хозяин = await _человек(db, company.id, "Хозяин группы")
    гость = await _человек(db, company.id, "Позванный позже")
    h = await _вход(client, хозяин.email)
    метка = uuid.uuid4().hex[:8]

    room = (await client.post("/api/chat/rooms", headers=h,
                              json={"type": "group", "name": f"История {метка}"})).json()
    await client.post(f"/api/chat/rooms/{room['id']}/messages", headers=h,
                      json={"content": f"до прихода {метка}"})
    r = await client.post(f"/api/chat/rooms/{room['id']}/participants", headers=h,
                          json={"userId": str(гость.id), "seeHistory": False})
    assert r.status_code == 201, r.text

    hg = await _вход(client, гость.email)
    лента = (await client.get(f"/api/chat/rooms/{room['id']}/messages", headers=hg)).json()
    assert all(метка not in (m.get("content") or "") for m in лента), "прошлое видно в ленте"
    найдено = (await client.get(f"/api/chat/search", params={"q": f"до прихода {метка}"},
                                headers=hg)).json()
    assert найдено == [], "поиск отдал переписку, которой нет в ленте"

    # Сообщение после прихода гость и видит, и находит — правило не должно
    # превращаться в «поиск не работает вовсе».
    await client.post(f"/api/chat/rooms/{room['id']}/messages", headers=h,
                      json={"content": f"после прихода {метка}"})
    свежее = (await client.get("/api/chat/search", params={"q": f"после прихода {метка}"},
                               headers=hg)).json()
    assert len(свежее) == 1, свежее


async def test_внешний_участник_чаты_не_заводит(client: AsyncClient, db: AsyncSession):
    company = await _компания(db)
    партнёр = await _человек(db, company.id, "Подрядчик", party="partner")
    свой = await _человек(db, company.id, "Сотрудник")

    hp = await _вход(client, партнёр.email)
    r = await client.post("/api/chat/rooms", headers=hp,
                          json={"type": "group", "name": "Группа подрядчика"})
    assert r.status_code == 403, r.text

    # Свой сотрудник группу по-прежнему заводит: правило запрещает только внешнему.
    hs = await _вход(client, свой.email)
    r = await client.post("/api/chat/rooms", headers=hs,
                          json={"type": "group", "name": "Группа сотрудника"})
    assert r.status_code == 201, r.text


async def test_системные_чаты_пространства_не_архивируются(
        client: AsyncClient, db: AsyncSession):
    company = await _компания(db)
    сотрудник = await _человек(db, company.id, "Участник пространства")
    h = await _вход(client, сотрудник.email)

    комнаты = (await client.get("/api/chat/rooms", headers=h)).json()
    системные = {r["kind"]: r["id"] for r in комнаты if r.get("kind")}
    assert {"general", "news", "platform"} <= set(системные), системные
    for kind in ("general", "news", "platform"):
        r = await client.post(f"/api/chat/rooms/{системные[kind]}/archive", headers=h)
        assert r.status_code == 400, f"{kind}: {r.status_code} {r.text}"


async def test_переименование_папки_сохраняет_её_чаты(client: AsyncClient, db: AsyncSession):
    company = await _компания(db)
    сотрудник = await _человек(db, company.id, "Хозяин папки")
    h = await _вход(client, сотрудник.email)

    room = (await client.post("/api/chat/rooms", headers=h,
                              json={"type": "group", "name": "Чат в папке"})).json()
    папка = (await client.post("/api/chat/folders", headers=h,
                               json={"name": "Папка", "roomIds": [room["id"]]})).json()
    assert папка["roomIds"] == [room["id"]]

    после = (await client.patch(f"/api/chat/folders/{папка['id']}", headers=h,
                                json={"name": "Папка (ред)"})).json()
    assert после["name"] == "Папка (ред)"
    assert после["roomIds"] == [room["id"]], "переименование опустошило папку"

    # Пустой список по-прежнему означает «убрать все чаты» — это осознанное действие.
    пусто = (await client.patch(f"/api/chat/folders/{папка['id']}", headers=h,
                                json={"name": "Папка (ред)", "roomIds": []})).json()
    assert пусто["roomIds"] == []


async def test_карточка_комнаты_показывает_непрочитанные_как_список(
        client: AsyncClient, db: AsyncSession):
    company = await _компания(db)
    автор = await _человек(db, company.id, "Автор")
    читатель = await _человек(db, company.id, "Читатель")
    ha = await _вход(client, автор.email)
    room = (await client.post("/api/chat/rooms", headers=ha,
                              json={"type": "group", "name": "Счётчик"})).json()
    await client.post(f"/api/chat/rooms/{room['id']}/participants", headers=ha,
                      json={"userId": str(читатель.id)})
    await client.post(f"/api/chat/rooms/{room['id']}/messages", headers=ha,
                      json={"content": "первое"})

    hr = await _вход(client, читатель.email)
    список = (await client.get("/api/chat/rooms", headers=hr)).json()
    строка = next(r for r in список if r["id"] == room["id"])
    карточка = (await client.get(f"/api/chat/rooms/{room['id']}", headers=hr)).json()
    assert строка["unreadCount"] == 1
    assert карточка["unreadCount"] == строка["unreadCount"], "карточка расходится со списком"
    assert карточка["lastMessageAt"] == строка["lastMessageAt"]
    assert карточка["lastMessage"] == строка["lastMessage"]
