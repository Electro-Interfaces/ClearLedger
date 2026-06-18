# Smoke: проверка расширенного pull контрагентов/договоров на живой БП ГИГ через COM.
# Валидирует кросс-клиентские имена полей (Owner_Key/Организация_Key/ВидДоговора и пр.).
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x")

from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.services.onec.odata_client import (  # noqa: E402
    ENTITY_CONTRACTS,
    ENTITY_COUNTERPARTIES,
)
from app.services.onec.sync_service import (  # noqa: E402
    CONTRACT_FETCH,
    COUNTERPARTY_FETCH,
)

CONN = r'File="D:\Users\magsp\GIG Base2";Usr="Гайворонская Татьяна";Pwd="12345";'


async def main() -> int:
    async with OneCComClient(CONN) as c:
        print("— Контрагенты (top 3) —", flush=True)
        rows = await c.fetch_entity(ENTITY_COUNTERPARTIES, select=COUNTERPARTY_FETCH, top=3)
        for r in rows:
            print({k: r.get(k) for k in (
                "Ref_Key", "Description", "ИНН", "НаименованиеПолное",
                "ЮридическоеФизическоеЛицо", "ГоловнойКонтрагент_Key")})
        print("\n— Договоры (top 3) —", flush=True)
        rows = await c.fetch_entity(ENTITY_CONTRACTS, select=CONTRACT_FETCH, top=3)
        for r in rows:
            print({k: r.get(k) for k in (
                "Ref_Key", "Номер", "Дата", "Owner_Key", "Организация_Key",
                "ВидДоговора", "ДоговорЗакрыт", "Сумма")})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
