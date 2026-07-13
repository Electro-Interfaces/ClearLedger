"""Пересборка строк продаж (FuelShiftSale) из сохранённого сырья raw_report
с АКТУАЛЬНЫМ маппингом оплат — для смен, где исторический ingest выбросил
виды оплаты, замапленные позже (Кредит/Кред.рубл./Монополия, 13.07.2026).

Логика = ingest fuel_router (chan_agg): sales-блок × resolve_channel.
Ручные правки (FuelShiftSaleOverride) не затрагиваются — они накладываются
поверх по натуральному ключу. Запуск (из server/):
  py -3.13 scripts/renormalize_shift_sales.py [--all]
Без --all пересобираются только смены, в сырье которых есть НОВОзамапленные
виды (по списку NEW_PATTERNS); с --all — все смены с raw_report.
"""
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Company, FuelShift, FuelShiftSale  # noqa: E402
from app.services.fuel_mappings import load_mapping_context  # noqa: E402

COMPANY = "gig"
NEW_PATTERNS = ("кредит", "кред.рубл", "монополи")


def _needs(raw: dict | None) -> bool:
    for p in (raw or {}).get("sales") or []:
        name = str((p.get("pay_type") or {}).get("name") or "").lower()
        if any(pat in name for pat in NEW_PATTERNS):
            return True
    return False


def _rebuild_rows(raw: dict | None, ctx) -> dict[tuple[str, int], dict]:
    """sales-блок → {(канал, код топлива): {liters, amount, discount, warehouse}} — как ingest."""
    agg: dict[tuple[str, int], dict] = {}
    for sale in (raw or {}).get("sales") or []:
        pay_name = (sale.get("pay_type") or {}).get("name", "")
        channel, warehouse = ctx.resolve_channel(pay_name)
        if not channel:
            continue
        for f in sale.get("fuel") or []:
            rel = f.get("release") or {}
            try:
                code = int((f.get("service") or {}).get("service_code"))
            except (TypeError, ValueError):
                continue
            a = agg.setdefault((channel, code),
                               {"liters": 0.0, "amount": 0.0, "discount": 0.0, "warehouse": warehouse})
            a["liters"] += float(rel.get("volume", 0) or 0)
            a["amount"] += float(rel.get("cost", 0) or 0)
            a["discount"] += float(rel.get("discount", 0) or 0)
    return agg


async def main() -> None:
    rebuild_all = "--all" in sys.argv
    async with async_session_factory() as db:
        cid = (await db.execute(select(Company.id).where(Company.slug == COMPANY))).scalar_one()
        ctx = await load_mapping_context(db, cid)
        shifts = (await db.execute(select(FuelShift).where(
            FuelShift.company_id == cid, FuelShift.raw_report.is_not(None)))).scalars().all()

        touched = 0
        for s in shifts:
            if not rebuild_all and not _needs(s.raw_report):
                continue
            agg = _rebuild_rows(s.raw_report, ctx)
            await db.execute(delete(FuelShiftSale).where(FuelShiftSale.shift_id == s.id))
            for (channel, code), a in agg.items():
                db.add(FuelShiftSale(
                    company_id=cid, shift_id=s.id,
                    payment_channel=channel, fuel_code=code,
                    liters=round(a["liters"], 3), amount=round(a["amount"], 2),
                    discount=round(a["discount"], 2), warehouse_name=a["warehouse"],
                ))
            # legacy-агрегаты смены (обратная совместимость UI)
            s.cash = round(sum(a["amount"] for (ch, _), a in agg.items() if ch == "retail_cash"), 2)
            s.card = round(sum(a["amount"] for (ch, _), a in agg.items() if ch == "retail_card"), 2)
            s.voucher = round(sum(a["amount"] for (ch, _), a in agg.items()
                                  if ch not in ("retail_cash", "retail_card")), 2)
            touched += 1
        await db.commit()
        print(f"пересобрано смен: {touched} (маппингов в контексте: {len(ctx.payment_mappings)})")


if __name__ == "__main__":
    asyncio.run(main())
