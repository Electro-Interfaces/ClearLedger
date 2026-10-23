"""Защита общей карточки от удаления при наличии прямых и мягких ссылок."""
from sqlalchemy import String, or_, select, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models import Counterparty, ServiceLocation


async def counterparty_usage(db, cp: Counterparty) -> list[str]:
    # Имена/колонки берутся из моделей, наличие — из реальной схемы. Частичные
    # поставки без магазина/проектов не должны падать на отсутствующей таблице.
    available = set((await db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    ))).scalars())
    keys = {str(cp.id)}
    if cp.external_ref:
        keys.add(cp.external_ref)
    result = []
    for table in Base.metadata.tables.values():
        if table.schema or table.name not in available:
            continue
        columns = [column for column in table.columns if (
            column.name.endswith('counterparty_id')
            or (table.name == 'counterparties' and column.name == 'head_ref')
            or any(fk.target_fullname == 'counterparties.id' for fk in column.foreign_keys)
        )]
        conditions = []
        for column in columns:
            if isinstance(column.type, UUID):
                conditions.append(column == cp.id)
            elif isinstance(column.type, String):
                conditions.append(column.in_(keys))
        # Документы и общие инструменты могут ссылаться строкой subject_ref.
        for name in ('subject_ref', 'target_ref'):
            if name in table.c:
                conditions.append(table.c[name].in_(['counterparty:' + k for k in keys]))
        if not conditions:
            continue
        query = select(1).select_from(table).where(or_(*conditions)).limit(1)
        if 'company_id' in table.c:
            query = query.where(table.c.company_id == cp.company_id)
        if await db.scalar(query):
            result.append(table.name)
    # Хранитель склада — реквизит объекта, отдельного FK у него пока нет.
    if ServiceLocation.__tablename__ in available:
        warehouse = ServiceLocation.extra_metadata['warehouse']['counterpartyId'].astext
        if await db.scalar(select(1).where(
            ServiceLocation.company_id == cp.company_id, warehouse.in_(keys)
        ).limit(1)):
            result.append('service_locations')
    return sorted(set(result))
