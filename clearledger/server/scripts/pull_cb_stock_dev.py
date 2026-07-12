"""
DEV Этап-1: наполнить StockOnHand (достоверный остаток) из регистров ЦБ ЭЛСИ.АЗК (COM).
  qty/retail_price/barcode — РегистрНакопления.ТоварыНаАЗК.Остатки (розничный зал);
  cost_amount             — РегистрНакопления.ПартииТоваровНаСкладах.Остатки (Σ Стоимость).
Грейн = склад × номенклатура. Перезаливает остаток компании gig. Read-only к 1С.

Запуск (из server/):  py -3.13 scripts/pull_cb_stock_dev.py
"""
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_factory, engine, Base  # noqa: E402
from app.models import StockOnHand  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
_NULL_GUID = "00000000-0000-0000-0000-000000000000"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with OneCComClient(conn) as client:
        # склад GUID → (код, имя). Код 1С — фикс-ширина с хвостовыми пробелами → strip.
        skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=500)
        wh = {r.get("Ref_Key"): (str(r.get("Code") or "").strip(), str(r.get("Description") or "")) for r in skl}

        # розничный остаток на АЗК: кол-во + цена + ШК. ⚠ ЦенаВРознице/ШтрихКод —
        # измерения регистра: у SKU несколько комбинаций (истории цен). Корректная
        # стоимость остатка = Σ(Количество × ЦенаВРознице) по комбинациям, средняя
        # цена = стоимость/кол-во. Весовые считаются в БАЗОВЫХ единицах (мл/г/л).
        azk = await client.fetch_register_balance(
            "AccumulationRegister_ТоварыНаАЗК",
            dimensions=["Номенклатура", "Склад", "ЦенаВРознице", "ШтрихКод"],
            resources=["Количество"],
        )
        # партии: удельная себестоимость за базовую ед. = Σ Стоимость / Σ Количество
        # (в тех же единицах, что и остаток → корректная маржа даже для блоков/весовых).
        parts = await client.fetch_register_balance(
            "AccumulationRegister_ПартииТоваровНаСкладах",
            dimensions=["Номенклатура", "Склад"],
            resources=["Количество", "Стоимость"],
        )
    print(f"получено: ТоварыНаАЗК {len(azk)}, партий {len(parts)}, складов {len(wh)}")

    # агрегация остатка по (склад, номенклатура): qty=Σкол, value=Σ(кол×цена)
    onhand: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"qty": 0.0, "value": 0.0, "barcode": None})
    for r in azk:
        nom = str(r.get("Номенклатура") or "")
        whg = str(r.get("Склад") or "")
        if not nom or nom == _NULL_GUID or not whg:
            continue
        code = wh.get(whg, ("?", ""))[0]
        o = onhand[(code, nom)]
        qty = _num(r.get("Количество"))
        o["qty"] += qty
        o["value"] += qty * _num(r.get("ЦенаВРознице"))
        if not o["barcode"] and r.get("ШтрихКод"):
            o["barcode"] = str(r.get("ШтрихКод"))

    # удельная себестоимость по (склад, номенклатура)
    pc: dict[tuple[str, str], list] = defaultdict(lambda: [0.0, 0.0])  # [Σкол, Σстоим]
    for r in parts:
        nom = str(r.get("Номенклатура") or "")
        whg = str(r.get("Склад") or "")
        if not nom or nom == _NULL_GUID or not whg:
            continue
        code = wh.get(whg, ("?", ""))[0]
        pc[(code, nom)][0] += _num(r.get("Количество"))
        pc[(code, nom)][1] += _num(r.get("Стоимость"))
    cost_unit = {k: (v[1] / v[0]) for k, v in pc.items()
                 if abs(v[0]) > 0.001 and (v[1] / v[0]) > 0}  # только положительная себест.

    wh_name_by_code = {c: n for (c, n) in wh.values()}

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        await db.execute(delete(StockOnHand).where(StockOnHand.company_id == cid))
        n = 0
        for (code, nom), o in onhand.items():
            qty = o["qty"]
            # средняя розн. цена (взвеш.) — чтобы qty×price = корректная стоимость остатка
            price = (o["value"] / qty) if qty else None
            cu = cost_unit.get((code, nom))
            db.add(StockOnHand(
                company_id=cid, warehouse_code=code,
                warehouse_name=wh_name_by_code.get(code),
                nomenclature_ref=nom,
                quantity=round(qty, 3),
                retail_price=(round(price, 2) if price is not None else None),
                cost_amount=None,
                cost_unit=(round(cu, 4) if cu is not None else None),
                barcode=o["barcode"],
            ))
            n += 1
        await db.commit()

    # сводка по складам
    by_wh: dict[str, int] = defaultdict(int)
    for (code, _nom) in onhand:
        by_wh[code] += 1
    print(f"StockOnHand: записано {n} позиций (склад×SKU)")
    for code, cnt in sorted(by_wh.items(), key=lambda x: -x[1])[:10]:
        print(f"   {code:>10} {wh_name_by_code.get(code, ''):32} {cnt:>6} SKU")


if __name__ == "__main__":
    asyncio.run(main())
