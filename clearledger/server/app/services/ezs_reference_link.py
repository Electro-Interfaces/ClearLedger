"""Связывание станций со справочниками витрины АСУиМ: бренд и группа.

Витрина отдаёт справочники (`brands_ru`, `chargepoint_groups_ru`), но колонки
`id_бренда` и `id_группы` в выгрузке станций пусты во ВСЕХ строках — связь
приходится восстанавливать по содержимому. Это не догадки: обе связки
проверяются по числу станций, которое сама витрина указывает для группы, и по
названию бренда.

**Бренд.** В карточках 33 написания на 15 брендов справочника: «ПСС» против
«ПСС (Россия)», «Fora»/«FORA»/«Фора», «Kostad»/«KOSTAD», «Реватт»/«REWATT»,
«StarCharge» с кириллической «С» внутри. Сводим по сжатому ключу: страна в
скобках отбрасывается, регистр снимается, кириллица и латиница приводятся к
одному алфавиту.

**Группа.** Названия групп описывают признак, который у нас уже есть:
  • «СНК» — это владелец «ООО СНК» (130 станций в группе = 130 у нас);
  • «РусГидро Красноярск Перенсона 2а» — адрес (13 = 13);
  • «<Регион> город» / «трасса» / «г+т» / «группа» — регион и класс размещения
    (Рязанская 19 + 12 = 31, Пермский 9 + 10 = 19, Сахалинская без СНК = 15).
Совпадение числа станций — критерий, а не украшение: связка, которая его не
проходит, не применяется, и группа остаётся непривязанной.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.mapping import owner_key
from app.models import EzsReference, Region, ServiceLocation

logger = logging.getLogger("clearledger.ezs_refs")

# Кириллица → латиница для брендов, записанных то так, то этак («Фора»/«FORA»,
# «Реватт»/«REWATT», «Епром»/«E-PROM»). Транслитерация по ЗВУЧАНИЮ, а не по
# начертанию: «н» это n, а не h, иначе «Ондер» и «ONDER» не сойдутся. Латинская
# «w» приводится к «v» — иначе «REWATT» и «Реватт» останутся разными.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "u", "я": "ya",
    "w": "v",
})


# Похожие начертания: в смешанных написаниях кириллица подставлена вместо
# латиницы («StarСharge» с русской «С»). Такое слово по звучанию не сойдётся,
# поэтому у бренда два ключа — по звучанию и по начертанию.
_LOOKALIKE = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
})


def _keys(name: str | None, table) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)          # страна в скобках — не часть имени
    return re.sub(r"[^a-z0-9]", "", s.translate(table))


def brand_key(name: str | None) -> str:
    """Сжатый ключ бренда по звучанию: «ПСС (Россия)» и «PSS» — одно и то же."""
    return _keys(name, _TRANSLIT)


def brand_keys(name: str | None) -> set[str]:
    """Оба ключа бренда: по звучанию и по начертанию. Пустые отбрасываются."""
    return {k for k in (_keys(name, _TRANSLIT), _keys(name, _LOOKALIKE)) if k}


def _group_matcher(name: str) -> tuple[str, Any, str | None]:
    """Название группы → (вид признака, аргумент, класс размещения).

    Виды: owner (по владельцу), address (по адресу или имени объекта),
    region (список регионов + класс), none (правило не выведено)."""
    low = (name or "").strip().lower()
    if low == "снк":
        return ("owner", "ООО СНК", None)
    if "перенсона" in low:
        return ("address", "еренсон", None)
    if low == "новая рига":
        return ("name", "новая рига", None)
    # «<Регион> город» / «трасса» / «г+т» / «группа» / без хвоста
    tail = None
    if low.endswith(" город"):
        tail, low = "city", low[:-6]
    elif low.endswith(" трасса"):
        tail, low = "highway", low[:-7]
    elif low.endswith(" г+т"):
        tail, low = None, low[:-4]
    elif low.endswith(" группа"):
        tail, low = None, low[:-7]
    # Группа может собирать несколько субъектов: «Курганская область,
    # Республика Хакассия г+т» — это два региона в одной группе.
    regions = [r.strip() for r in low.split(",") if r.strip()]
    if not regions or all(r.isdigit() for r in regions):
        return ("none", None, None)
    return ("region", regions, tail)


def _region_key(name: str) -> str:
    """Ключ сравнения региона: «Республика Хакассия» ↔ «Хакасия».

    В названиях групп регион пишут вольно — с «республикой», с двумя «с»,
    в сокращении. Сравниваем по корню первого значимого слова."""
    s = (name or "").strip().lower().replace("ё", "е")
    for prefix in ("республика ", "респ. ", "респ "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    word = s.replace("-", " ").split()[0] if s.split() else ""
    return word.rstrip("ая").replace("сс", "с")


async def link_references(db: AsyncSession, company_id, *, apply: bool = False) -> dict[str, Any]:
    """Сопоставить станции с брендами и группами витрины.

    `apply=False` — только отчёт (что сойдётся и на скольких станциях),
    `apply=True` — записать `asuimBrandId` / `asuimGroupId` в паспорт станции.
    Отчёт всегда полный: связка без подтверждения числом видна, но не пишется."""
    locs = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.type == "ev_charging"))).scalars().all()
    refs = (await db.execute(select(EzsReference).where(
        EzsReference.company_id == company_id))).scalars().all()
    regions = {r.id: r.name for r in (await db.execute(select(Region))).scalars().all()}

    # ── Бренды ───────────────────────────────────────────────────────────────
    by_key: dict[str, EzsReference] = {}
    for r in (x for x in refs if x.kind == "brand"):
        for k in brand_keys(r.name):
            by_key.setdefault(k, r)
    brand_hits = 0
    brand_misses: dict[str, int] = {}
    for loc in locs:
        ref = next((by_key[k] for k in brand_keys(loc.brand) if k in by_key), None)
        if ref is None:
            if loc.brand:
                brand_misses[loc.brand] = brand_misses.get(loc.brand, 0) + 1
            continue
        brand_hits += 1
        if apply:
            loc.extra_metadata = {**(loc.extra_metadata or {}),
                                  "asuimBrandId": ref.ext_id, "brandName": ref.name}

    # ── Группы ───────────────────────────────────────────────────────────────
    groups_out: list[dict[str, Any]] = []
    group_hits = 0
    for ref in [r for r in refs if r.kind == "group"]:
        declared = (ref.payload or {}).get("stationsCount")
        kind, arg, cls = _group_matcher(ref.name or "")
        # Группа — это состав ДЕЙСТВУЮЩЕЙ сети: выведенные станции витрина в
        # своих счётчиках не держит (Рязанская 31 против наших 32 с закрытой).
        live = [l for l in locs if l.status != "closed" and not l.is_test]
        if kind == "owner":
            # Сравнение по ключу без правовой формы: компактная выгрузка пишет
            # «СНК», витрина — «ООО СНК», и группа молча оставалась непривязанной.
            members = [l for l in live if owner_key(l.owner) == owner_key(arg)]
        elif kind == "address":
            members = [l for l in live if arg in (l.address or "").lower()]
        elif kind == "name":
            members = [l for l in live if arg in (l.name or "").lower()]
        elif kind == "region":
            keys = {_region_key(r) for r in arg}
            members = [l for l in live
                       if _region_key(regions.get(l.region_id) or "") in keys
                       and (cls is None or l.location_class == cls)
                       # Станции подрядчика живут в своей группе (СНК), иначе
                       # сахалинский регион вобрал бы 130 чужих станций.
                       and owner_key(l.owner) != owner_key("ООО СНК")]
        else:
            members = []
        ok = bool(members) and declared is not None and len(members) == int(declared)
        groups_out.append({"group": ref.name, "declared": declared,
                           "matched": len(members), "rule": kind, "confirmed": ok})
        if ok:
            group_hits += len(members)
            if apply:
                for l in members:
                    l.extra_metadata = {**(l.extra_metadata or {}),
                                        "asuimGroupId": ref.ext_id, "groupName": ref.name}
    if apply:
        await db.flush()

    confirmed = [g for g in groups_out if g["confirmed"]]
    msg = (f"бренды: сведено {brand_hits} из {len(locs)}; "
           f"группы: подтверждено {len(confirmed)} из {len(groups_out)}, "
           f"станций в них {group_hits}")
    logger.info("связывание справочников витрины: %s (apply=%s)", msg, apply)
    return {
        "applied": apply,
        "brands": {"linked": brand_hits, "total": len(locs),
                   "unmatched": sorted(brand_misses.items(), key=lambda x: -x[1])},
        "groups": groups_out,
        "message": msg,
    }
