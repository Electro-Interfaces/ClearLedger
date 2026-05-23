# Полный цикл: Company + OneCConnection(mode=com) → sync_catalogs → sync_documents
# на стенде D:\Users\magsp\GIG Base2.
# Запуск: py -3.13 scripts/smoke_full_sync.py

from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401 — регистрация моделей
from app.database import async_session_factory, create_all  # noqa: E402
from app.models import (  # noqa: E402
    AccountingDoc,
    Company,
    Counterparty,
    NomenclatureItem,
    OneCConnection,
    OneCSyncLog,
    Organization,
    Warehouse,
)
from app.services.onec.crypto import encrypt_password  # noqa: E402
from app.services.onec.sync_service import OneCSyncService  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

CONN_STRING = (
    r'File="D:\Users\magsp\GIG Base2";'
    r'Usr="Гайворонская Татьяна";'
    r'Pwd="12345";'
)
TEST_COMPANY_SLUG = "smoke-gig-base2"


async def reset_test_company(s) -> Company:
    existing = (await s.execute(select(Company).where(Company.slug == TEST_COMPANY_SLUG))).scalar_one_or_none()
    if existing:
        # OneCSyncLog не имеет company_id — удаляется каскадом через OneCConnection.
        for model in (AccountingDoc, Counterparty, Organization, Warehouse, NomenclatureItem):
            await s.execute(delete(model).where(model.company_id == existing.id))
        # Удаление коннекта каскадом унесёт sync_logs.
        await s.execute(delete(OneCConnection).where(OneCConnection.company_id == existing.id))
        await s.execute(delete(Company).where(Company.id == existing.id))
        await s.flush()
    company = Company(
        id=uuid.uuid4(),
        name="Smoke GIG Base2",
        slug=TEST_COMPANY_SLUG,
        profile_id="fuel",
    )
    s.add(company)
    await s.flush()
    return company


async def main() -> int:
    await create_all()
    async with async_session_factory() as s:
        company = await reset_test_company(s)
        conn = OneCConnection(
            id=uuid.uuid4(),
            company_id=company.id,
            name="GIG Base2 (smoke)",
            mode="com",
            odata_url=CONN_STRING,
            username="Гайворонская Татьяна",
            password_encrypted=encrypt_password("12345"),
            sync_interval_sec=600,
        )
        s.add(conn)
        await s.flush()
        await s.commit()

        # Шаг 1: тест подключения
        service = OneCSyncService(s)
        print("[1] test_connection ...", flush=True)
        result = await service.test_connection(conn)
        print(f"    available={result['available']}, catalogs={len(result['catalogs'])}")
        if not result["available"]:
            print(f"    error: {result['error']}")
            return 1

        # Шаг 2: sync_catalogs
        print()
        print("[2] sync_catalogs ...", flush=True)
        log = await service.sync_catalogs(conn)
        await s.commit()
        print(f"    status={log.status}, processed={log.items_processed}, "
              f"created={log.items_created}, updated={log.items_updated}, errors={log.items_errors}")
        if log.status != "completed":
            print(f"    details: {log.details}")

        cnt_cp = (await s.execute(select(func.count()).select_from(Counterparty).where(Counterparty.company_id == company.id))).scalar()
        cnt_org = (await s.execute(select(func.count()).select_from(Organization).where(Organization.company_id == company.id))).scalar()
        cnt_wh = (await s.execute(select(func.count()).select_from(Warehouse).where(Warehouse.company_id == company.id))).scalar()
        cnt_nom = (await s.execute(select(func.count()).select_from(NomenclatureItem).where(NomenclatureItem.company_id == company.id))).scalar()
        print(f"    Counterparty={cnt_cp}, Organization={cnt_org}, Warehouse={cnt_wh}, Nomenclature={cnt_nom}")

        # Шаг 3: sync_documents
        print()
        print("[3] sync_documents ...", flush=True)
        log2 = await service.sync_documents(conn)
        await s.commit()
        print(f"    status={log2.status}, processed={log2.items_processed}, "
              f"created={log2.items_created}, updated={log2.items_updated}, errors={log2.items_errors}")
        cnt_doc = (await s.execute(select(func.count()).select_from(AccountingDoc).where(AccountingDoc.company_id == company.id))).scalar()
        print(f"    AccountingDoc={cnt_doc}")

        # Топ-5 документов с самыми большими суммами — для глазного теста
        top = (await s.execute(
            select(AccountingDoc.doc_type, AccountingDoc.number, AccountingDoc.date,
                   AccountingDoc.counterparty_name, AccountingDoc.amount)
            .where(AccountingDoc.company_id == company.id)
            .order_by(AccountingDoc.amount.desc())
            .limit(5)
        )).all()
        for r in top:
            print(f"      {r.doc_type:<25} N {r.number:<25} {r.date}  {r.counterparty_name[:40]:<40}  sum={r.amount:>14,.2f}")

    print()
    print("=" * 60)
    print("SMOKE full sync OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
