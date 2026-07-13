"""
DEV: собрать пакет ЦБ→БП для ОДНОЙ смены 208 эмиттером Ledger и выгрузить JSON в
каталог (для Ф4 байт-сверки и загрузки на БП-стенд GIG Base2).

Запуск (из server/):
  py -3.13 scripts/emit_shift_package_dev.py            # список июньских смен
  py -3.13 scripts/emit_shift_package_dev.py <shift_key> [outdir]
  py -3.13 scripts/emit_shift_package_dev.py --auto [outdir]  # авто: поздняя богатая смена
"""
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import DataEntry  # noqa: E402
from app.services.bp_export import BpPackageEmitter, _day  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"


async def _list_shifts(db, cid):
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == cid, DataEntry.source == "oneC",
        DataEntry.doc_type_id == "retail_sale_sidegoods"))).scalars().all()
    out = []
    for r in rows:
        sm = (r.meta or {}).get("Смена") or {}
        key = str(sm.get("Смена") or f"{_day(sm)}|{sm.get('КодАЗС') or '—'}")
        out.append((_day(sm), str(sm.get("КодАЗС") or "—"), sm.get("Номер"), key))
    out.sort(key=lambda x: (x[0] or "", x[2] or 0))
    return out


async def main() -> None:
    args = [a for a in sys.argv[1:]]
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        shifts = await _list_shifts(db, cid)

        if not args:
            print(f"Смен retail 208: {len(shifts)}")
            for day, azs, num, key in shifts:
                print(f"  {day}  АЗС{azs}  смена №{num}  key={key}")
            return

        if args[0] == "--auto":
            outdir = args[1] if len(args) > 1 else "."
            # поздняя смена (после Дня X ~11.06) с богатым составом — берём последнюю
            june = [s for s in shifts if (s[0] or "") >= "2026-06-15"]
            pick = (june or shifts)[-1]
            shift_key = pick[3]
            print(f"AUTO → {pick[0]} АЗС{pick[1]} смена №{pick[2]} key={shift_key}")
        else:
            shift_key = args[0]
            outdir = args[1] if len(args) > 1 else "."

        emitter = BpPackageEmitter(db, cid)
        summary = await emitter.emit_to_dir(shift_key, outdir)
        print("── выгружено ──")
        for k, v in summary.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
