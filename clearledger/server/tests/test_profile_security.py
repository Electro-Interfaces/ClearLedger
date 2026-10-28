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


# ===== Отсутствие: отпуск, больничный, командировка =====

def _на(день: str):
    from datetime import date
    return date.fromisoformat(день)


def _человек(**kw) -> User:
    return User(email="kto@example.com", name="Кто-то", **kw)


def test_отсутствие_считается_по_границам_включительно():
    from app.services import notify

    u = _человек(away_from=_на("2026-11-03"), away_to=_на("2026-11-17"))
    assert notify.is_away(u, _на("2026-11-03")) is True     # первый день
    assert notify.is_away(u, _на("2026-11-17")) is True     # последний
    assert notify.is_away(u, _на("2026-11-02")) is False
    assert notify.is_away(u, _на("2026-11-18")) is False


def test_одна_дата_тоже_считается():
    from app.services import notify

    ушёл = _человек(away_from=_на("2026-11-03"), away_to=None)
    assert notify.is_away(ушёл, _на("2026-12-31")) is True
    вернётся = _человек(away_from=None, away_to=_на("2026-11-17"))
    assert notify.is_away(вернётся, _на("2026-01-01")) is True
    assert notify.is_away(вернётся, _на("2026-11-18")) is False
    assert notify.is_away(_человек(), _на("2026-11-18")) is False


@pytest.mark.asyncio(loop_scope="session")
async def test_отметка_отсутствия_сохраняется_и_снимается(auth_client):
    try:
        r = await auth_client.patch("/api/chat/me",
                                    json={"awayFrom": "2026-11-03", "awayTo": "2026-11-17"})
        assert r.status_code == 200, r.text
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["away_from"] == "2026-11-03"
        assert me["away_to"] == "2026-11-17"

        # Возвращение раньше ухода не принимается.
        r = await auth_client.patch("/api/chat/me",
                                    json={"awayFrom": "2026-11-17", "awayTo": "2026-11-03"})
        assert r.status_code == 400, r.text
        assert "раньше" in r.text

        # Мусор вместо даты тоже отбивается.
        r = await auth_client.patch("/api/chat/me", json={"awayFrom": "третьего"})
        assert r.status_code == 400, r.text

        # Пустая строка снимает отметку.
        r = await auth_client.patch("/api/chat/me", json={"awayFrom": "", "awayTo": ""})
        assert r.status_code == 200, r.text
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["away_from"] is None and me["away_to"] is None
    finally:
        await auth_client.patch("/api/chat/me", json={"awayFrom": "", "awayTo": ""})


@pytest.mark.asyncio(loop_scope="session")
async def test_в_отпуске_сводка_дня_не_уходит(auth_client, db):
    """Отметка отсутствия убирает человека из рассылки «Пульса»."""
    from datetime import date, datetime, timedelta, timezone

    from app.models import UserCompany
    from app.services import pulse_digest
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    user = (await db.execute(select(User).where(User.id == uuid.UUID(me["id"])))).scalar_one()
    членство = (await db.execute(select(UserCompany).where(
        UserCompany.company_id == cid, UserCompany.user_id == user.id))).scalar_one_or_none()
    if членство is None:
        pytest.skip("суперадмин не состоит в компании сида")
    было_видно = user.last_seen_at
    user.last_seen_at = datetime.now(timezone.utc) - timedelta(days=1)
    user.away_from = user.away_to = None
    await db.commit()
    try:
        assert user.email in await pulse_digest._recipients(db, cid)

        сегодня = date.today()
        user.away_from, user.away_to = сегодня - timedelta(days=1), сегодня + timedelta(days=5)
        await db.commit()
        assert user.email not in await pulse_digest._recipients(db, cid), "сводка ушла в отпуск"
    finally:
        user.away_from = user.away_to = None
        user.last_seen_at = было_видно
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_профиль_показывает_кто_замещает(auth_client, db):
    """Замещение видно в профиле, но заводит его администратор, не сам человек."""
    from datetime import date, timedelta

    from app.models import UserSubstitution

    me = (await auth_client.get("/api/auth/me")).json()
    user = (await db.execute(select(User).where(User.id == uuid.UUID(me["id"])))).scalar_one()
    if user.company_id is None:
        pytest.skip("у учётной записи нет компании по умолчанию")
    assert me["substitute"] is None, "замещения не было, а профиль его показывает"

    зам_id = uuid.uuid4()
    db.add(User(id=зам_id, email=f"zam-{зам_id.hex[:8]}@example.com", name="Заместитель",
                role="user", password_hash="x" * 20))
    await db.flush()
    сегодня = date.today()
    сам = UserSubstitution(company_id=user.company_id, user_id=user.id, deputy_id=зам_id,
                           starts_on=сегодня, ends_on=сегодня + timedelta(days=10),
                           basis="Приказ № 1")
    db.add(сам)
    await db.commit()
    try:
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["substitute"] == "Заместитель"
        assert me["substitute_period"].startswith(сегодня.strftime("%d.%m.%Y"))
    finally:
        await db.execute(UserSubstitution.__table__.delete().where(UserSubstitution.id == сам.id))
        await db.execute(User.__table__.delete().where(User.id == зам_id))
        await db.commit()
