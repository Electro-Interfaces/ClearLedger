"""UUID из БД имеют один Python-тип независимо от PostgreSQL-драйвера."""
from uuid import UUID as PythonUUID

from asyncpg.pgproto.pgproto import UUID as AsyncpgUUID
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.types import TypeDecorator


def canonical_database_uuid(value):
    """Принимает только известные UUID-типы из результата драйвера БД."""
    if value is None or type(value) is PythonUUID:
        return value
    if type(value) is AsyncpgUUID:
        raw = value.bytes
        if type(raw) is bytes and len(raw) == 16:
            return PythonUUID(bytes=raw)
    raise TypeError("Результат UUID из БД имеет неподдерживаемый Python-тип")


class CanonicalUUID(TypeDecorator):
    """Канонизирует прочитанный UUID до помещения значения в identity map.

    Обработчик применяется только к результатам SQLAlchemy. Проверки входных
    данных, typed keys, bind/literal обработка и PostgreSQL UUID не меняются.
    Режим as_uuid=False сохраняет исходный строковый результат SQLAlchemy.
    """

    impl = PostgreSQLUUID
    cache_ok = True

    def __init__(self, as_uuid=True):
        self.as_uuid = as_uuid
        super().__init__(as_uuid=as_uuid)

    @property
    def python_type(self):
        return self.impl.python_type

    def process_result_value(self, value, dialect):
        if not self.as_uuid:
            return value
        return canonical_database_uuid(value)


def uuid_storage_type(sql_type):
    """Раскрывает только наш адаптер для прежних проверок SQL-типа колонки."""
    return sql_type.impl if type(sql_type) is CanonicalUUID else sql_type
