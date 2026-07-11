"""
DEV: наполнить CbMovementDoc(kind='revaluation') — переоценки ЦБ ЭЛСИ.АЗК (208).
Document.ПереоценкаТоваровАЗК: ТЧ Товары = ЦенаВРозницеСтарая→ЦенаВРознице (+Количество
остатка). Считаем Δ цены, Δ%, влияние на розн. стоимость остатка (Σ Δ×Количество).
Только строки с изменением цены. Read-only к 1С. Запуск (из server/):
  py -3.13 scripts/pull_cb_revaluation_dev.py
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
KIND = "revaluation"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
STORE_WAREHOUSES = {"208", "20800002"}
DOC = "ПереоценкаТоваровАЗК"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _reason(up: int, down: int) -> str:
    if up and not down:
        return "Подорожание"
    if down and not up:
        return "Удешевление"
    if up and down:
        return "Смешанная"
    return "Без изменений"


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
            select=["Ref_Key", "Number", "Date", "Склад_Key", "Комментарий"],
            orderby="Date УБЫВ", top=6000,
        )
        lines = await client.query_tabular(
            DOC, "Товары",
            select=["Ссылка", "Ссылка.Склад", "Номенклатура", "ЦенаВРозницеСтарая", "ЦенаВРознице", "Количество"],
            where="Т.ЦенаВРознице <> Т.ЦенаВРозницеСтарая", top=200000,
        )
    print(f"получено: переоценок {len(hdr)}, строк-изменений {len(lines)}, складов {len(wh)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        names = {n.external_ref: n.name for n in (await db.execute(
            select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}

        by_doc: dict[str, dict] = defaultdict(lambda: {"pos": 0, "up": 0, "down": 0, "impact": 0.0, "lines": []})
        for r in lines:
            code = wh.get(r.get("Ссылка.Склад"), ("?", ""))[0]
            if code not in STORE_WAREHOUSES:
                continue
            ref = str(r.get("Ссылка") or "")
            nom = str(r.get("Номенклатура") or "")
            old = _num(r.get("ЦенаВРозницеСтарая")); new = _num(r.get("ЦенаВРознице"))
            qty = _num(r.get("Количество"))
            delta = new - old
            pct = (100.0 * delta / old) if old else None
            a = by_doc[ref]
            a["pos"] += 1
            if delta > 0:
                a["up"] += 1
            elif delta < 0:
                a["down"] += 1
            a["impact"] += delta * qty
            if len(a["lines"]) < 500:
                a["lines"].append({
                    "ref": nom, "name": names.get(nom, nom[:8]),
                    "old": round(old, 2), "new": round(new, 2), "delta": round(delta, 2),
                    "pct": (round(pct, 1) if pct is not None else None), "qty": round(qty, 3),
                })

        await db.execute(delete(CbMovementDoc).where(
            CbMovementDoc.company_id == cid, CbMovementDoc.kind == KIND))
        n = 0
        for h in hdr:
            code = wh.get(h.get("Склад_Key"), ("?", ""))[0]
            if code not in STORE_WAREHOUSES:
                continue
            ref = str(h.get("Ref_Key") or "")
            a = by_doc.get(ref)
            if not a:  # переоценка без фактических изменений цены — пропускаем
                continue
            db.add(CbMovementDoc(
                company_id=cid, kind=KIND, external_ref=ref,
                number=(str(h.get("Number")) if h.get("Number") else None),
                doc_date=(str(h.get("Date"))[:10] if h.get("Date") else None),
                warehouse_code=code, warehouse_name=wh.get(h.get("Склад_Key"), ("?", ""))[1],
                comment=((str(h.get("Комментарий")) or None) if h.get("Комментарий") else None),
                reason=_reason(a["up"], a["down"]), from_inventory=False,
                positions=a["pos"], total_qty=a["up"], total_amount=round(a["impact"], 2),
                lines=(sorted(a["lines"], key=lambda x: (x["pct"] if x["pct"] is not None else 0)) or None),
            ))
            n += 1
        await db.commit()

    up = sum(v["up"] for v in by_doc.values()); down = sum(v["down"] for v in by_doc.values())
    print(f"CbMovementDoc(revaluation): записано {n} переоценок (208); строк-изменений: подорожаний {up}, удешевлений {down}")


if __name__ == "__main__":
    asyncio.run(main())
