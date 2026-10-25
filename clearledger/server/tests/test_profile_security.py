"""Что человек видит и может сделать со своей учётной записью сам.

Раньше единственной реакцией на подозрение «кто-то заходил под моей учёткой»
было «выйти на всех устройствах» вслепую: ни списка входов, ни списка
устройств человек не видел. Здесь проверяется, что он видит СВОИ события и
отвязывает СВОИ устройства — и ничего чужого.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import AuditEvent, ChatPushSubscription, User
from app.services import user_agent as ua_service
from app.services.phone_e164 import pretty


def test_устройство_узнаётся_по_строке_браузера():
    chrome = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    iphone = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
    edge = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0")
    assert ua_service.describe(chrome) == "Chrome · Windows"
    assert ua_service.describe(iphone) == "Safari · iPhone"
    # Edge представляется Chrome — порядок разбора важнее полноты.
    assert ua_service.describe(edge) == "Edge · Windows"
    assert ua_service.describe(None) == "Неизвестное устройство"
    assert ua_service.describe("curl/8.5.0") == "Неизвестное устройство"


def test_строка_устройства_укорачивается():
    assert ua_service.short("  Chrome\n  141 ") == "Chrome 141"
    assert ua_service.short("x" * 500, 300) == "x" * 300
    assert ua_service.short(None) is None


def test_номер_приводится_к_единому_виду():
    assert pretty("89001234567") == "+7 900 123-45-67"
    assert pretty("+7(999) 999 99-95") == "+7 999 999-99-95"
    assert pretty("8 (812) 000-00-00 доб 123") == "+7 812 000-00-00, доб. 123"
    # Не распознали — не выбрасываем: человек мог записать внутренний номер.
    assert pretty("внутренний 1234") == "внутренний 1234"
    assert pretty("  ") is None
    assert pretty(None) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_профиль_показывает_свои_входы(auth_client, db):
    me = (await auth_client.get("/api/auth/me")).json()
    мой = (await db.execute(select(User).where(User.id == uuid.UUID(me["id"])))).scalar_one()
    r = await auth_client.get("/api/auth/security/logins")
    assert r.status_code == 200, r.text
    входы = r.json()["logins"]
    # Фикстура логинится — хотя бы один вход обязан быть.
    assert входы, "список входов пуст, хотя вход только что был"
    последний = входы[0]
    assert последний["action"].startswith("auth.")
    assert последний["label"]
    assert последний["at"]

    # Чужое событие в выдачу не попадает.
    чужой = str(uuid.uuid4())
    db.add(AuditEvent(company_id=мой.company_id, user_id=чужой,
                      user_name="Кто-то другой", action="auth.login",
                      details="203.0.113.7 · Chrome/141 Windows NT 10.0"))
    await db.commit()
    try:
        входы = (await auth_client.get("/api/auth/security/logins")).json()["logins"]
        assert all(в["ip"] != "203.0.113.7" for в in входы), "видно чужой вход"
    finally:
        await db.execute(AuditEvent.__table__.delete().where(AuditEvent.user_id == чужой))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_устройства_видны_и_отвязываются(auth_client, db):
    me = (await auth_client.get("/api/auth/me")).json()
    мой = (await db.execute(select(User).where(User.id == uuid.UUID(me["id"])))).scalar_one()
    чужой_id = uuid.uuid4()
    db.add(User(id=чужой_id, email=f"sosed-{чужой_id.hex[:8]}@example.com",
                name="Сосед", role="user", password_hash="x" * 20))
    await db.flush()
    моё = ChatPushSubscription(
        user_id=мой.id, endpoint=f"https://push.example/{uuid.uuid4()}",
        p256dh="k", auth="a",
        user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/141.0.0.0 Safari/537.36")
    чужое = ChatPushSubscription(
        user_id=чужой_id, endpoint=f"https://push.example/{uuid.uuid4()}",
        p256dh="k", auth="a", user_agent="Mozilla/5.0 (Android) Chrome/141")
    db.add_all([моё, чужое])
    await db.commit()
    try:
        устройства = (await auth_client.get("/api/auth/security/devices")).json()["devices"]
        мои_id = {d["id"] for d in устройства}
        assert str(моё.id) in мои_id
        assert str(чужое.id) not in мои_id, "видно чужое устройство"
        назван = next(d for d in устройства if d["id"] == str(моё.id))
        assert назван["device"] == "Chrome · Windows"

        # Чужое не отвязывается: ручка не находит его по своему user_id.
        r = await auth_client.delete(f"/api/auth/security/devices/{чужое.id}")
        assert r.status_code == 204, r.text
        осталось = await db.scalar(select(func.count()).select_from(ChatPushSubscription)
                                   .where(ChatPushSubscription.id == чужое.id))
        assert осталось == 1, "отвязали чужое устройство"

        # Своё отвязывается.
        r = await auth_client.delete(f"/api/auth/security/devices/{моё.id}")
        assert r.status_code == 204, r.text
        осталось = await db.scalar(select(func.count()).select_from(ChatPushSubscription)
                                   .where(ChatPushSubscription.id == моё.id))
        assert осталось == 0
    finally:
        await db.execute(ChatPushSubscription.__table__.delete().where(
            ChatPushSubscription.id.in_([моё.id, чужое.id])))
        await db.execute(User.__table__.delete().where(User.id == чужой_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_телефон_сохраняется_в_едином_виде(auth_client):
    было = (await auth_client.get("/api/auth/me")).json()
    try:
        r = await auth_client.patch("/api/chat/me", json={"phoneMobile": "89001234567",
                                                          "phoneOffice": "8 (812) 000-00-00 доб 123"})
        assert r.status_code == 200, r.text
        assert r.json()["phoneMobile"] == "+7 900 123-45-67"
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["phone_mobile"] == "+7 900 123-45-67"
        assert me["phone_office"] == "+7 812 000-00-00, доб. 123"
    finally:
        await auth_client.patch("/api/chat/me", json={
            "phoneMobile": было.get("phone_mobile") or "",
            "phoneOffice": было.get("phone_office") or ""})
