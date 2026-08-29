"""Реплика в историю действующего документа.

Право `edit` снимается, как только документ вступает в силу: реквизиты
действующего документа меняют новой редакцией. Вместе с ними запиралась и
реплика — а она нужна ровно тогда, когда документ действует: «созвонились,
срок перенесли», «отдали в бухгалтерию». Документ жил два года без единой
строки в истории.

Проверка держит границу с обеих сторон: реплику по действующему документу
принять, правку реквизитов — отклонить. Состояние ставится напрямую: путь в
силу — это маршрут согласования и подписант, к правилу о реплике отношения он
не имеет, и гонять его здесь значило бы проверять чужое.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocCard
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _действующий(client: AsyncClient, db: AsyncSession) -> tuple[str, str]:
    me = (await client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    await client.post(f"/api/docs/kinds/starter?company_id={cid}")
    kinds = (await client.get("/api/docs/kinds",
                              params={"company_id": cid})).json()["kinds"]
    kind = next(k for k in kinds if k["code"] == "doc_in")

    created = await client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": f"Письмо для реплики {uuid.uuid4().hex[:8]}",
    })
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    row = await db.get(DocCard, uuid.UUID(doc_id))
    row.status = "in_force"
    await db.commit()
    return cid, doc_id


async def test_реплика_по_действующему_документу_принимается(
        auth_client: AsyncClient, db: AsyncSession):
    cid, doc_id = await _действующий(auth_client, db)
    слово = f"созвонились, срок перенесли {uuid.uuid4().hex[:6]}"

    ответ = await auth_client.post(f"/api/docs/{doc_id}/action", json={
        "company_id": cid, "note": слово})
    assert ответ.status_code == 200, (
        "реплику по действующему документу не приняли: " + ответ.text)

    карточка = (await auth_client.get(
        f"/api/docs/{doc_id}", params={"company_id": cid})).json()
    реплики = [e for e in карточка["events"] if e["kind"] == "comment"]
    assert any(e["note"] == слово for e in реплики), (
        "реплика принята, но в истории документа её нет")

    # Витрина берёт разрешение из `actions`: без отдельного пункта она гасит
    # поле, даже когда ручка реплику приняла бы.
    assert "note" in карточка["available_actions"], (
        "у действующего документа нет действия «note» — витрина погасит поле")
    assert "edit" not in карточка["available_actions"], (
        "у действующего документа появилось «edit» — реквизиты открылись")


async def test_реквизиты_действующего_документа_остаются_запертыми(
        auth_client: AsyncClient, db: AsyncSession):
    """Обратная сторона: открыв реплику, нельзя было открыть и правку."""
    cid, doc_id = await _действующий(auth_client, db)

    ответ = await auth_client.post(f"/api/docs/{doc_id}/action", json={
        "company_id": cid, "title": "Тихая подмена заголовка"})
    assert ответ.status_code == 409, (
        "реквизиты действующего документа поддались правке: " + ответ.text)
