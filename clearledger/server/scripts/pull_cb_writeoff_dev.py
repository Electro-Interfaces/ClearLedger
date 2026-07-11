"""
DEV Этап-3: наполнить CbMovementDoc(kind='writeoff') — списания ЦБ ЭЛСИ.АЗК (208).
Реестр Document.СписаниеТоваров + строки ТЧ Товары (Номенклатура/Количество/Сумма/Цена).
Причина: связь с инвентаризацией (недостача) + разбор комментария (брак/пересорт/…).
Имена — из CbNomenclature. Read-only к 1С. Запуск (из server/):
  py -3.13 scripts/pull_cb_writeoff_dev.py
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
KIND = "writeoff"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
STORE_WAREHOUSES = {"208", "20800002"}
DOC = "СписаниеТоваров"
NULL = "00000000-0000-0000-0000-000000000000"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _reason(from_inv: bool, comment: str | None) -> str:
    c = (comment or "").lower()
    if "передача дня" in c or "день x" in c or "день икс" in c:
        return "Передача Дня X"
    if from_inv:
        return "Инвентаризация (недостача)"
    if "брак" in c:
        return "Брак"
    if "пересорт" in c or "перессорт" in c:
        return "Пересортица"
    if "срок" in c or "просроч" in c:
        return "Срок годности"
    if "порч" in c:
        return "Порча"
    if "приказ" in c:
        return "Приказ"
    return "Прочее"


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with OneCComClient(conn) as client:
        skl = await client.fetch_entity("Catalog_Склады", select=["Ref_Key", "Code", "Description"], top=500)
        wh = {r.get("Ref_Key"): (str(r.get("Code") or "").strip(), str(r.get("Description") or "")) for r in skl}

        hdr = await client.fetch_entity(
            f"Document_{DOC}",
            select=["Ref_Key", "Number", "Date", "Склад_Key", "Комментарий",
                    "ИнвентаризацияТоваровНаСкладе", "СуммаДокумента"],
            orderby="Date УБЫВ", top=2000,
        )
        lines = await client.query_tabular(
            DOC, "Товары",
            select=["Ссылка", "Ссылка.Склад", "Номенклатура", "Количество", "Сумма", "Цена"],
            top=200000,
        )
    print(f"получено: списаний {len(hdr)}, строк {len(lines)}, складов {len(wh)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        names = {n.external_ref: n.name for n in (await db.execute(
            select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}

        # строки по документу (склады магазина)
        by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
        for r in lines:
            code = wh.get(r.get("Ссылка.Склад"), ("?", ""))[0]
            if code not in STORE_WAREHOUSES:
                continue
            ref = str(r.get("Ссылка") or "")
            nom = str(r.get("Номенклатура") or "")
            qty = _num(r.get("Количество")); amt = _num(r.get("Сумма"))
            a = by_doc[ref]
            a["pos"] += 1; a["qty"] += qty; a["amt"] += amt
            if len(a["lines"]) < 500:
                a["lines"].append({
                    "ref": nom, "name": names.get(nom, nom[:8]),
                    "qty": round(qty, 3), "amount": round(amt, 2), "price": _num(r.get("Цена")),
                })

        await db.execute(delete(CbMovementDoc).where(
            CbMovementDoc.company_id == cid, CbMovementDoc.kind == KIND))
        n = 0
        for h in hdr:
            code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
            if code not in STORE_WAREHOUSES:
                continue
            ref = str(h.get("Ref_Key") or "")
            inv = h.get("ИнвентаризацияТоваровНаСкладе")
            from_inv = bool(inv and str(inv) != NULL)
            comment = (str(h.get("Комментарий")) or None) if h.get("Комментарий") else None
            a = by_doc.get(ref, {"pos": 0, "qty": 0.0, "amt": 0.0, "lines": []})
            db.add(CbMovementDoc(
                company_id=cid, kind=KIND, external_ref=ref,
                number=(str(h.get("Number")) if h.get("Number") else None),
                doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
                warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
                comment=comment, reason=_reason(from_inv, comment), from_inventory=from_inv,
                positions=a["pos"], total_qty=round(a["qty"], 3),
                total_amount=round(a["amt"], 2) if a["amt"] else _num(h.get("СуммаДокумента")),
                lines=(sorted(a["lines"], key=lambda x: -x["amount"]) or None),
            ))
            n += 1
        await db.commit()

    tot = sum(v["amt"] for v in by_doc.values())
    print(f"CbMovementDoc(writeoff): записано {n} списаний (208), сумма строк {round(tot)}₽")


if __name__ == "__main__":
    asyncio.run(main())
