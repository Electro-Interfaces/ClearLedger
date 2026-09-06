import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import literal_column
from sqlalchemy.dialects import postgresql

from app.models import DocCard, DocKind, User
from app.routers import docs_router as router
from app.services import doc_approvals


@pytest.fixture
def editing(monkeypatch):
    cid, uid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    version = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
    doc = DocCard(id=did, company_id=cid, kind_id=uuid.uuid4(), title="До правки",
                  status="draft", approval_status="none", approval_round=0,
                  created_at=version, due_at=version, external_date=date(2026, 9, 5), attrs={})
    user = User(id=uid, name="Проверяющий", email="qa@example.invalid")
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: doc))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    monkeypatch.setattr(router, "assert_company_product", AsyncMock(return_value=cid))
    monkeypatch.setattr(router, "_doc_or_404", AsyncMock(return_value=doc))
    monkeypatch.setattr(router, "_assert_doc_permission", AsyncMock())
    monkeypatch.setattr(router, "_kind_or_404", AsyncMock(return_value=DocKind(fields=[], route=[])))
    monkeypatch.setattr(router, "_supersede_pending_acquaints", AsyncMock())
    monkeypatch.setattr(router, "_card_out", lambda value: {"title": value.title, "due_at": value.due_at,
                                                         "external_date": value.external_date})
    return cid, doc, user, db


@pytest.mark.asyncio
async def test_конфликт_не_перезаписывает_реквизиты(editing):
    cid, doc, user, db = editing
    payload = router.ActionIn(company_id=str(cid), title="Устаревшая правка",
                              expected_edit_version=doc.created_at - timedelta(seconds=1))
    with pytest.raises(HTTPException) as error:
        await router.doc_action(str(doc.id), payload, db, user)
    assert error.value.status_code == 409
    assert doc.title == "До правки"
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_явное_очищение_дат_сохраняется_одним_действием(editing):
    cid, doc, user, db = editing
    payload = router.ActionIn(company_id=str(cid), due_at=None, external_date=None,
                              expected_edit_version=doc.created_at)
    result = await router.doc_action(str(doc.id), payload, db, user)
    assert result["due_at"] is None and result["external_date"] is None
    assert doc.updated_at > doc.created_at
    assert {call.args[0].note for call in db.add.call_args_list} == {"due_at", "external_date"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_отсутствующие_даты_не_очищаются(editing):
    cid, doc, user, db = editing
    original = (doc.due_at, doc.external_date)
    await router.doc_action(str(doc.id), router.ActionIn(company_id=str(cid), title="После правки"), db, user)
    assert (doc.due_at, doc.external_date) == original


@pytest.mark.asyncio
async def test_маршрут_показывает_пустой_шаг_и_недостижимый_кворум(monkeypatch):
    db, cid, uid = MagicMock(), uuid.uuid4(), uuid.uuid4()
    doc = DocCard(attrs={})
    route = [{"code": "check", "name": "Проверка", "actors": [{"by": "user", "ref": str(uid)}], "quorum": "2", "mode": "parallel", "sla_hours": 24}]
    monkeypatch.setattr(doc_approvals, "resolve_actors", AsyncMock(return_value=[]))
    preview = await doc_approvals.preview_route(db, cid, doc, route)
    assert len(preview["problems"]) == 2
    assert preview["steps"][0]["people"] == []
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_изменение_участника_меняет_подтверждение_маршрута(monkeypatch):
    cid, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(name="Анна", email="qa@example.invalid"))
    resolver = AsyncMock(return_value=[("user", str(first), first)])
    monkeypatch.setattr(doc_approvals, "resolve_actors", resolver)
    route = [{"code": "check", "name": "Проверка", "actors": [{"by": "role", "ref": str(uuid.uuid4())}]}]
    before = await doc_approvals.preview_route(db, cid, DocCard(attrs={}), route)
    resolver.return_value = [("user", str(second), second)]
    after = await doc_approvals.preview_route(db, cid, DocCard(attrs={}), route)
    assert before["route_token"] != after["route_token"]
    assert before["steps"][0]["people"][0]["name"] == "Анна"
    db.add.assert_not_called()
    result = await doc_approvals.start(db, cid, DocCard(attrs={}), route, None,
                                      expected_route_token=before["route_token"])
    assert result["conflict"] is True
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_поиск_дублей_ограничен_компанией_и_правами(monkeypatch):
    cid = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.execute.return_value.scalars.return_value.all.return_value = []
    monkeypatch.setattr(router, "assert_company_product", AsyncMock(return_value=cid))
    permission = AsyncMock(return_value=literal_column("qa_readable_only"))
    monkeypatch.setattr(router, "_readable_doc_clause", permission)
    result = await router.duplicate_candidates(company_id=str(cid), external_number="А-15",
        external_date=date(2026, 9, 5), counterparty_id=None, counterparty_name="Партнёр",
        file_sha256="a" * 64, db=db, current_user=User(id=uuid.uuid4()))
    assert result == {"docs": []}
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert str(cid) in sql and "qa_readable_only" in sql
    assert "tombstoned_at IS NULL" in sql and "is_current IS true" in sql
    permission.assert_awaited_once()
