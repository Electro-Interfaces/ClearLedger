"""Проверка К1 на настоящем обрезанном файле: частичный срез не закрывает точки."""
import asyncio, pathlib
from sqlalchemy import func, select
from app.database import async_session_factory
from app.models import Company, MarketSite
from app.services import file_store
from app.services.market_registry import SOURCE_CODE, ingest_registry, parse_registry_csv


async def main() -> None:
    data = pathlib.Path("/tmp/market-part.csv").read_bytes()
    rows = parse_registry_csv(data)
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        before = int((await db.execute(
            select(func.sum(MarketSite.closed_confirmations))
            .where(MarketSite.company_id == company.id,
                   MarketSite.source == SOURCE_CODE))).scalar() or 0)
        res = await ingest_registry(db, company.id, rows,
                                    snapshot_date="2026-09-13", source_ref="part-test")
        after = int((await db.execute(
            select(func.sum(MarketSite.closed_confirmations))
            .where(MarketSite.company_id == company.id,
                   MarketSite.source == SOURCE_CODE))).scalar() or 0)
        closed = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .where(MarketSite.company_id == company.id,
                   MarketSite.source == SOURCE_CODE,
                   MarketSite.status == "closed"))).scalar() or 0)
        print(f"строк в обрезанном файле: {len(rows)}")
        print(f"покрытие среза: {res['coverage']} %, признан частичным: {res['partial']}")
        print(f"«не найдено в срезе»: {res['missing']}")
        print(f"сумма счётчиков пропусков: было {before}, стало {after}"
              + ("  ← не изменилась, точки не закрываются" if before == after else "  ← ВЫРОСЛА"))
        print(f"закрытых точек источника: {closed}")


asyncio.run(main())
