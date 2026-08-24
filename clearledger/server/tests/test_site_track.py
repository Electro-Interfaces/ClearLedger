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

    # Поручение по тому же предмету — объекта сети всё ещё нет, а выезд нужен.
    early_errand = Task(company_id=cid, title="Осмотр участка", status="open",
                        subject_ref=f"site:{site.id}",
                        author_id=uuid.UUID(me["id"]))
    db.add(early_errand)
    await db.commit()

    listing = await auth_client.get(f"/api/sites/{site.id}/track",
                                    params={"company_id": str(cid)})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["subject_ref"] == f"site:{site.id}"
    assert {i["title"] for i in body["items"]} == {"Акт выбора площадки", "Осмотр участка"}
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
    assert titles == {"Акт выбора площадки", "Осмотр участка",
                      "Акт ввода", "Выезд на пусконаладку"}
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


async def test_предмет_поручения_проверяется(auth_client: AsyncClient):
    """Ссылка проверяется как у документа: поручение с несуществующим проектом
    потерялось бы молча — запись формально верна, а найти её по проекту нельзя."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    made = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Поручение в никуда",
        "subject_ref": f"site:{uuid.uuid4()}"})
    assert made.status_code == 404, made.text


async def test_лента_работы_отбирается_по_предмету(auth_client: AsyncClient,
                                                   db: AsyncSession):
    """Реестр документов умел отбор по предмету с самого начала, лента — нет, и
    переход «показать всю работу по проекту» приводил на список без единого
    поручения."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    site = EzsSite(company_id=cid, title=f"Отбор {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="construction")
    db.add(site)
    await db.flush()
    kind = await _kind(db, cid)
    ref = f"site:{site.id}"

    db.add_all([
        DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code,
                family="internal", direction="none", title="Договор аренды",
                status="draft", subject_ref=ref),
        Task(company_id=cid, title="Согласовать площадку", status="open",
             subject_ref=ref, author_id=uuid.UUID(me["id"])),
        # Чужая работа: без предмета — в отбор попасть не должна.
        Task(company_id=cid, title="Посторонняя работа", status="open",
             author_id=uuid.UUID(me["id"])),
    ])
    await db.commit()

    body = (await auth_client.get("/api/work", params={
        "company_id": str(cid), "scope": "all", "ref": ref})).json()
    titles = {i["title"] for i in body["work"]}
    assert titles == {"Договор аренды", "Согласовать площадку"}
    assert {i["kind"] for i in body["work"]} == {"doc", "task"}


async def test_предмет_расшифровывается_именем_и_ссылкой(
        auth_client: AsyncClient, db: AsyncSession):
    """Сырая ссылка человеку ничего не говорит: он не отличит проект от договора
    и не поймёт, о какой площадке речь."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    site = EzsSite(company_id=cid, title="Крыгина ул. 95", kind="new_build",
                   stage="construction")
    db.add(site)
    await db.commit()

    ghost = f"site:{uuid.uuid4()}"
    body = (await auth_client.get("/api/docs/refs/resolve", params={
        "company_id": str(cid), "refs": f"site:{site.id},{ghost}"})).json()["refs"]

    assert body[f"site:{site.id}"]["name"] == "Крыгина ул. 95"
    assert body[f"site:{site.id}"]["url"].endswith(str(site.id))
    # Исчезнувшая цель называется прямо: молчание человек прочтёт как «связи
    # нет», хотя связь есть и она сломана.
    assert ghost in body and body[ghost]["name"] is None
