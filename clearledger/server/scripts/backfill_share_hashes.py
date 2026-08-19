"""Публичные ссылки: перевести открытые токены в хеши.

Токен в базе означал, что дамп таблицы — это рабочие ссылки на все непросроченные
документы. Схема уже принимает `token_hash`; здесь проставляются хеши тем ссылкам,
что были выданы раньше, и открытые значения стираются.

Выданные ссылки продолжают работать: у получателя на руках сам токен, а ищем мы
по его хешу. Ломается только показ ссылки из списка — но он и был проблемой:
ссылку показывают один раз, при выпуске.

Использование (без --apply ничего не пишет):
  COMPANY_SLUG=rushydro exec-py.sh rushydro backfill_share_hashes.py
  python scripts/backfill_share_hashes.py --apply
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import DocShareLink  # noqa: E402
from app.routers.doc_share_router import token_hash  # noqa: E402

APPLY = "--apply" in sys.argv or os.environ.get("APPLY") == "1"


async def main() -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(DocShareLink).where(DocShareLink.token.is_not(None))
        )).scalars().all()

        hashed = cleared = conflicts = 0
        for link in rows:
            raw = (link.token or "").strip()
            if not raw:
                continue
            digest = token_hash(raw)
            if link.token_hash and link.token_hash != digest:
                # Хеш уже стоит и не сходится — трогать нельзя, это разбирают руками.
                conflicts += 1
                continue
            if not link.token_hash:
                link.token_hash = digest
                link.token_prefix = raw[:8]
                hashed += 1
            link.token = None
            cleared += 1

        if APPLY:
            await db.commit()
        else:
            await db.rollback()
            print("dry-run: изменения откачены")
        print(f"ссылок всего={len(rows)}; проставлено хешей={hashed}; "
              f"очищено открытых токенов={cleared}; расхождений={conflicts}")


if __name__ == "__main__":
    asyncio.run(main())
