"""Выбор видов писем в личных настройках.

Смысл настройки: канал «почта» отвечает на вопрос «писать ли вообще», а виды —
на вопрос «о чём». До неё человек, которому мешал поток ответов по чужим
задачам, выключал почту целиком и переставал получать «вам поручено».

Проверяется и обратная сторона: почтовому участнику (`mail_only`) письмо —
единственный канал, и настройка его не глушит.
"""
import pytest

from app.models import User
from app.services import notify


def _человек(**kw) -> User:
    return User(email="kto@example.com", name="Кто-то", **kw)


def test_по_умолчанию_приходит_всё():
    # NULL в профиле — поведение до появления настройки: обновление не вправе
    # молча отключить письма, которые человек получал вчера.
    u = _человек(email_notify=None)
    assert notify.email_kinds(u) == set(notify.EMAIL_KINDS)
    for kind in notify.EMAIL_KINDS:
        assert notify.wants_email(u, kind) is True


def test_выбранные_виды_уважаются():
    u = _человек(email_notify=["task_assigned", "digest"])
    assert notify.wants_email(u, "task_assigned") is True
    assert notify.wants_email(u, "digest") is True
    assert notify.wants_email(u, "task_reply") is False
    assert notify.wants_email(u, "task_status") is False


def test_пустой_список_значит_ничего():
    # Осознанный выбор «на почту не писать» отличается от NULL и сохраняется.
    u = _человек(email_notify=[])
    assert notify.email_kinds(u) == set()
    assert notify.wants_email(u, "task_assigned") is False


def test_мусор_в_настройке_не_включает_чужое():
    u = _человек(email_notify=["task_reply", "выдуманное"])
    assert notify.email_kinds(u) == {"task_reply"}


def test_неизвестный_вид_письма_доставляется():
    # Новый вид, которого ещё нет в каталоге, лучше доставить, чем потерять.
    u = _человек(email_notify=["task_assigned"])
    assert notify.wants_email(u, "что_то_новое") is True


def test_почтовому_участнику_пишем_всегда():
    u = _человек(email_notify=[], mail_only=True)
    for kind in notify.EMAIL_KINDS:
        assert notify.wants_email(u, kind) is True


@pytest.mark.asyncio(loop_scope="session")
async def test_профиль_отдаёт_и_принимает_виды(auth_client):
    было = (await auth_client.get("/api/auth/me")).json()["email_notify"]
    assert было == list(notify.EMAIL_KINDS)
    try:
        r = await auth_client.patch("/api/chat/me",
                                    json={"emailNotify": ["digest", "task_assigned"]})
        assert r.status_code == 200, r.text
        # Порядок — каталожный, а не присланный: иначе интерфейс считал бы
        # сохранённое изменённым.
        me = (await auth_client.get("/api/auth/me")).json()
        assert me["email_notify"] == ["task_assigned", "digest"]

        r = await auth_client.patch("/api/chat/me", json={"emailNotify": []})
        assert r.status_code == 200, r.text
        assert (await auth_client.get("/api/auth/me")).json()["email_notify"] == []
    finally:
        await auth_client.patch("/api/chat/me", json={"emailNotify": list(notify.EMAIL_KINDS)})


@pytest.mark.asyncio(loop_scope="session")
async def test_сводка_не_уходит_отказавшемуся(auth_client, db):
    """Отказ от сводки убирает человека из рассылки «Пульса», доступ к экрану остаётся."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models import UserCompany
    from app.services import pulse_digest
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    user = (await db.execute(select(User).where(User.email == "admin@clearledger.ru"))).scalar_one()
    членство = (await db.execute(select(UserCompany).where(
        UserCompany.company_id == cid, UserCompany.user_id == user.id))).scalar_one_or_none()
    if членство is None:
        pytest.skip("суперадмин не состоит в компании сида — рассылку проверяет отдельный стенд")
    было_видно = user.last_seen_at
    user.last_seen_at = datetime.now(timezone.utc) - timedelta(days=1)
    user.email_notify = None
    await db.commit()
    try:
        адреса = await pulse_digest._recipients(db, cid)
        assert user.email in адреса, "по умолчанию сводка приходит"

        user.email_notify = ["task_assigned"]        # сводку отключили
        await db.commit()
        адреса = await pulse_digest._recipients(db, cid)
        assert user.email not in адреса, "отказ от сводки не сработал"
    finally:
        user.email_notify = None
        user.last_seen_at = было_видно
        await db.commit()
