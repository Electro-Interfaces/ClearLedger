"""
DEV: наполнить CbMovementDoc(kind='transfer') — перемещения ЦБ ЭЛСИ.АЗК (208).
Document.ПеремещениеТоваров: СкладОтправитель→СкладПолучатель + строки ТЧ Товары.
⚠ Себестоимость у внутренних перемещений = 0 → сумма строки = Количество × Цена
(розн. стоимость перемещённого). Направление относительно складов магазина 208.
Read-only к 1С. Запуск (из server/):  py -3.13 scripts/pull_cb_transfer_dev.py
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
from app.models import CbMovementDoc, CbNomenclature  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
KIND = "transfer"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
STORE_WAREHOUSES = {"208", "20800002"}
DOC = "ПеремещениеТоваров"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _direction(src: str, dst: str) -> str:
    si, di = src in STORE_WAREHOUSES, dst in STORE_WAREHOUSES
    if si and di:
        return "Внутреннее (склад↔зал)"
    if di:
        return "Приход (на 208)"
    if si:
        return "Расход (с 208)"
    return "Прочее"


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with OneCComClient(conn) as client:
        skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=500)
        wh = {r.get("Ref_Key"): (str(r.get("Code") or "").strip(), str(r.get("Description") or "")) for r in skl}

        hdr = await client.fetch_entity(
            f"Document_{DOC}",
            select=["Ref_Key", "Number", "Date", "Posted", "DeletionMark",
                    "СкладОтправитель_Key", "СкладПолучатель_Key", "Комментарий"],
            orderby="Date УБЫВ", top=2000,
        )
        lines = await client.query_tabular(
            DOC, "Товары",
            select=["Ссылка", "Ссылка.СкладОтправитель", "Ссылка.СкладПолучатель",
                    "НомерСтроки", "Номенклатура", "Количество", "Цена", "Себестоимость"],
            top=200000,
        )
    print(f"получено: перемещений {len(hdr)}, строк {len(lines)}, складов {len(wh)}")

    def _involved(src_g, dst_g) -> bool:
        return wh.get(src_g, ("?", ""))[0] in STORE_WAREHOUSES or wh.get(dst_g, ("?", ""))[0] in STORE_WAREHOUSES

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        names = {n.external_ref: n.name for n in (await db.execute(
            select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}

        by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
        for r in lines:
            if not _involved(r.get("Ссылка.СкладОтправитель"), r.get("Ссылка.СкладПолучатель")):
                continue
            ref = str(r.get("Ссылка") or "")
            nom = str(r.get("Номенклатура") or "")
            qty = _num(r.get("Количество")); price = _num(r.get("Цена"))
            amt = qty * price
            a = by_doc[ref]
            a["pos"] += 1; a["qty"] += qty; a["amt"] += amt
            if len(a["lines"]) < 500:
                a["lines"].append({
                    "n": int(_num(r.get("НомерСтроки"))) or (len(a["lines"]) + 1),
                    "ref": nom, "name": names.get(nom, nom[:8]),
                    "qty": round(qty, 3), "price": round(price, 2), "amount": round(amt, 2),
                    "cost": round(_num(r.get("Себестоимость")), 2),
                })

        await db.execute(delete(CbMovementDoc).where(
            CbMovementDoc.company_id == cid, CbMovementDoc.kind == KIND))
        n = 0
        for h in hdr:
            src_g, dst_g = h.get("СкладОтправитель_Key"), h.get("СкладПолучатель_Key")
            if not _involved(src_g, dst_g):
                continue
            src = wh.get(src_g, ("?", "")); dst = wh.get(dst_g, ("?", ""))
            ref = str(h.get("Ref_Key") or "")
            a = by_doc.get(ref, {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
            db.add(CbMovementDoc(
                company_id=cid, kind=KIND, external_ref=ref,
                number=(str(h.get("Number")) if h.get("Number") else None),
                doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
                posted=bool(h.get("Posted")), deleted=bool(h.get("DeletionMark")),
                warehouse_code=src[0], warehouse_name=src[1],
                warehouse_to_code=dst[0], warehouse_to_name=dst[1],
                comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
                reason=_direction(src[0], dst[0]), from_inventory=False,
                positions=a["pos"], total_qty=round(a["qty"], 3), total_amount=round(a["amt"], 2),
                lines=(sorted(a["lines"], key=lambda x: x["n"]) or None),
            ))
            n += 1
        await db.commit()

    tot = sum(v["amt"] for v in by_doc.values())
    print(f"CbMovementDoc(transfer): записано {n} перемещений (208), розн. стоимость Σ {round(tot)}₽")


if __name__ == "__main__":
    asyncio.run(main())
