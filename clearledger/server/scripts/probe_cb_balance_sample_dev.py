"""
DEV Этап-1 sample: остатки партий/АЗК ЦБ ЭЛСИ.АЗК — размер, склады (найти 208), значения.
Read-only. Запуск (из server/): py -3.13 scripts/probe_cb_balance_sample_dev.py
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.onec.com_client import OneCComClient  # noqa: E402

SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with OneCComClient(conn) as client:
        # ── Склады (найти 208) ──
        print("= СКЛАДЫ (Catalog.Склады: Code/Description) =")
        skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=100)
        wh_name = {r.get("Ref_Key"): f'{r.get("Code")}·{r.get("Description")}' for r in skl}
        for r in skl:
            print(f'   {r.get("Code"):>8}  {r.get("Description")}')
        print(f"   всего складов: {len(skl)}\n")

        # ── ПартииТоваровНаСкладах.Остатки — объём + разрез по складам ──
        print("= ПартииТоваровНаСкладах.Остатки (весь регистр) =")
        parts = await client.fetch_register_balance(
            "AccumulationRegister_ПартииТоваровНаСкладах",
            dimensions=["Номенклатура", "Склад", "ДокументОприходования"],
            resources=["Количество", "Стоимость"],
        )
        print(f"   строк партий: {len(parts)}")
        by_wh = Counter(p.get("Склад") for p in parts)
        print("   по складам (строк):")
        for wh, n in by_wh.most_common(15):
            print(f'      {wh_name.get(wh, str(wh)[:12]):40} {n:>7}')
        print("   примеры строк:")
        for p in parts[:6]:
            print(f'      ном={str(p.get("Номенклатура"))[:8]} склад={wh_name.get(p.get("Склад"),"?")[:22]:22} '
                  f'кол={p.get("Количество")} стоим={p.get("Стоимость")}')
        print()

        # ── ТоварыНаАЗК.Остатки — розничный остаток + цена + ШК ──
        print("= ТоварыНаАЗК.Остатки (розничный, с ценой/ШК) =")
        azk = await client.fetch_register_balance(
            "AccumulationRegister_ТоварыНаАЗК",
            dimensions=["Номенклатура", "Склад", "ЦенаВРознице", "ШтрихКод"],
            resources=["Количество"],
        )
        print(f"   строк: {len(azk)}")
        by_wh2 = Counter(a.get("Склад") for a in azk)
        for wh, n in by_wh2.most_common(15):
            print(f'      {wh_name.get(wh, str(wh)[:12]):40} {n:>7}')
        for a in azk[:6]:
            print(f'      ном={str(a.get("Номенклатура"))[:8]} склад={wh_name.get(a.get("Склад"),"?")[:22]:22} '
                  f'кол={a.get("Количество")} цена={a.get("ЦенаВРознице")} ШК={a.get("ШтрихКод")}')

    print("\n= sample завершён =")


if __name__ == "__main__":
    asyncio.run(main())
