"""Работа «Трека» в карточке проекта: чем она находится.

Ловим то, из-за чего лента оказалась бы пустой при живой работе: предмет у
проекта два (сам проект и объект сети), и искать надо по обоим — объект
появляется только со вводом в эксплуатацию, а бумаги нужны с первого дня.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocCard, DocKind, EzsSite, ServiceLocation, Task
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _kind(db: AsyncSession, cid: uuid.UUID) -> DocKind:
    kind = DocKind(company_id=cid, code=f"probe{uuid.uuid4().hex[:6]}",
                   name="Проверка", family="internal", direction="none")
    db.add(kind)
    await db.flush()
    return kind


async def test_лента_проекта_находит_работу_обоими_предметами(
        auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))

    site = EzsSite(company_id=cid, title=f"Проверка ленты {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="construction")
    db.add(site)
    await db.flush()
    kind = await _kind(db, cid)

    # Документ по проекту — объекта у площадки ещё нет.
    early = DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code,
                    family="internal", direction="none",
                    title="Акт выбора площадки", status="draft",
                    subject_ref=f"site:{site.id}")
    db.add(early)
    await db.commit()

    listing = await auth_client.get(f"/api/sites/{site.id}/track",
                                    params={"company_id": str(cid)})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["subject_ref"] == f"site:{site.id}"
    assert [i["title"] for i in body["items"]] == ["Акт выбора площадки"]
    assert body["object_id"] is None

    # Площадка стала объектом сети — работа по объекту попадает в ту же ленту.
    # `code` у объекта обязателен: без него вставка падает, а не молча проходит.
    location = ServiceLocation(id=f"ezs-{uuid.uuid4().hex[:16]}", company_id=cid,
                               code=f"P-{uuid.uuid4().hex[:6]}",
                               name="Проверочная площадка")
    db.add(location)
    await db.flush()
    site.location_id = location.id
    later = DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code,
                    family="internal", direction="none",
                    title="Акт ввода", status="draft", object_id=location.id)
    errand = Task(company_id=cid, title="Выезд на пусконаладку", status="open",
                  object_id=location.id, author_id=uuid.UUID(me["id"]))
    db.add_all([later, errand])
    await db.commit()

    body = (await auth_client.get(f"/api/sites/{site.id}/track",
                                  params={"company_id": str(cid)})).json()
    titles = {i["title"] for i in body["items"]}
    assert titles == {"Акт выбора площадки", "Акт ввода", "Выезд на пусконаладку"}
    assert body["object_id"] == location.id
    # Документы и поручения идут вместе: два списка человек складывал бы в уме.
    assert {i["kind"] for i in body["items"]} == {"doc", "task"}


async def test_проект_законный_предмет_документа(auth_client: AsyncClient,
                                                 db: AsyncSession):
    """Ссылка на проект проверяется, как договор или объект: с несуществующим
    проектом документ подшился бы в пустоту и потерялся молча."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    kind = await _kind(db, cid)
    await db.commit()

    made = await auth_client.post("/api/docs", json={
        "company_id": str(cid), "kind_id": str(kind.id),
        "title": "Документ в никуда", "subject_ref": f"site:{uuid.uuid4()}"})
    assert made.status_code == 404, made.text


async def test_ленты_нет_у_чужого_проекта(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    missing = await auth_client.get(f"/api/sites/{uuid.uuid4()}/track",
                                    params={"company_id": cid})
    assert missing.status_code == 404, missing.text
