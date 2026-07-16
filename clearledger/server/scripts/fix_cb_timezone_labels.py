"""
Миграция: переклеить зону у ЦБ-таймстемпов DataEntry с фиктивного +00:00 на +03:00.

Причина (P0-1 сверки сопряжения): pywin32 отдавал даты 1С как pywintypes.datetime
с меткой UTC, хотя стенные часы в них — МЕСТНЫЕ московские. Мгновение уезжало на
3 часа, а у смен с ночным стартом расходилась и ДАТА смены с топливным контуром
(тот пишет истинный UTC). com_worker._val починен (ставит +03:00), но уже
загруженные записи несут старую метку.

Стенные часы НЕ трогаем — меняется только метка зоны, т.е. мгновение становится
верным. Дата-префикс (по нему группируют витрины магазина) не меняется.

Запуск (из server/):  py -3.13 scripts/fix_cb_timezone_labels.py [--apply]
Без --apply — сухой прогон (только показать, что изменится).
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
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import DataEntry  # noqa: E402

APPLY = "--apply" in sys.argv
OLD = "+00:00"
NEW = "+03:00"
# Пути в meta, где лежат ЦБ-таймстемпы
SHIFT_KEYS = ("Открытие", "Закрытие")
DOC_KEYS = ("Дата",)


def _relabel(s):
    """'2026-06-11T00:05:13+00:00' → '2026-06-11T00:05:13+03:00' (часы не трогаем)."""
    if isinstance(s, str) and s.endswith(OLD) and "T" in s:
        return s[: -len(OLD)] + NEW
    return s


async def main() -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(select(DataEntry).where(DataEntry.source == "oneC"))).scalars().all()
        touched = 0
        samples = []
        for e in rows:
            meta = e.meta or {}
            changed = False
            sm = meta.get("Смена")
            if isinstance(sm, dict):
                for k in SHIFT_KEYS:
                    v = sm.get(k)
                    nv = _relabel(v)
                    if nv != v:
                        sm[k] = nv
                        changed = True
                        if len(samples) < 6:
                            samples.append(f"{e.doc_type_id} Смена.{k}: {v} → {nv}")
            doc = meta.get("Документ")
            if isinstance(doc, dict):
                for k in DOC_KEYS:
                    v = doc.get(k)
                    nv = _relabel(v)
                    if nv != v:
                        doc[k] = nv
                        changed = True
            if changed:
                touched += 1
                if APPLY:
                    e.meta = meta
                    flag_modified(e, "meta")
        print(f"ЦБ DataEntry всего: {len(rows)}; с меткой {OLD} → правим: {touched}")
        for s in samples:
            print("   ", s)
        if APPLY:
            await db.commit()
            print(f"✅ применено: {touched} записей переклеено на {NEW}")
        else:
            print("СУХОЙ ПРОГОН — запусти с --apply чтобы записать")


if __name__ == "__main__":
    asyncio.run(main())
