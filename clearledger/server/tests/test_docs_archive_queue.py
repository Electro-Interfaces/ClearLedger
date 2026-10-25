import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import Company, DocAccessGrant, DocCard, DocKind, User, UserCompany

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={
        "email": email, "password": password,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_archive_queue_применяет_права_до_cursor_limit(
    client: AsyncClient, db: AsyncSession,
):
    marker = uuid.uuid4().hex
    company = Company(
        name=f"Архивная очередь {marker}", slug=f"archive-queue-{marker[:12]}",
        profile_id="gig",
    )
    password = "archive-queue-123"
    user = User(
        company=company, email=f"archive-queue-{marker}@example.org",
        name="Архивист очереди", password_hash=hash_password(password),
    )
    db.add_all([company, user])
    await db.flush()
    db.add(UserCompany(
        user_id=user.id, company_id=company.id, role="user", modules=["docs"],
    ))
    kind = DocKind(
        company_id=company.id, code=f"queue_{marker[:8]}", name="Очередь",
        family="internal", direction="none", number_scope="kind_year",
        fields=[], route=[],
    )
    db.add(kind)
    await db.flush()

    docs = []
    for index, storage_until in enumerate((
        date(2019, 12, 31), date(2020, 12, 31),
        date(2021, 12, 31), date(2021, 12, 31), None,
    )):
        doc = DocCard(
            company_id=company.id, kind_id=kind.id, kind_code=kind.code,
            family="internal", direction="none", title=f"Очередь {index}",
            status="archived", confidentiality="company", author_id=user.id,
            storage_until=storage_until, retention_state="archived",
            retention_class="temporary",
        )
        docs.append(doc)
        db.add(doc)
    private = DocCard(
        company_id=company.id, kind_id=kind.id, kind_code=kind.code,
        family="internal", direction="none", title="Нет права чтения",
        status="archived", confidentiality="private",
        storage_until=None, retention_state="archived",
        retention_class="temporary",
    )
    db.add(private)
    await db.flush()
    for doc in [*docs[2:], private]:
        db.add(DocAccessGrant(
            company_id=company.id, scope_type="doc", scope_id=doc.id,
            subject_type="user", subject_id=user.id, permissions=["archive"],
            denied_permissions=[], created_by=user.id,
        ))
    await db.commit()

    headers = await _headers(client, user.email, password)
    first = await client.get("/api/docs/archive/queue", headers=headers, params={
        "company_id": str(company.id), "limit": 2,
    })
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert {row["id"] for row in first_body["documents"]} == {
        str(docs[2].id), str(docs[3].id),
    }
    assert first_body["next_cursor"]

    second = await client.get("/api/docs/archive/queue", headers=headers, params={
        "company_id": str(company.id), "limit": 2,
        "cursor": first_body["next_cursor"],
    })
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["documents"]] == [str(docs[4].id)]
    assert second.json()["next_cursor"] is None

    malformed = await client.get("/api/docs/archive/queue", headers=headers, params={
        "company_id": str(company.id), "cursor": "not-a-cursor",
    })
    assert malformed.status_code == 400


async def test_отбор_очереди_считает_сервер(
    client: AsyncClient, db: AsyncSession,
):
    """Кнопка «Срок истёк» обязана искать по всей очереди, а не по первой странице.

    Раньше отбор шёл в витрине по уже загруженным строкам: при limit=1 человек
    видел «подходящих документов нет», хотя документ с истёкшим сроком лежал
    второй страницей. Поэтому проверяем отбор ВМЕСТЕ с маленьким лимитом.
    """
    marker = uuid.uuid4().hex
    company = Company(
        name=f"Отбор очереди {marker}", slug=f"queue-filter-{marker[:12]}",
        profile_id="gig",
    )
    password = "queue-filter-123"
    user = User(
        company=company, email=f"queue-filter-{marker}@example.org",
        name="Архивист отбора", password_hash=hash_password(password),
    )
    db.add_all([company, user])
    await db.flush()
    db.add(UserCompany(
        user_id=user.id, company_id=company.id, role="admin", modules=["docs"],
    ))
    kind = DocKind(
        company_id=company.id, code=f"qf_{marker[:8]}", name="Отбор",
        family="internal", direction="none", number_scope="kind_year",
        fields=[], route=[],
    )
    db.add(kind)
    await db.flush()

    def карточка(title: str, **kwargs) -> DocCard:
        doc = DocCard(
            company_id=company.id, kind_id=kind.id, kind_code=kind.code,
            family="internal", direction="none", title=title,
            status="archived", confidentiality="company", author_id=user.id,
            retention_class="temporary", **kwargs,
        )
        db.add(doc)
        return doc

    # Срок истёк; стоит ПОСЛЕ свежих по сортировке — значит на первую страницу
    # с маленьким лимитом не попадёт.
    истёк = карточка("Срок истёк", storage_until=date(2019, 12, 31),
                     retention_state="archived")
    карточка("Хранится дальше", storage_until=date(2030, 12, 31),
             retention_state="archived")
    прежний = карточка("Прежняя версия", storage_until=date(2019, 12, 31),
                       retention_state="legacy_review")
    в_работе = карточка("Акт готовится", storage_until=date(2019, 12, 31),
                        retention_state="destruction_ready")
    await db.commit()

    headers = await _headers(client, user.email, password)

    async def очередь(отбор: str, limit: int = 1) -> list[str]:
        найденные: list[str] = []
        cursor = None
        while True:
            params = {"company_id": str(company.id), "limit": limit, "queue": отбор}
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/api/docs/archive/queue",
                                        headers=headers, params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            найденные += [row["id"] for row in body["documents"]]
            cursor = body["next_cursor"]
            if not cursor:
                return найденные

    # Первая страница отбора «срок истёк» не пустая, хотя лимит — одна строка.
    первая = await client.get("/api/docs/archive/queue", headers=headers, params={
        "company_id": str(company.id), "limit": 1, "queue": "due",
    })
    assert первая.status_code == 200, первая.text
    assert первая.json()["documents"], "отбор отдал пустую первую страницу"

    assert str(истёк.id) in await очередь("due")
    assert str(прежний.id) not in await очередь("due"), "прежняя версия уничтожению не подлежит"
    # Документ, по которому готовится акт, препятствия к уничтожению не имеет —
    # он остаётся и в «срок истёк», и в «в процессе» (как считал прежний экран).
    assert str(в_работе.id) in await очередь("due")
    assert await очередь("legacy") == [str(прежний.id)]
    assert await очередь("active") == [str(в_работе.id)]
    assert len(await очередь("all")) == 4

    неизвестный = await client.get("/api/docs/archive/queue", headers=headers, params={
        "company_id": str(company.id), "queue": "кто-то-придумал",
    })
    assert неизвестный.status_code == 400
