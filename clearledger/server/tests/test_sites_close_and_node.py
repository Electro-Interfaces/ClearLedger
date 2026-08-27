"""Выход проекта из работы требует причины; реестр умеет отбирать по узлу маршрута.

Две вещи, которые ломаются молча. Первая: закрыть место без объяснения — значит
через полгода получить тот же адрес и не знать, отказались мы сами или отказали
нам; заказчик так и сформулировал 27.08.2026 — «без комментария уводить объекты в
отказ или замороженные нельзя». Вторая: стадия воронки отвечает «далеко ли до
станции», а узел маршрута — «у кого сейчас работа», и отбора по второму вопросу в
реестре не было вовсе.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers import seed_company_id

from app.models import ProcessSnapshot

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _site(client: AsyncClient, cid: str, address: str) -> dict:
    r = await client.post("/api/sites", params={"company_id": cid}, json={
        "address": address, "city": "Псков", "stage": "negotiation"})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def test_отказ_без_причины_не_проходит(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    site = await _site(auth_client, cid, "ул. Закрытая, 1")

    r = await auth_client.post(f"/api/sites/{site['id']}/stage",
                               params={"company_id": cid}, json={"stage": "archive"})
    assert r.status_code == 200, r.text
    assert r.json()["moved"] is False
    assert "причина" in r.json()["message"].lower()

    r = await auth_client.post(f"/api/sites/{site['id']}/stage", params={"company_id": cid},
                               json={"stage": "archive", "reason": "Нет свободной мощности"})
    assert r.json()["moved"] is True, r.text
    card = (await auth_client.get(f"/api/sites/{site['id']}", params={"company_id": cid})).json()
    assert card["stage"] == "archive"
    assert card["archiveReason"] == "Нет свободной мощности"


async def test_пауза_тоже_требует_причины_и_хранит_её(auth_client: AsyncClient):
    """Раньше причина паузы жила только в тексте события: в карточке — прочерк."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    site = await _site(auth_client, cid, "ул. Отложенная, 2")

    r = await auth_client.post(f"/api/sites/{site['id']}/stage",
                               params={"company_id": cid}, json={"stage": "on_hold"})
    assert r.json()["moved"] is False, r.text

    r = await auth_client.post(f"/api/sites/{site['id']}/stage", params={"company_id": cid},
                               json={"stage": "on_hold", "reason": "Ждём решения собственника"})
    assert r.json()["moved"] is True, r.text
    card = (await auth_client.get(f"/api/sites/{site['id']}", params={"company_id": cid})).json()
    assert card["archiveReason"] == "Ждём решения собственника"


async def test_отбор_по_узлу_маршрута(auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    свой = await _site(auth_client, cid, "ул. Согласуемая, 3")
    чужой = await _site(auth_client, cid, "ул. Посторонняя, 4")

    # Ход ведёт «Поддержка»; в реестр он попадает снимком — его и кладём.
    db.add(ProcessSnapshot(
        company_id=uuid.UUID(cid), subject_type="ezs_site", subject_id=свой["id"],
        payload={"stage": {"code": "ezs_contract_approval", "name": "Согласование договора"}}))
    await db.commit()

    r = await auth_client.get("/api/sites", params={
        "company_id": cid, "node": "ezs_contract_approval"})
    ids = [i["id"] for i in r.json()["items"]]
    assert свой["id"] in ids
    assert чужой["id"] not in ids

    meta = (await auth_client.get("/api/sites/meta/nodes", params={"company_id": cid})).json()
    узел = next(n for n in meta["nodes"] if n["code"] == "ezs_contract_approval")
    assert узел["label"] == "Согласование договора"
    assert узел["count"] >= 1
    # Полнота названа числом: у проектов без единого шага узла нет вовсе.
    assert meta["known"] <= meta["active"]
