"""
DEV Этап-3: наполнить CbInventoryDoc — инвентаризации ЦБ ЭЛСИ.АЗК (склады 208).
Реестр Document.ИнвентаризацияТоваровНаСкладе (+Проведен/ПометкаУдаления/ДатаЗаполнения)
+ ПОЛНЫЕ строки ТЧ Товары (эмиттер БП отдаёт всю ТЧ — носитель факта, эталон
TL_ЭкспортБП). Агрегаты отклонений факт↔учёт (недостачи/излишки) считаются по
строкам с fact≠uchet. Имена номенклатуры — из кеша CbNomenclature. Read-only к 1С.

Запуск (из server/):  py -3.13 scripts/pull_cb_inventory_dev.py
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

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from app.database import async_session_factory, engine, Base  # noqa: E402
from app.models import CbInventoryDoc, CbNomenclature  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
STORE_WAREHOUSES = {"208", "20800002"}  # Торговый зал + Склад АЗС №208
DOC = "ИнвентаризацияТоваровНаСкладе"
# фильтр строк ТЧ по складам магазина прямо в запросе (полная ТЧ по сети — миллионы строк)
LINES_WHERE = 'СокрЛП(Т.Ссылка.Склад.Код) В ("208", "20800002")'


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_or_none(v) -> str | None:
    s = str(v or "")
    return None if (not s or s.startswith("0001")) else s[:19]


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with OneCComClient(conn) as client:
        skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=500)
        wh = {r.get("Ref_Key"): (str(r.get("Code") or "").strip(), str(r.get("Description") or "")) for r in skl}

        # реестр инвентаризаций
        hdr = await client.fetch_entity(
            f"Document_{DOC}",
            select=["Ref_Key", "Number", "Date", "Posted", "DeletionMark",
                    "Склад_Key", "Комментарий", "ДатаЗаполнения"],
            orderby="Date УБЫВ", top=1600,
        )
        # ПОЛНЫЕ строки ТЧ по складам магазина — одним запросом
        rows = await client.query_tabular(
            DOC, "Товары",
            select=["Ссылка", "НомерСтроки", "Номенклатура",
                    "Количество", "КоличествоУчет", "Цена", "Сумма", "СуммаУчет"],
            where=LINES_WHERE, top=300000,
        )
    print(f"получено: инвентаризаций {len(hdr)}, строк ТЧ (208) {len(rows)}, складов {len(wh)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        names = {n.external_ref: n.name for n in (await db.execute(
            select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}

        # полные строки + агрегаты отклонений по документу
        agg: dict[str, dict] = defaultdict(lambda: {
            "dev_pos": 0, "sh_qty": 0.0, "sh_amt": 0.0, "su_qty": 0.0, "su_amt": 0.0, "lines": []})
        for r in rows:
            ref = str(r.get("Ссылка") or "")
            nom = str(r.get("Номенклатура") or "")
            fact = _num(r.get("Количество")); uch = _num(r.get("КоличествоУчет"))
            amt = _num(r.get("Сумма")); amt_uch = _num(r.get("СуммаУчет"))
            d_qty = fact - uch
            d_amt = amt - amt_uch
            a = agg[ref]
            if abs(d_qty) > 1e-9:
                a["dev_pos"] += 1
                if d_qty < 0:
                    a["sh_qty"] += d_qty; a["sh_amt"] += d_amt
                else:
                    a["su_qty"] += d_qty; a["su_amt"] += d_amt
            a["lines"].append({
                "n": int(_num(r.get("НомерСтроки"))) or (len(a["lines"]) + 1),
                "ref": nom, "name": names.get(nom, nom[:8]),
                "fact": round(fact, 3), "uchet": round(uch, 3),
                "price": round(_num(r.get("Цена")), 2),
                "amount": round(amt, 2), "amount_uchet": round(amt_uch, 2),
                "dev": round(d_qty, 3), "amount_dev": round(d_amt, 2),
            })

        # WIPE-fix: upsert по (company_id, external_ref) вместо delete-all —
        # см. pull_cb_writeoff_dev.py.
        rows = []
        for h in hdr:
            code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
            if code not in STORE_WAREHOUSES:
                continue
            ref = str(h.get("Ref_Key") or "")
            a = agg.get(ref, {"dev_pos": 0, "sh_qty": 0.0, "sh_amt": 0.0, "su_qty": 0.0, "su_amt": 0.0, "lines": []})
            rows.append(dict(
                company_id=cid, external_ref=ref,
                number=(str(h.get("Number")) if h.get("Number") else None),
                doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
                posted=bool(h.get("Posted")), deleted=bool(h.get("DeletionMark")),
                fill_date=_iso_or_none(h.get("ДатаЗаполнения")),
                warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
                comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
                dev_positions=a["dev_pos"],
                shortage_qty=round(a["sh_qty"], 3), shortage_amount=round(a["sh_amt"], 2),
                surplus_qty=round(a["su_qty"], 3), surplus_amount=round(a["su_amt"], 2),
                net_amount=round(a["sh_amt"] + a["su_amt"], 2),
                lines=(sorted(a["lines"], key=lambda x: x["n"]) or None),
            ))
        n = len(rows)
        if rows:
            upd = ["number", "doc_date", "posted", "deleted", "fill_date",
                   "warehouse_code", "warehouse_name", "comment", "dev_positions",
                   "shortage_qty", "shortage_amount", "surplus_qty", "surplus_amount",
                   "net_amount", "lines"]
            stmt = pg_insert(CbInventoryDoc).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["company_id", "external_ref"],
                set_={**{c: getattr(stmt.excluded, c) for c in upd}, "snapshot_at": func.now()},
            )
            await db.execute(stmt)
        await db.commit()

    with_dev = sum(1 for h in hdr
                   if wh.get(h.get("Склад_Key"), ("?", ""))[0] in STORE_WAREHOUSES
                   and agg.get(str(h.get("Ref_Key") or ""), {}).get("dev_pos"))
    tot_sh = sum(a["sh_amt"] for a in agg.values())
    tot_su = sum(a["su_amt"] for a in agg.values())
    tot_lines = sum(len(a["lines"]) for a in agg.values())
    print(f"CbInventoryDoc: записано {n} документов (208), с отклонениями {with_dev}, строк ТЧ {tot_lines}")
    print(f"недостачи Σ {round(tot_sh)}₽, излишки Σ {round(tot_su)}₽, net {round(tot_sh + tot_su)}₽")


if __name__ == "__main__":
    asyncio.run(main())
