# Smoke сверки: создаём 4 тестовых DataEntry под топовые ПТУ из БП ГИГ,
# с разными дельтами сумм для проверки классификации
# (none / rounding / minor / material / critical).
# Запуск: py -3.13 scripts/smoke_reconcile.py

from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401
from app.database import async_session_factory  # noqa: E402
from app.models import AccountingDoc, Company, DataEntry  # noqa: E402
from app.services.reconciliation_service import run_reconciliation  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402


# Идентифицируем тестовые entries по специальному маркеру.
TEST_TAG = "smoke-reconcile-2026-05-24"


async def main() -> int:
    async with async_session_factory() as s:
        gig = (await s.execute(select(Company).where(Company.slug == "gig"))).scalar_one_or_none()
        if not gig:
            print("FAIL: company gig not found")
            return 1

        # Чистим прошлые тестовые entries.
        await s.execute(delete(DataEntry).where(
            DataEntry.company_id == gig.id,
            DataEntry.source_label == TEST_TAG,
        ))
        await s.flush()

        # Берём 4 топ-ПТУ с заполненным ИНН.
        docs = (await s.execute(
            select(AccountingDoc).where(
                AccountingDoc.company_id == gig.id,
                AccountingDoc.doc_type == "ПТУ",
                AccountingDoc.counterparty_inn.is_not(None),
            ).order_by(AccountingDoc.amount.desc()).limit(4)
        )).scalars().all()

        # Каждому документу — entry с разным delta:
        #   #0 → точное совпадение  (delta 0.00)
        #   #1 → копейка            (delta 0.02)
        #   #2 → мелкое             (delta 5.50)
        #   #3 → значимое           (delta 250.0)
        deltas = [0.0, 0.02, 5.50, 250.0]
        plan = [
            ("Тестовая ТТН точное совпадение", deltas[0]),
            ("Тестовая ТТН копеечное расхождение", deltas[1]),
            ("Тестовая ТТН мелкое расхождение", deltas[2]),
            ("Тестовая ТТН значимое расхождение", deltas[3]),
        ]
        for doc, (title, delta) in zip(docs, plan):
            entry_amount = doc.amount + delta
            s.add(DataEntry(
                id=uuid.uuid4(),
                title=title,
                category_id="primary",
                subcategory_id="ttn",
                doc_type_id="ttn",
                company_id=gig.id,
                status="recognized",
                source="upload",
                source_label=TEST_TAG,
                meta={
                    "inn": doc.counterparty_inn,
                    "docNumber": doc.external_number or doc.number,
                    "docDate": doc.external_date or doc.date,
                    "amount": str(entry_amount),
                },
            ))
            print(f"+ entry для {doc.number} amount {entry_amount:.2f} (delta {delta:+.2f})")

        await s.commit()

        print()
        print("Run reconciliation ...")
        stats = await run_reconciliation(s, gig.id)
        await s.commit()
        print(f"  total={stats['total']} matched={stats['matched']} "
              f"discrepancy={stats['discrepancy']} unmatched={stats['unmatched']}")
        if "by_severity" in stats:
            print("  by_severity:")
            for k, v in sorted(stats["by_severity"].items()):
                print(f"    {k:12s} {v}")

        # Покажем какой статус получили наши 4 тестовых дока.
        print()
        print("Тестовые матчи:")
        rows = (await s.execute(
            select(AccountingDoc.number, AccountingDoc.amount,
                   AccountingDoc.discrepancy_status, AccountingDoc.discrepancy_summary)
            .where(AccountingDoc.company_id == gig.id,
                   AccountingDoc.id.in_([d.id for d in docs]))
        )).all()
        for r in rows:
            print(f"  {r.number:<22} sum={r.amount:>14,.2f}  status={r.discrepancy_status:<10} «{r.discrepancy_summary}»")

        # Общая разбивка
        cnt = (await s.execute(
            select(AccountingDoc.discrepancy_status, func.count())
            .where(AccountingDoc.company_id == gig.id)
            .group_by(AccountingDoc.discrepancy_status)
        )).all()
        print()
        print("Разбивка всех документов по discrepancy_status:")
        for status, n in cnt:
            print(f"  {status:<12} {n:>6}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
