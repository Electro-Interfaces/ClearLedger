"""Узкие команды карточек импортных реестров и текстовых ролей.

Caller владеет правами, компанией, lock, scoped index и сопоставлением.
Создание вызывается только после отсутствия кандидата; команды не делают
upsert и не завершают транзакцию. Договоры и ссылки остаются у caller.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Counterparty
from app.services.reference_identity import CounterpartyIndex
from app.services.reference_overrides import apply_import_values


async def create_imported_counterparty(
    db: AsyncSession, company_id, index: CounterpartyIndex, *,
    name: str, inn: str, cp_type: str, alias: str | None,
) -> Counterparty:
    """Создать импортную карточку и опубликовать её в индексе текущего прогона.

    Исходные строки в snapshot сохраняются целиком, реквизиты имеют прежние
    ограничения длины. После неуспешного flush индекс не получает карточку.
    """
    cp = Counterparty(
        company_id=company_id, inn=None if inn == "" else inn[:20], name=name[:500],
        type=cp_type, aliases=[alias] if alias else [], kind="external",
        raw={"referenceIdentity": {"name": name, "inn": inn}},
    )
    db.add(cp)
    await db.flush()
    index.add(cp)
    return cp


def add_imported_counterparty_alias(cp: Counterparty, alias: str | None) -> None:
    """Добавить прикладную роль, сохранив ручную фиксацию aliases."""
    if alias and alias not in (cp.aliases or []):
        apply_import_values(cp, {"aliases": sorted(set((cp.aliases or []) + [alias]))})
