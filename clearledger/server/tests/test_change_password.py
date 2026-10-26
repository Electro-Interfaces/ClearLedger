"""Смена своего пароля изнутри сеанса.

Главное, что проверяется: прежние входы гаснут, а текущее окно остаётся
рабочим. Если перепутать порядок — человек сменит пароль и тут же выпадет
на форму входа, а это ровно та ситуация, из-за которой смену пароля
откладывают «на потом» и живут с утёкшим.

Пароль учётной записи возвращается прямо в БД, а не вторым вызовом ручки:
сидовый `admin123` короче сегодняшнего минимума, и через API его обратно
не поставить. Не вернуть — посыплются все наборы, которым нужен вход
(фикстура `auth_client`).
"""
import pytest
from sqlalchemy import func, select

from app.auth import hash_password
from app.models import User

ПОЧТА = "admin@clearledger.ru"
СТАРЫЙ = "admin123"
НОВЫЙ = "ТихийВечер-2026"


async def _вернуть_пароль(db):
    user = (await db.execute(
        select(User).where(func.lower(User.email) == ПОЧТА))).scalar_one()
    user.password_hash = hash_password(СТАРЫЙ)
    await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_change_password_keeps_current_session(auth_client, client, db):
    прежний = auth_client.headers["Authorization"]
    try:
        r = await auth_client.post("/api/auth/change-password",
                                   json={"currentPassword": СТАРЫЙ, "newPassword": НОВЫЙ})
        assert r.status_code == 200, r.text
        свежий = r.json()["access_token"]
        assert свежий

        # Старый токен погашен вместе с прежним паролем.
        r = await client.get("/api/auth/me", headers={"Authorization": прежний})
        assert r.status_code == 401, r.text

        # Новый токен из ответа работает сразу, без повторного входа.
        r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {свежий}"})
        assert r.status_code == 200, r.text

        # Новым паролем можно войти, старым — уже нет.
        r = await client.post("/api/auth/login", json={"email": ПОЧТА, "password": НОВЫЙ})
        assert r.status_code == 200, r.text
        r = await client.post("/api/auth/login", json={"email": ПОЧТА, "password": СТАРЫЙ})
        assert r.status_code == 401, r.text
    finally:
        await _вернуть_пароль(db)


@pytest.mark.asyncio(loop_scope="session")
async def test_change_password_rejects_wrong_and_same(auth_client, db):
    try:
        r = await auth_client.post("/api/auth/change-password",
                                   json={"currentPassword": "не-тот-пароль", "newPassword": НОВЫЙ})
        assert r.status_code == 400, r.text
        assert "Текущий пароль" in r.text

        # Новый, совпадающий с текущим, не проходит (здесь — ещё и по длине).
        r = await auth_client.post("/api/auth/change-password",
                                   json={"currentPassword": СТАРЫЙ, "newPassword": СТАРЫЙ})
        assert r.status_code in (400, 422), r.text

        # Короткий новый пароль отбивает общее правило схемы, а не обработчик.
        r = await auth_client.post("/api/auth/change-password",
                                   json={"currentPassword": СТАРЫЙ, "newPassword": "корот"})
        assert r.status_code == 422, r.text

        # Ни одна неудачная попытка не тронула учётную запись: сеанс жив.
        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 200, r.text
    finally:
        await _вернуть_пароль(db)
