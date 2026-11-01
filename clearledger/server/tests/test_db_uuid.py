"""Проверки границы UUID и прежней семантики потребителей metadata.

Для выполнения нужна отдельная ROOT-композиция: общий conftest создаёт БД.
Сам модуль не открывает соединений и не меняет обработчики или ядро блокировок.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from asyncpg.pgproto.pgproto import UUID as DriverUUID
from sqlalchemy import Column, String, Table, MetaData
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import TypeDecorator, Uuid

from app.db_types import CanonicalUUID, canonical_database_uuid, uuid_storage_type
from app.services.contract_write_locks import CompanyKey, advisory_key, encode_key

VALUE = "00000000-0000-0000-0000-000000000123"


def test_dialect_result_adapter_preserves_exact_key_encoding_and_rejects_raw_driver():
    driver = DriverUUID(VALUE)
    with pytest.raises(TypeError):
        CompanyKey(driver)
    dialect = PGDialect_asyncpg()
    processor = CanonicalUUID().dialect_impl(dialect).result_processor(dialect, None)
    converted = processor(driver)
    expected = UUID(VALUE)
    assert type(converted) is UUID and converted == driver == expected
    assert encode_key(CompanyKey(converted)) == encode_key(CompanyKey(expected))
    assert advisory_key(CompanyKey(converted)) == advisory_key(CompanyKey(expected))
    assert processor(None) is None and processor(expected) is expected


@pytest.mark.parametrize("value", [VALUE, "bad", True, 1, b"x" * 16, object()])
def test_database_result_adapter_rejects_non_uuid_without_coercion(value):
    with pytest.raises(TypeError):
        canonical_database_uuid(value)


def test_unknown_uuid_subclass_is_rejected_before_dispatching_properties():
    class HostileUUID(UUID):
        @property
        def bytes(self):
            raise AssertionError("Свойство неизвестного подкласса не должно читаться")

        def __str__(self):
            raise AssertionError("Не должно быть строкового преобразования")

    value = HostileUUID(VALUE)
    with pytest.raises(TypeError):
        canonical_database_uuid(value)
    with pytest.raises(TypeError):
        CompanyKey(value)


@pytest.mark.parametrize("as_uuid", [True, False])
def test_native_uuid_ddl_bind_literal_python_type_and_string_mode_are_preserved(as_uuid):
    dialect = PGDialect_asyncpg()
    old, new = PGUUID(as_uuid=as_uuid), CanonicalUUID(as_uuid=as_uuid)
    value = UUID(VALUE) if as_uuid else VALUE
    assert new.python_type is old.python_type
    for name in ("bind_processor", "literal_processor"):
        before = getattr(old.dialect_impl(dialect), name)(dialect)
        after = getattr(new.dialect_impl(dialect), name)(dialect)
        assert (after(value) if after else value) == (before(value) if before else value)
    old_table = Table("uuid_parity", MetaData(), Column("id", old, primary_key=True))
    new_table = Table("uuid_parity", MetaData(), Column("id", new, primary_key=True))
    assert str(CreateTable(old_table).compile(dialect=dialect)) == str(CreateTable(new_table).compile(dialect=dialect))
    before = old.dialect_impl(dialect).result_processor(dialect, None)
    after = new.dialect_impl(dialect).result_processor(dialect, None)
    expected = before(DriverUUID(VALUE)) if before else DriverUUID(VALUE)
    actual = after(DriverUUID(VALUE))
    assert actual == expected and type(actual) is (UUID if as_uuid else str)
    assert CanonicalUUID(True)._static_cache_key != CanonicalUUID(False)._static_cache_key
    assert CanonicalUUID(as_uuid)._static_cache_key == CanonicalUUID(as_uuid)._static_cache_key


def test_metadata_unwraps_only_known_adapter_and_preserves_uuid_families():
    class UnknownDecorator(TypeDecorator):
        impl = PGUUID
        cache_ok = True

    class UnknownSubclass(CanonicalUUID):
        pass

    adapted = CanonicalUUID()
    assert uuid_storage_type(adapted) is adapted.impl
    for value in (PGUUID(), Uuid(), String(), UnknownDecorator(), UnknownSubclass()):
        assert uuid_storage_type(value) is value


def test_product_scope_filters_invalid_uuid_and_keeps_opaque_string_ids():
    from app.api_contracts import ScopeMode
    from app.product_api.queries import native_id, scope_clause

    column = Column("id", CanonicalUUID())
    assert native_id(column, VALUE) == UUID(VALUE)
    assert native_id(column, "not-a-uuid") is None
    opaque = Column("id", String())
    assert native_id(opaque, "opaque:station") == "opaque:station"
    assert scope_clause(column, SimpleNamespace(mode=ScopeMode.SET, ids=(VALUE, "invalid"))).right.value == [UUID(VALUE)]
    assert scope_clause(opaque, SimpleNamespace(mode=ScopeMode.SET, ids=("opaque:station",))).right.value == ["opaque:station"]


@pytest.mark.asyncio(loop_scope="session")
async def test_actual_query_rejects_invalid_detail_and_signed_cursor_before_row_query():
    from fastapi import HTTPException
    from app.product_api.queries import Query

    class DB:
        def __init__(self):
            self.counts = 0

        async def scalar(self, statement):
            self.counts += 1
            return 0

        async def scalars(self, statement):
            raise AssertionError("Недопустимый UUID курсора не должен попасть в запрос строк")

    class ProjectionQuery(Query):
        async def conditions(self, resource):
            return []

        def binding(self, resource, params):
            return "unit-metadata-binding"

    db = DB()
    query = ProjectionQuery(db, None, None, b"synthetic-unit-cursor-key")
    with pytest.raises(HTTPException) as error:
        await query.detail("counterparties", "invalid")
    assert error.value.status_code == 404 and db.counts == 0
    cursor = query.encode_cursor(SimpleNamespace(id="invalid", created_at=datetime.now(timezone.utc)), "unit-metadata-binding")
    params = SimpleNamespace(cursor=cursor, q=None, date_from=None, date_to=None, page_size=10)
    with pytest.raises(HTTPException) as error:
        await query.listing("counterparties", params)
    assert error.value.status_code == 400 and error.value.detail == "Invalid cursor" and db.counts == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_counterparty_usage_keeps_uuid_dependency_preflight():
    from app.models import Counterparty
    from app.services.counterparty_usage import counterparty_usage

    class DB:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: ["contracts"])

        async def scalar(self, statement):
            self.statements.append(statement)
            return 1

    db = DB()
    cp = Counterparty(id=UUID(VALUE), company_id=UUID(int=2), external_ref=None)
    assert await counterparty_usage(db, cp) == ["contracts"]
    assert len(db.statements) == 1
    compiled = db.statements[0].compile()
    assert "contracts.counterparty_id =" in str(compiled) and "contracts.company_id =" in str(compiled)
    assert UUID(VALUE) in compiled.params.values() and UUID(int=2) in compiled.params.values()
