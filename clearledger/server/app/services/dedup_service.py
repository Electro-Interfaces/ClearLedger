"""
Контроль дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ.

Работает на кеше Ledger (dedup_cards + dedup_ns_bindings + dedup_statuses),
который наполняется pull-скриптом со станции 208 (+ склейка со снимком ЦБ по GUID).
Даёт: группы дублей (нечёткий матч), мост касса↔карточка, статусы/трекинг, экспорт.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DedupCard, DedupNsBinding, DedupStatus, CbNomenclature

# ── нормализация имени (ключ группировки дублей) ─────────────────────────────
_PUNCT = re.compile(r'[«»"\'`.,()\[\]{}/\\\-–—:;!?]+')
_MULTISPACE = re.compile(r'\s+')
_GRAM = re.compile(r'(\d)\s*гр(?![а-яё])')     # «100 гр» / «100гр» → «100г»
_ASSORT = re.compile(r'ассор', re.IGNORECASE)  # «в ассортименте»/«в ассорт.»/«в ассор» — НЕ дубль


def normalize_name(name: str) -> str:
    s = (name or "").lower().replace("ё", "е")
    s = _PUNCT.sub(" ", s)
    s = _GRAM.sub(r"\1г", s)
    s = _MULTISPACE.sub(" ", s).strip()
    return s.replace(" ", "")


def is_assortment(name: str) -> bool:
    return bool(_ASSORT.search(name or ""))


def code_prefix(code: str) -> str:
    c = (code or "").strip().upper()
    if c.startswith("008"):
        return "008"
    if c.startswith("208"):
        return "208"
    if c.startswith("ЦБ"):
        return "ЦБ"
    if c.startswith("000"):
        return "000"
    return "иное"


# ── загрузка дампа 208 (CLI-скрипт + кнопка «Обновить срез») ─────────────────
def _to_price(s: str) -> float | None:
    try:
        v = float(s)
        return v if v != 0 else None
    except (ValueError, TypeError):
        return None


def _parse_dump(text: str):
    section = None
    cards, binds, prices = [], [], {}
    for ln in text.splitlines():
        if ln.startswith("#CARDS"):
            section = "cards"; continue
        if ln.startswith("#BINDINGS"):
            section = "bind"; continue
        if ln.startswith("#PRICES"):
            section = "prices"; continue
        if ln.startswith("#END") or not ln.strip():
            continue
        p = ln.split("|")
        if section == "cards" and len(p) >= 5:
            cards.append(p)
        elif section == "bind" and len(p) >= 7:
            binds.append(p)
        elif section == "prices" and len(p) >= 2:
            prices[p[0].lower()] = _to_price(p[1])
    return cards, binds, prices


async def load_dump(db: AsyncSession, cid: uuid.UUID, dump_text: str) -> dict:
    """Идемпотентно заменяет кеш дедупа компании: local208 (карточки+цены+привязки)
    из дампа + склейка ЦБ (CbNomenclature) по GUID. Используется CLI-загрузчиком и
    эндпоинтом «Обновить срез»."""
    dump_text = dump_text.lstrip("﻿")  # BOM от ADODB.Stream utf-8 (дамп с ноды 208)
    await db.execute(delete(DedupNsBinding).where(DedupNsBinding.company_id == cid))
    await db.execute(delete(DedupCard).where(DedupCard.company_id == cid))
    await db.commit()

    cards, binds, prices = _parse_dump(dump_text)
    for c in cards:
        guid, code, marked, name, group = c[0].lower(), c[1], c[2], c[3], c[4]
        db.add(DedupCard(
            company_id=cid, source="local208", guid=guid, code=code,
            code_prefix=code_prefix(code), name=name, name_norm=normalize_name(name),
            marked=marked == "1", is_assortment=is_assortment(name), group_name=group,
            price=prices.get(guid)))
    for p in binds:
        wh, ns, cg, cm, bc, act, price = p[:7]
        db.add(DedupNsBinding(
            company_id=cid, warehouse=(wh or "").strip(), ns_code=ns,
            card_guid=(cg or "").lower() or None, card_marked=cm == "1",
            barcode=bc or None, active=act == "1", retail_price=_to_price(price)))
    await db.flush()

    cb = (await db.execute(select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()
    for c in cb:
        g = (c.external_ref or "").lower()
        if not g:
            continue
        db.add(DedupCard(
            company_id=cid, source="cb", guid=g, code=c.code,
            code_prefix=code_prefix(c.code or ""), name=c.name or "",
            name_norm=normalize_name(c.name or ""), marked=False,
            is_assortment=is_assortment(c.name or ""), group_name=None))
    await db.commit()
    return {"cards": len(cards), "bindings": len(binds), "prices": len(prices), "cb": len(cb)}


# ── сводка (KPI) ─────────────────────────────────────────────────────────────
async def summary(db: AsyncSession, cid: uuid.UUID) -> dict:
    cards = (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "local208"))).scalars().all()
    total = len(cards)
    marked = sum(1 for c in cards if c.marked)
    by_prefix: dict[str, int] = {}
    for c in cards:
        by_prefix[c.code_prefix or "иное"] = by_prefix.get(c.code_prefix or "иное", 0) + 1

    # группы дублей (по name_norm, только не-ассортимент, ≥2 карточки)
    groups: dict[str, list[DedupCard]] = {}
    for c in cards:
        if c.is_assortment or not c.name_norm:
            continue
        groups.setdefault(c.name_norm, []).append(c)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    excess = sum(len(v) - 1 for v in dup_groups.values())
    live_groups = sum(1 for v in dup_groups.values() if sum(1 for x in v if not x.marked) > 1)
    # рассинхрон цен: живые карточки группы с разными розн.ценами
    price_desync = sum(1 for v in dup_groups.values()
                       if len({x.price for x in v if not x.marked and x.price}) > 1)
    updated = max((c.updated_at for c in cards if c.updated_at), default=None)

    # мост кассы
    binds = (await db.execute(select(DedupNsBinding).where(
        DedupNsBinding.company_id == cid, DedupNsBinding.active.is_(True)))).scalars().all()
    on_marked = sum(1 for b in binds if b.card_marked)
    per_card: dict[str, int] = {}
    for b in binds:
        if b.card_guid:
            per_card[b.card_guid] = per_card.get(b.card_guid, 0) + 1
    multi_code_cards = sum(1 for n in per_card.values() if n >= 2)

    return {
        "cardsTotal": total, "cardsMarked": marked, "byPrefix": by_prefix,
        "dupGroups": len(dup_groups), "excessCards": excess, "liveDupGroups": live_groups,
        "priceDesyncGroups": price_desync,
        "assortmentCards": sum(1 for c in cards if c.is_assortment),
        "nsActive": len(binds), "nsOnMarked": on_marked, "multiCodeCards": multi_code_cards,
        "cbLinked": (await db.execute(select(func.count()).select_from(DedupCard).where(
            DedupCard.company_id == cid, DedupCard.source == "cb"))).scalar() or 0,
        "updatedAt": updated.isoformat() if updated else None,
    }


# ── группы дублей ────────────────────────────────────────────────────────────
async def groups(db: AsyncSession, cid: uuid.UUID, *, q: str | None = None,
                 include_assortment: bool = False, only_live: bool = False,
                 status: str | None = None, price_desync: bool = False) -> list[dict]:
    cards = (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "local208"))).scalars().all()
    # привязки кассы по карточке (для отметки «касса бьёт сюда»)
    binds = (await db.execute(select(DedupNsBinding).where(
        DedupNsBinding.company_id == cid))).scalars().all()
    codes_by_card: dict[str, list[dict]] = {}
    for b in binds:
        if b.card_guid:
            codes_by_card.setdefault(b.card_guid, []).append(
                {"nsCode": b.ns_code, "active": b.active, "price": b.retail_price})
    # ЦБ-карточки по guid (гибрид)
    cb = {c.guid: c for c in (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "cb"))).scalars().all()}
    # статусы групп
    statuses = {s.entity_key: s for s in (await db.execute(select(DedupStatus).where(
        DedupStatus.company_id == cid, DedupStatus.entity_type == "group"))).scalars().all()}

    grp: dict[str, list[DedupCard]] = {}
    for c in cards:
        if not c.name_norm:
            continue
        if not include_assortment and c.is_assortment:
            continue
        grp.setdefault(c.name_norm, []).append(c)

    out = []
    ql = (q or "").lower().strip()
    for key, members in grp.items():
        if len(members) < 2:
            continue
        live = [m for m in members if not m.marked]
        if only_live and len(live) < 2:
            continue
        st = statuses.get(key)
        if status and (st.status if st else "pending") != status:
            continue
        title = max(members, key=lambda m: len(m.name or "")).name
        if ql and ql not in title.lower() and ql not in key:
            continue
        prefixes = sorted({m.code_prefix or "иное" for m in members})
        mem = []
        for m in sorted(members, key=lambda x: (x.marked, x.code or "")):
            mcodes = codes_by_card.get(m.guid, [])
            mem.append({
                "guid": m.guid, "code": m.code, "prefix": m.code_prefix,
                "name": m.name, "marked": m.marked, "group": m.group_name,
                "price": m.price,
                "nsCodes": mcodes, "nsActive": any(x["active"] for x in mcodes),
                "inCb": m.guid in cb,
            })
        # рассинхрон цен: разные розн.цены у ЖИВЫХ карточек-дублей одного товара
        live_prices = sorted({m.price for m in members if not m.marked and m.price})
        spread = live_prices if len(live_prices) > 1 else []
        if price_desync and not spread:
            continue
        out.append({
            "key": key, "title": title, "count": len(members), "live": len(live),
            "assortment": members[0].is_assortment, "prefixes": prefixes,
            "priceSpread": spread,
            "members": mem,
            "status": st.status if st else "pending",
            "canonGuid": st.canon_guid if st else None,
            "note": st.note if st else None,
        })
    # сортировка: сначала с рассинхроном цен, потом по числу живых карточек
    out.sort(key=lambda g: (0 if g["priceSpread"] else 1, -g["live"], -g["count"]))
    return out


# ── мост касса ↔ карточка ────────────────────────────────────────────────────
async def bridge(db: AsyncSession, cid: uuid.UUID, *, kind: str = "on_marked") -> list[dict]:
    """kind: on_marked (коды на помеченные карточки) | multi (карточки с ≥2 кодами)
    | price_split (карточки с разными ценами по кодам)."""
    binds = (await db.execute(select(DedupNsBinding).where(
        DedupNsBinding.company_id == cid))).scalars().all()
    cards = {c.guid: c for c in (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "local208"))).scalars().all()}

    def cardname(g):
        c = cards.get(g)
        return c.name if c else "?"

    if kind == "on_marked":
        rows = []
        for b in binds:
            if b.active and b.card_marked:
                rows.append({"nsCode": b.ns_code, "warehouse": b.warehouse,
                             "cardGuid": b.card_guid, "cardName": cardname(b.card_guid),
                             "price": b.retail_price, "barcode": b.barcode})
        return sorted(rows, key=lambda r: r["nsCode"])

    # группировка по карточке
    by_card: dict[str, list[DedupNsBinding]] = {}
    for b in binds:
        if b.card_guid and b.active:
            by_card.setdefault(b.card_guid, []).append(b)

    rows = []
    for g, bl in by_card.items():
        prices = sorted({b.retail_price for b in bl if b.retail_price})
        if kind == "multi" and len(bl) >= 2:
            rows.append({"cardGuid": g, "cardName": cardname(g), "codes": len(bl),
                         "nsCodes": sorted(b.ns_code for b in bl), "prices": prices,
                         "marked": cards.get(g).marked if cards.get(g) else False})
        elif kind == "price_split" and len(prices) > 1:
            rows.append({"cardGuid": g, "cardName": cardname(g), "codes": len(bl),
                         "nsCodes": sorted(b.ns_code for b in bl), "prices": prices,
                         "marked": cards.get(g).marked if cards.get(g) else False})
    return sorted(rows, key=lambda r: -r["codes"])


# ── статусы (трекинг) ────────────────────────────────────────────────────────
async def set_status(db: AsyncSession, cid: uuid.UUID, *, entity_type: str, entity_key: str,
                     status: str | None, canon_guid: str | None, note: str | None,
                     user: str) -> DedupStatus:
    row = (await db.execute(select(DedupStatus).where(
        DedupStatus.company_id == cid, DedupStatus.entity_type == entity_type,
        DedupStatus.entity_key == entity_key))).scalar_one_or_none()
    now = datetime.now(timezone.utc).isoformat()
    if row is None:
        row = DedupStatus(company_id=cid, entity_type=entity_type, entity_key=entity_key,
                          status="pending", history=[])
        db.add(row)
    prev = row.status
    if status is not None:
        row.status = status
    if canon_guid is not None:
        row.canon_guid = canon_guid or None
    if note is not None:
        row.note = note
    row.updated_by = user
    hist = list(row.history or [])
    hist.append({"at": now, "by": user, "from": prev, "to": row.status,
                 "canon": row.canon_guid, "note": note})
    row.history = hist[-50:]
    await db.commit()
    return row


# ── экспорт плана дедупа (для .epf / скриптов) ───────────────────────────────
async def export_plan(db: AsyncSession, cid: uuid.UUID) -> list[dict]:
    """Пары дубль→канон для исполнителя. Канон = помеченный статусом группы
    canon_guid, либо эвристика: живая 008-карточка, иначе первая живая."""
    gs = await groups(db, cid, include_assortment=False)
    plan = []
    for g in gs:
        if g["status"] in ("not_duplicate",):
            continue
        canon = g.get("canonGuid")
        if not canon:
            live = [m for m in g["members"] if not m["marked"]]
            pool = live or g["members"]
            pick = next((m for m in pool if m["prefix"] == "008"), pool[0])
            canon = pick["guid"]
        canon_m = next((m for m in g["members"] if m["guid"] == canon), None)
        for m in g["members"]:
            if m["guid"] == canon:
                continue
            plan.append({
                "group": g["title"], "status": g["status"],
                "priceSpread": "/".join(str(p) for p in g["priceSpread"]),
                "dupGuid": m["guid"], "dupCode": m["code"], "dupName": m["name"],
                "dupMarked": m["marked"], "dupPrice": m["price"],
                "dupNsCodes": [x["nsCode"] for x in m["nsCodes"]],
                "canonGuid": canon, "canonCode": canon_m["code"] if canon_m else None,
                "canonName": canon_m["name"] if canon_m else None,
                "canonPrice": canon_m["price"] if canon_m else None,
            })
    return plan
