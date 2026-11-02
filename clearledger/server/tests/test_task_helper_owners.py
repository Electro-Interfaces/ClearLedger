"""M04-P5 fixed outputs + real PG/HTTP; execution belongs to ROOT frozen gate."""
import os

if os.environ.get("RUN_TASK_HELPER_OWNERS_TESTS") != "1":
    raise RuntimeError("ROOT-approved task helper owners runner required")

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String, Uuid, column, delete, event, select, values
from sqlalchemy.sql import visitors

from app.main import app
from app.models import (AuditEvent, ServiceLocation, Task, TaskEvent, TaskParticipant,
                        TaskProject, TaskSprint, TaskType, TaskVersion, TaskWatcher,
                        UserCompany)
from app.routers import tasks_router
from app.services import management_local, task_access, task_queries, task_routes
from tests.test_management_api import headers, management_data  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")
PREFIX = "task-helper-golden"
IDS = {label: uuid.UUID(f"a5100000-0000-4000-8000-{i:012x}") for i, label in enumerate((
    "company", "private-author", "private-assignee", "private-watcher", "private-participant",
    "private-hidden", "personal-mine", "personal-other", "foreign"), 1)}
READER = {IDS["company"], IDS["private-author"], IDS["private-assignee"],
          IDS["private-watcher"], IDS["private-participant"]}
ADMIN = READER | {IDS["private-hidden"]}
DEFAULT = [{"code": "new", "name": "Постановка"},
           {"code": "in_progress", "name": "В работе"},
           {"code": "review", "name": "Проверка"}]
CUSTOM = [{"code": "opened", "name": "Открыто"}, {"code": "checked", "name": "Проверено"}]


@pytest.fixture
async def world(management_data, db):
    d = management_data
    cid, reader, other = d["cid"], d["reader"], d["other"]
    reader.name, other.name = "Helper reader", "Helper author"
    projects = [TaskProject(company_id=cid, code=code, name=name)
                for code, name in (("HP1", "Project Alpha"), ("HP2", "Project Beta"))]
    types = [TaskType(company_id=cid, code="helper-a", name="Type Alpha", route=CUSTOM),
             TaskType(company_id=cid, code="helper-b", name="Type Beta", route=[])]
    objects = [ServiceLocation(id="helper-" + uuid.uuid4().hex[:24], company_id=cid, code=code, name=name)
               for code, name in (("A", "Object Alpha"), ("B", "Object Beta"))]
    db.add_all([*projects, *types, *objects])
    await db.flush()
    versions = [TaskVersion(company_id=cid, project_id=p.id, name=name)
                for p, name in zip(projects, ("Version Alpha", "Version Beta"))]
    sprints = [TaskSprint(company_id=cid, project_id=p.id, name=name)
               for p, name in zip(projects, ("Sprint Alpha", "Sprint Beta"))]
    db.add_all([*versions, *sprints])
    await db.flush()
    rows = {}
    for i, (label, company_id, visibility, author, assignee) in enumerate([
        ("company", cid, "company", other.id, reader.id),
        ("private-author", cid, "private", reader.id, other.id),
        ("private-assignee", cid, "private", other.id, reader.id),
        ("private-watcher", cid, "private", other.id, other.id),
        ("private-participant", cid, "private", other.id, other.id),
        ("private-hidden", cid, "private", other.id, other.id),
        ("personal-mine", cid, "personal", reader.id, reader.id),
        ("personal-other", cid, "personal", other.id, other.id),
        ("foreign", d["other_cid"], "company", reader.id, reader.id),
    ]):
        stamp = datetime(2026, 10, 30, 10, tzinfo=timezone.utc) + timedelta(minutes=i)
        row = Task(id=IDS[label], company_id=company_id, title=PREFIX + ":" + label,
                   visibility=visibility, author_id=author, assignee_id=assignee,
                   created_at=stamp, updated_at=stamp, status="open")
        if label in ("company", "private-author"):
            j = int(label == "private-author")
            row.type_id, row.project_id, row.object_id = types[j].id, projects[j].id, objects[j].id
            row.fix_version_id, row.found_version_id = versions[j].id, versions[1-j].id
            row.sprint_id = sprints[j].id
            row.project_number = 1
            row.stage_code = "opened" if j == 0 else "new"
        db.add(row)
        rows[label] = row
    await db.flush()
    db.add_all([TaskWatcher(task_id=IDS["private-watcher"], user_id=reader.id),
                TaskParticipant(task_id=IDS["private-participant"], user_id=reader.id)])
    await db.commit()
    d.update(rows=rows, projects=projects, types=types, objects=objects, versions=versions, sprints=sprints)
    yield d
    await db.execute(delete(Task).where(Task.id.in_(IDS.values())))
    await db.commit()


async def snapshot(db):
    return {model.__tablename__: sorted(repr(tuple(row)) for row in
            (await db.execute(select(model.__table__))).all()) for model in (
                Task, TaskEvent, TaskWatcher, TaskParticipant, TaskType, TaskProject,
                TaskVersion, TaskSprint, ServiceLocation, AuditEvent)}


@contextmanager
def select_tables(db):
    tables = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            tables.append(statement.split("FROM ", 1)[1].split()[0].strip('"'))
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield tables
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def sparse(identifier, **fields):
    data = dict(id=identifier, type_id=None, author_id=None, assignee_id=None, object_id=None,
                project_id=None, fix_version_id=None, found_version_id=None, sprint_id=None)
    data.update(fields)
    return NS(**data)


def expected_alpha():
    return {"type": "Type Alpha", "route": CUSTOM, "author": "Helper author", "assignee": "Helper reader",
            "object": "Object Alpha", "project": "Project Alpha", "project_code": "HP1",
            "fix_version": "Version Alpha", "found_version": "Version Beta", "sprint": "Sprint Alpha"}


async def test_batched_projection_fixed_outputs_and_exact_six_queries(world, db, monkeypatch, pytestconfig):
    rows = [world["rows"]["company"], world["rows"]["private-author"]]
    before = await snapshot(db)
    boundary = pytestconfig._task_helper_owners_boundary
    sent = len(boundary.capture)
    with monkeypatch.context() as patch, select_tables(db) as tables:
        commit, flush = AsyncMock(), AsyncMock()
        patch.setattr(db, "commit", commit)
        patch.setattr(db, "flush", flush)
        names = await task_queries.names(db, rows * 8)
        commit.assert_not_awaited()
        flush.assert_not_awaited()
    assert tables == ["task_projects", "task_versions", "task_sprints", "task_types", "users", "service_locations"]
    assert names == {IDS["company"]: expected_alpha(), IDS["private-author"]: {
        "type": "Type Beta", "route": DEFAULT, "author": "Helper reader", "assignee": "Helper author",
        "object": "Object Beta", "project": "Project Beta", "project_code": "HP2",
        "fix_version": "Version Beta", "found_version": "Version Alpha", "sprint": "Sprint Beta"}}
    assert names[IDS["private-author"]]["route"] is task_routes.DEFAULT_ROUTE
    assert await snapshot(db) == before and len(boundary.capture) == sent


@pytest.mark.parametrize("mode,query_count", [("empty", 0), ("null", 0), ("unknown", 6), ("user-only", 1)])
async def test_empty_null_unknown_and_sparse_inputs_keep_query_budget(world, db, mode, query_count):
    identifier, missing = uuid.UUID(int=100), uuid.UUID(int=999)
    fields = {} if mode != "unknown" else dict(type_id=missing, author_id=missing, assignee_id=missing,
        object_id="helper-unknown-location", project_id=missing, fix_version_id=missing,
        found_version_id=missing, sprint_id=missing)
    if mode == "user-only":
        fields = dict(author_id=world["reader"].id)
    rows = [] if mode == "empty" else [sparse(identifier, **fields)]
    before = await snapshot(db)
    with select_tables(db) as tables:
        result = await task_queries.names(db, rows)
    assert len(tables) == query_count
    expected = {"type": None, "route": DEFAULT, "author": "Helper reader" if mode == "user-only" else None,
        "assignee": None, "object": None, "project": None, "project_code": None,
        "fix_version": None, "found_version": None, "sprint": None}
    assert result == ({} if mode == "empty" else {identifier: expected})
    assert await snapshot(db) == before


@pytest.mark.parametrize("route,expected", [(None, DEFAULT), ([], DEFAULT),
    ([None, "bad", {}, {"name": "no code"}], DEFAULT),
    ([{"code": "b", "name": "Б"}, 1, {"code": "a", "name": "А"}],
     [{"code": "b", "name": "Б"}, {"code": "a", "name": "А"}])])
async def test_route_null_empty_custom_outputs(route, expected):
    assert task_routes.route_of(NS(route=route)) == expected
    assert tasks_router._route_of(NS(route=route)) == expected
    assert task_routes.route_of(None) is task_routes.DEFAULT_ROUTE
    assert tasks_router.DEFAULT_ROUTE is task_routes.DEFAULT_ROUTE
    assert tasks_router.STARTER_TYPES[0]["route"] is task_routes.DEFAULT_ROUTE
    assert task_routes.DEFAULT_ROUTE == DEFAULT


@pytest.mark.parametrize("mode", ["empty", "falsey", "none"])
async def test_native_default_replacement_and_route_hook_stay_late_bound(monkeypatch, mode):
    class FalseyRoute(list):
        def __bool__(self): return False
    replacement = [] if mode == "empty" else FalseyRoute([{"code": "late", "name": "Поздний"}]) if mode == "falsey" else None
    monkeypatch.setattr(tasks_router, "DEFAULT_ROUTE", replacement)
    assert tasks_router._route_of(None) is replacement
    db = NS(execute=AsyncMock(side_effect=AssertionError("sparse input queried SQL")))
    identifier = uuid.UUID(int=1)
    assert (await tasks_router._names(db, [sparse(identifier)]))[identifier]["route"] is replacement
    hook = Mock(return_value=CUSTOM)
    monkeypatch.setattr(tasks_router, "_route_of", hook)
    assert (await tasks_router._names(db, [sparse(identifier)]))[identifier]["route"] is CUSTOM
    hook.assert_called_once_with(None)
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("case", ["docs", "plan", "denied"])
async def test_product_gate_fallback_and_native_auth_hook(monkeypatch, case):
    cid, user, db = uuid.uuid4(), NS(), NS()
    calls = []
    class Gate:
        def __bool__(self): return False
        async def __call__(self, ref, who, session, code):
            assert (ref, who, session) == (str(cid), user, db)
            calls.append(code)
            if case == "docs" or (case == "plan" and code == "plan"):
                return cid
            raise HTTPException(403, "exact product refusal")
    monkeypatch.setattr(tasks_router, "assert_company_product", Gate())
    if case == "denied":
        with pytest.raises(HTTPException) as error:
            await tasks_router._assert_work(str(cid), user, db)
        assert error.value.status_code == 403 and error.value.detail == "exact product refusal"
    else:
        assert await tasks_router._assert_work(str(cid), user, db) == cid
    assert calls == (["docs"] if case == "docs" else ["docs", "plan"])


async def test_falsey_route_resolver_is_used_and_owner_wrappers_delegate(monkeypatch):
    class Resolver:
        def __bool__(self): return False
        def __call__(self, value):
            assert value is None
            return CUSTOM
    identifier, db = uuid.UUID(int=1), NS(execute=AsyncMock())
    assert (await task_queries.names(db, [sparse(identifier)], route_resolver=Resolver()))[identifier]["route"] is CUSTOM
    sentinel = object()
    population = Mock(return_value=sentinel)
    monkeypatch.setattr(task_queries, "not_personal", population)
    assert tasks_router._not_personal() is sentinel
    population.assert_called_once_with()
    db.execute.assert_not_awaited()


async def test_population_sql_null_and_unknown_are_not_an_acl(db):
    sample_ids = [uuid.UUID(int=i) for i in range(1, 7)]
    samples = values(column("id", Uuid), column("visibility", String), name="population_samples").data([
        (sample_ids[0], "company"), (sample_ids[1], "private"), (sample_ids[2], "personal"),
        (sample_ids[3], None), (sample_ids[4], "unknown"), (sample_ids[5], "")])
    # Substitute only the fixture column into the actual owner expression;
    # no copy of its operator or comparison value appears in the test query.
    def replace(node):
        if getattr(node, "table", None) is Task.__table__ and getattr(node, "name", None) == "visibility":
            return samples.c.visibility
    predicate = visitors.replacement_traverse(task_queries.not_personal(), {}, replace)
    actual = list((await db.scalars(select(samples.c.id).where(predicate))).all())
    assert set(actual) == {sample_ids[0], sample_ids[1], sample_ids[4], sample_ids[5]}
    assert len(actual) == 4


@pytest.mark.parametrize("role,expected", [("reader", READER), ("admin", ADMIN), ("superadmin", ADMIN)])
async def test_fixed_id_native_management_acl_population_no_hidden_counts(world, db, role, expected):
    d = world
    if role == "superadmin":
        d[role] = d["admin"]
        d[role].is_superadmin = True
        await db.commit()
    auth = headers(d, user=role)
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        native = await client.get("/api/tasks", headers=auth, params={"company_id": str(d["cid"]), "q": PREFIX, "scope": "all"})
        assert native.status_code == 200, native.text
        ids = [uuid.UUID(t["id"]) for t in native.json()["tasks"]]
        assert set(ids) == expected and len(ids) == native.json()["total"] == len(expected)
        alpha = next(row for row in native.json()["tasks"] if row["id"] == str(IDS["company"]))
        assert (alpha["type"], alpha["author"], alpha["assignee"], alpha["object"], alpha["project"], alpha["route"]) == (
            "Type Alpha", "Helper author", "Helper reader", "Object Alpha", "Project Alpha", CUSTOM)
        response = await client.get("/api/management/overview", headers=auth, params={"kind": "tasks", "query": PREFIX})
        assert response.status_code == 200, response.text
        assert {uuid.UUID(row["source_id"]) for row in response.json()["items"]} == expected
        assert len(response.json()["items"]) == len(expected) and not response.json()["truncated"]
        capped = await client.get("/api/management/overview", headers=auth, params={"kind": "tasks", "query": PREFIX, "limit": 1})
        assert capped.status_code == 200 and len(capped.json()["items"]) == 1 and capped.json()["truncated"]
        personal = await client.get("/api/tasks", headers=auth, params={"company_id": str(d["cid"]), "q": PREFIX, "scope": "all", "visibility": "personal"})
        assert personal.status_code == 200, personal.text
        assert {uuid.UUID(row["id"]) for row in personal.json()["tasks"]} == ({IDS["personal-mine"]} if role == "reader" else set())
    assert await snapshot(db) == before


async def test_management_direct_bindings_use_owners_not_router_helpers(world, db, monkeypatch):
    d = world
    before = await snapshot(db)
    gate, projection, population = task_access.assert_work, task_queries.names, task_queries.not_personal
    seen = []
    async def checked(*args, **kwargs):
        seen.append("gate")
        return await gate(*args, **kwargs)
    async def named(*args, **kwargs):
        seen.append("names")
        return await projection(*args, **kwargs)
    def selected():
        seen.append("population")
        return population()
    with monkeypatch.context() as patch:
        for name in ("_assert_work", "_names", "_not_personal"):
            patch.setattr(tasks_router, name, Mock(side_effect=AssertionError("old management binding")))
        patch.setattr(task_access, "assert_work", checked)
        patch.setattr(task_queries, "names", named)
        patch.setattr(task_queries, "not_personal", selected)
        commit, flush = AsyncMock(), AsyncMock()
        patch.setattr(db, "commit", commit)
        patch.setattr(db, "flush", flush)
        rows, truncated = await management_local.read_local(db, d["reader"], d["cid"], "tasks", query=PREFIX, date_from=None, date_to=None, limit=100)
        assert {row.source_id for row in rows} == READER and not truncated
        assert seen == ["gate", "population", "names"]
        alpha = next(row for row in rows if row.source_id == IDS["company"])
        assert (alpha.author_name, alpha.assignee_name, alpha.project_name) == ("Helper author", "Helper reader", "Project Alpha")
        commit.assert_not_awaited()
        flush.assert_not_awaited()
    assert await snapshot(db) == before


@pytest.mark.parametrize("revoke", ["membership", "modules"])
async def test_membership_and_modules_revoke_remain_caller_authority(world, db, revoke):
    d = world
    member = await db.get(UserCompany, (d["reader"].id, d["cid"]))
    if revoke == "membership":
        await db.delete(member)
    else:
        member.modules = ["chat"]
    await db.commit()
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/tasks", headers=headers(d), params={"company_id": str(d["cid"]), "q": PREFIX})
        assert response.status_code == 403, response.text
        response = await client.get("/api/management/overview", headers=headers(d), params={"kind": "tasks", "query": PREFIX})
        assert response.status_code == (403 if revoke == "membership" else 200), response.text
        if response.status_code == 200:
            assert response.json()["items"] == [] and response.json()["sources"][0]["state"] == "forbidden"
    assert await snapshot(db) == before


async def test_plan_only_membership_keeps_legacy_fallback_with_real_sql(world, db):
    d = world
    member = await db.get(UserCompany, (d["reader"].id, d["cid"]))
    member.modules = ["plan"]
    await db.commit()
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        native = await client.get("/api/tasks", headers=headers(d), params={
            "company_id": str(d["cid"]), "q": PREFIX, "scope": "all"})
        assert native.status_code == 200, native.text
        assert {uuid.UUID(row["id"]) for row in native.json()["tasks"]} == READER
        overview = await client.get("/api/management/overview", headers=headers(d),
                                    params={"kind": "tasks", "query": PREFIX})
        assert overview.status_code == 200, overview.text
        assert overview.json()["sources"][0]["state"] == "ok"
        assert {uuid.UUID(row["source_id"]) for row in overview.json()["items"]} == READER
    assert await snapshot(db) == before
