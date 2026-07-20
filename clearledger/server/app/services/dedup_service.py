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

from app.models import DedupCard, DedupNsBinding, DedupStatus, DedupCorrectionJob, CbNomenclature

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


WH208 = "208"


def code_prefix(code: str) -> str:
    """Префикс КОДА номенклатуры в базе 208 — наследие нумерации, НЕ станция.
    Карточка «008…» спокойно живёт на кассе 208: код 5147 склада 208 бьёт на
    «008000001476» (Трос @550 ₽). Разрез «наше/не наше» — только по складу
    привязки кассы (см. in_scope_208), никогда по префиксу."""
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
    cards, binds, prices, sales = [], [], {}, {}
    for ln in text.splitlines():
        if ln.startswith("#CARDS"):
            section = "cards"; continue
        if ln.startswith("#BINDINGS"):
            section = "bind"; continue
        if ln.startswith("#PRICES"):
            section = "prices"; continue
        if ln.startswith("#SALES"):
            section = "sales"; continue
        if ln.startswith("#END") or not ln.strip():
            continue
        p = ln.split("|")
        if section == "cards" and len(p) >= 5:
            cards.append(p)
        elif section == "bind" and len(p) >= 7:
            binds.append(p)
        elif section == "prices" and len(p) >= 2:
            prices[p[0].lower()] = _to_price(p[1])
        elif section == "sales" and len(p) >= 2:
            try:
                sales[p[0].lower()] = float(str(p[1]).replace(",", "."))
            except (ValueError, TypeError):
                pass
    return cards, binds, prices, sales


async def load_dump(db: AsyncSession, cid: uuid.UUID, dump_text: str) -> dict:
    """Идемпотентно заменяет кеш дедупа компании: local208 (карточки+цены+привязки)
    из дампа + склейка ЦБ (CbNomenclature) по GUID. Используется CLI-загрузчиком и
    эндпоинтом «Обновить срез»."""
    dump_text = dump_text.lstrip("﻿")  # BOM от ADODB.Stream utf-8 (дамп с ноды 208)
    await db.execute(delete(DedupNsBinding).where(DedupNsBinding.company_id == cid))
    await db.execute(delete(DedupCard).where(DedupCard.company_id == cid))
    await db.commit()

    cards, binds, prices, sales = _parse_dump(dump_text)
    for c in cards:
        guid, code, marked, name, group = c[0].lower(), c[1], c[2], c[3], c[4]
        db.add(DedupCard(
            company_id=cid, source="local208", guid=guid, code=code,
            code_prefix=code_prefix(code), name=name, name_norm=normalize_name(name),
            marked=marked == "1", is_assortment=is_assortment(name), group_name=group,
            price=prices.get(guid), sold_qty=sales.get(guid)))
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
    return {"cards": len(cards), "bindings": len(binds), "prices": len(prices),
            "sales": len(sales), "cb": len(cb)}


# ── разрез «контур станции 208» ──────────────────────────────────────────────
def cb_status(card: DedupCard, cb: dict) -> str:
    """Связь карточки с центральной базой: ok (есть, код тот же) | missing (в ЦБ
    нет — заведена локально и не уехала) | code_diff (код разошёлся по существу).
    Пробелы в коде не считаем расхождением: они одинаково мусорят в обоих
    источниках (« Cosmos») — это дефект самих данных, а не рассинхрон с ЦБ."""
    c = cb.get(card.guid)
    if c is None:
        return "missing"
    if (card.code or "").strip() != (c.code or "").strip():
        return "code_diff"
    return "ok"


def in_scope_208(members, codes_by_card: dict[str, list[dict]]) -> bool:
    """Группа в контуре 208, если касса 208 через неё реально работает: активный
    код склада 208 на любой карточке либо продажи. Мёртвые карточки (кофе-напитки,
    лимонады) и коды чужих складов (5/210/8/207/209) — не наша зона."""
    for m in members:
        if m.sold_qty and m.sold_qty > 0:
            return True
        for x in codes_by_card.get(m.guid, []):
            if x.get("active") and str(x.get("wh") or "") == WH208:
                return True
    return False


async def _codes_by_card(db: AsyncSession, cid: uuid.UUID, *, active_only: bool = False) -> dict[str, list[dict]]:
    stmt = select(DedupNsBinding).where(DedupNsBinding.company_id == cid)
    if active_only:
        stmt = stmt.where(DedupNsBinding.active.is_(True))
    out: dict[str, list[dict]] = {}
    for b in (await db.execute(stmt)).scalars().all():
        if b.card_guid:
            out.setdefault(b.card_guid, []).append(
                {"nsCode": b.ns_code, "wh": b.warehouse, "active": b.active,
                 "price": b.retail_price})
    return out


# ── распознавание канона, вписанного в примечание ────────────────────────────
_NOTE_DIGITS = re.compile(r'\d+')


async def _cards_by_code(db: AsyncSession, cid: uuid.UUID) -> dict[str, str]:
    """guid по нормализованному (только цифры) коду карточки — для резолва канона
    из примечания. Короткие коды (<9 цифр) отбрасываем: цена/код кассы иначе
    ловятся как карточка."""
    rows = (await db.execute(select(DedupCard.guid, DedupCard.code).where(
        DedupCard.company_id == cid, DedupCard.source == "local208"))).all()
    out: dict[str, str] = {}
    for guid, code in rows:
        c = re.sub(r"\D", "", code or "")
        if len(c) >= 9:
            out.setdefault(c, guid)
    return out


def resolve_canon_from_note(note: str | None, by_code: dict[str, str]) -> str | None:
    """Админ вписывает код карточки-хозяина в примечание («…008000003904 720 р…»),
    иногда слитно с ценой («008000003904720 р»). Ищем код карточки как ПОДСТРОКУ
    в цифровых токенах примечания (точное равенство ломается о слипшуюся цену),
    предпочитая самый длинный код — 12-значный надёжнее 9-значного.

    Резолв — по ВСЕМ карточкам 208, не только по членам группы: жёсткая
    нормализация имени разводит реальные дубли по разным группам
    («Трос …5 т.» ↔ «Трос …(5т./5 м.)», «LD Blue» ↔ «LD Autograph Blue»),
    и хозяин, на которого указывает оператор, обычно в соседней группе."""
    if not note:
        return None
    tokens = _NOTE_DIGITS.findall(note)
    if not tokens:
        return None
    best_guid, best_len = None, 0
    for code, guid in by_code.items():
        if len(code) <= best_len:
            continue
        if any(code in t for t in tokens):
            best_guid, best_len = guid, len(code)
    return best_guid


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
    # разрез «наше/не наше»: касса 208 работает через группу или нет
    codes = await _codes_by_card(db, cid)
    scoped = {k: v for k, v in dup_groups.items() if in_scope_208(v, codes)}
    # рассинхрон цен: живые карточки группы с разными розн.ценами (только контур 208 —
    # у мёртвых групп разные цены ни на что не влияют, это ложная тревога)
    price_desync = sum(1 for v in scoped.values()
                       if len({x.price for x in v if not x.marked and x.price}) > 1)
    updated = max((c.updated_at for c in cards if c.updated_at), default=None)

    # связь с ЦБ: интересна не галочка «есть» (у 99,96%), а аномалии
    cb_cards = {c.guid: c for c in (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "cb"))).scalars().all()}
    cb_missing = sum(1 for c in cards if cb_status(c, cb_cards) == "missing")
    cb_code_diff = sum(1 for c in cards if cb_status(c, cb_cards) == "code_diff")

    # мост кассы
    binds = (await db.execute(select(DedupNsBinding).where(
        DedupNsBinding.company_id == cid, DedupNsBinding.active.is_(True)))).scalars().all()
    on_marked = sum(1 for b in binds if b.card_marked)
    per_card: dict[str, int] = {}
    for b in binds:
        if b.card_guid:
            per_card[b.card_guid] = per_card.get(b.card_guid, 0) + 1
    multi_code_cards = sum(1 for n in per_card.values() if n >= 2)

    # группы, помеченные оператором «не используется / убрать» (на вывод из НСИ)
    not_used_groups = (await db.execute(select(func.count()).select_from(DedupStatus).where(
        DedupStatus.company_id == cid, DedupStatus.entity_type == "group",
        DedupStatus.status == "not_used"))).scalar() or 0

    return {
        "cardsTotal": total, "cardsMarked": marked, "byPrefix": by_prefix,
        "dupGroups": len(dup_groups), "excessCards": excess, "liveDupGroups": live_groups,
        "scopedGroups": len(scoped), "outOfScopeGroups": len(dup_groups) - len(scoped),
        "priceDesyncGroups": price_desync,
        "assortmentCards": sum(1 for c in cards if c.is_assortment),
        "nsActive": len(binds), "nsOnMarked": on_marked, "multiCodeCards": multi_code_cards,
        "cbLinked": len(cb_cards),
        "cbMissing": cb_missing, "cbCodeDiff": cb_code_diff,
        "notUsedGroups": not_used_groups,
        "updatedAt": updated.isoformat() if updated else None,
    }


# ── группы дублей ────────────────────────────────────────────────────────────
async def groups(db: AsyncSession, cid: uuid.UUID, *, q: str | None = None,
                 include_assortment: bool = False, only_live: bool = False,
                 status: str | None = None, price_desync: bool = False,
                 only_scope_208: bool = False) -> list[dict]:
    cards = (await db.execute(select(DedupCard).where(
        DedupCard.company_id == cid, DedupCard.source == "local208"))).scalars().all()
    card_by_guid = {c.guid: c for c in cards}
    # привязки кассы по карточке (для отметки «касса бьёт сюда»)
    codes_by_card = await _codes_by_card(db, cid)
    # ЦБ-карточки по guid: база 208 — узел РИБ центральной, номенклатура общая,
    # поэтому в ЦБ есть 7238 из 7241 (99,96%) и код совпадает у 7236. Галочка
    # «есть в ЦБ» стоит почти у всех и не различает ничего — показываем аномалию.
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
        scoped = in_scope_208(members, codes_by_card)
        if only_scope_208 and not scoped:
            continue
        st = statuses.get(key)
        if status and (st.status if st else "pending") != status:
            continue
        title = max(members, key=lambda m: len(m.name or "")).name
        if ql and ql not in title.lower() and ql not in key:
            continue
        prefixes = sorted({m.code_prefix or "иное" for m in members})
        mem = []
        # карточки, которые ПРОДАЮТСЯ сейчас — сверху (кандидаты в канон)
        for m in sorted(members, key=lambda x: (-(x.sold_qty or 0), x.marked, x.code or "")):
            mcodes = codes_by_card.get(m.guid, [])
            mem.append({
                "guid": m.guid, "code": m.code, "prefix": m.code_prefix,
                "name": m.name, "marked": m.marked, "group": m.group_name,
                "price": m.price, "soldQty": m.sold_qty,
                "sellsNow": bool(m.sold_qty and m.sold_qty > 0),
                "nsCodes": mcodes, "nsActive": any(x["active"] for x in mcodes),
                "inCb": m.guid in cb, "cbStatus": cb_status(m, cb),
            })
        # рекомендуемый канон = ЖИВАЯ карточка с макс. продажами (что реально бьёт касса)
        selling = [m for m in members if not m.marked and m.sold_qty and m.sold_qty > 0]
        selling.sort(key=lambda x: -(x.sold_qty or 0))
        recommended = selling[0].guid if selling else None
        # рассинхрон цен: разные розн.цены у ЖИВЫХ карточек-дублей одного товара
        live_prices = sorted({m.price for m in members if not m.marked and m.price})
        spread = live_prices if len(live_prices) > 1 else []
        if price_desync and not spread:
            continue
        # канон-хозяин может лежать в СОСЕДНЕЙ группе (нормализация имени развела
        # реальные дубли) — резолвим имя по всем карточкам и помечаем «внешний»,
        # чтобы выбор оператора не потерялся при отображении.
        canon_guid = st.canon_guid if st else None
        member_guids = {m.guid for m in members}
        canon_external = bool(canon_guid and canon_guid not in member_guids)
        canon_name = card_by_guid[canon_guid].name if canon_guid in card_by_guid else None
        out.append({
            "key": key, "title": title, "count": len(members), "live": len(live),
            "assortment": members[0].is_assortment, "prefixes": prefixes,
            "inScope208": scoped, "priceSpread": spread,
            "sellingCount": len(selling),          # сколько карточек продаётся (>1 = конфликт)
            "recommendedCanon": recommended,       # канон по факту продаж
            "members": mem,
            "status": st.status if st else "pending",
            "canonGuid": canon_guid,
            "canonName": canon_name,
            "canonExternal": canon_external,
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
    # оператор вписал код хозяина в примечание, а канон явно не выбрал —
    # распознаём канон из текста (подстрока кода по всем карточкам 208, cross-group)
    auto_canon = None
    if canon_guid is None and note is not None and not row.canon_guid:
        auto_canon = resolve_canon_from_note(row.note, await _cards_by_code(db, cid))
        if auto_canon:
            row.canon_guid = auto_canon
    row.updated_by = user
    hist = list(row.history or [])
    hist.append({"at": now, "by": user, "from": prev, "to": row.status,
                 "canon": row.canon_guid, "note": note,
                 **({"autoCanon": auto_canon} if auto_canon else {})})
    row.history = hist[-50:]
    await db.commit()
    return row


# ── экспорт плана дедупа (для .epf / скриптов) ───────────────────────────────
async def export_plan(db: AsyncSession, cid: uuid.UUID, *, only_scope_208: bool = True) -> list[dict]:
    """Пары дубль→канон для исполнителя — по умолчанию только контур 208: план
    работ по чужим складам и мёртвым карточкам исполнителю не нужен. Канон =
    помеченный статусом группы canon_guid, либо рекомендация по продажам."""
    gs = await groups(db, cid, include_assortment=False, only_scope_208=only_scope_208)
    plan = []
    for g in gs:
        # «не дубль» и «не используется» (вывод из НСИ) — не сливаем на канон
        if g["status"] in ("not_duplicate", "not_used"):
            continue
        canon = g.get("canonGuid") or g.get("recommendedCanon")
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
                # канон может быть в соседней группе — имя берём из g["canonName"]
                "canonGuid": canon, "canonCode": canon_m["code"] if canon_m else None,
                "canonName": canon_m["name"] if canon_m else g.get("canonName"),
                "canonPrice": canon_m["price"] if canon_m else None,
            })
    return plan


# ── корректировки по команде менеджера ───────────────────────────────────────
async def create_refresh_job(db: AsyncSession, cid: uuid.UUID, *, user: str) -> dict:
    """Задание «собрать свежий срез»: станция сама снимет дамп с локальной 1С и
    зальёт его сюда. Прод-бэкенд в сеть станции не ходит — очередь заданий и есть
    канал управления, файл руками менеджеру брать негде."""
    pending = (await db.execute(select(DedupCorrectionJob).where(
        DedupCorrectionJob.company_id == cid, DedupCorrectionJob.kind == "refresh",
        DedupCorrectionJob.status.in_(("pending", "running"))))).scalars().first()
    if pending is not None:
        return {"jobId": str(pending.id), "already": True,
                "note": "Срез уже собирается — задание в очереди"}
    job = DedupCorrectionJob(
        company_id=cid, kind="refresh", status="pending", dry_run=False,
        payload={"warehouse": "208"}, created_by=user)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"jobId": str(job.id), "already": False}


async def create_repoint_job(db: AsyncSession, cid: uuid.UUID, *, group_keys: list[str],
                             dry_run: bool, user: str) -> dict:
    """Создать задание перецепа кодов НС на канон по выбранным группам. Канон
    берётся из статуса группы (обязателен). Собирает активные коды кассы с
    НЕ-канонических карточек → перецеп на канон. Нода 208 выполнит по ключу."""
    gs = await groups(db, cid, include_assortment=True)
    by_key = {g["key"]: g for g in gs}
    pgroups, skipped = [], []
    wh = "208"
    for k in group_keys:
        g = by_key.get(k)
        if not g:
            skipped.append({"key": k, "why": "группа не найдена"}); continue
        canon = g.get("canonGuid")
        if not canon:
            skipped.append({"key": k, "why": "не выбран канон"}); continue
        canon_m = next((m for m in g["members"] if m["guid"] == canon), None)
        # ⚠ Только коды СВОЕГО склада: один код НС живёт на разных складах и там
        # указывает на другой товар (208/381=уголь, 210/381=Camel). Без фильтра
        # перецеп сорвал бы чужую привязку кассы.
        codes = sorted({x["nsCode"] for m in g["members"] if m["guid"] != canon
                        for x in m["nsCodes"] if x["active"] and str(x.get("wh") or "") == wh})
        if not codes:
            skipped.append({"key": k, "why": f"нет активных кодов кассы склада {wh} на дублях"}); continue
        # Ожидаемые владельцы кодов — карточки-дубли этой группы. Нода сверит и
        # не тронет код, который «уехал» на посторонний товар.
        pgroups.append({
            "groupKey": k, "title": g["title"], "canonGuid": canon,
            "canonCode": canon_m["code"] if canon_m else None,
            "canonName": canon_m["name"] if canon_m else None,
            "canonPrice": canon_m["price"] if canon_m else None,
            "nsCodes": codes,
            "fromGuids": sorted({m["guid"] for m in g["members"] if m["guid"] != canon}),
        })
    if not pgroups:
        return {"error": "нет групп с каноном и кодами для перецепа", "skipped": skipped}
    job = DedupCorrectionJob(
        company_id=cid, kind="repoint", status="pending", dry_run=dry_run,
        payload={"warehouse": wh, "groups": pgroups}, created_by=user)
    db.add(job)
    await db.commit()
    return {"jobId": str(job.id), "groups": len(pgroups),
            "codes": sum(len(g["nsCodes"]) for g in pgroups), "skipped": skipped,
            "dryRun": dry_run}


def _job_out(j: DedupCorrectionJob) -> dict:
    pg = (j.payload or {}).get("groups", [])
    return {
        "id": str(j.id), "kind": j.kind, "status": j.status, "dryRun": j.dry_run,
        "warehouse": (j.payload or {}).get("warehouse"), "groups": len(pg),
        "codes": sum(len(g.get("nsCodes", [])) for g in pg),
        "titles": [g.get("title") for g in pg][:8],
        "result": j.result, "createdBy": j.created_by,
        "createdAt": j.created_at.isoformat() if j.created_at else None,
        "executedAt": j.executed_at.isoformat() if j.executed_at else None,
    }


async def list_jobs(db: AsyncSession, cid: uuid.UUID, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(DedupCorrectionJob)
            .where(DedupCorrectionJob.company_id == cid)
            .order_by(DedupCorrectionJob.created_at.desc()).limit(limit))).scalars().all()
    return [_job_out(j) for j in rows]


async def cancel_job(db: AsyncSession, cid: uuid.UUID, job_id: uuid.UUID) -> bool:
    j = await db.get(DedupCorrectionJob, job_id)
    if j is None or j.company_id != cid or j.status not in ("pending", "running"):
        return False
    j.status = "cancelled"
    await db.commit()
    return True


async def claim_pending_job(db: AsyncSession, cid: uuid.UUID) -> dict | None:
    """Нода забирает следующее pending-задание (помечает running). Плоские rows
    для JScript: {jobId, kind, dryRun, warehouse, rows:[{nsCode, canonGuid, canonName}]}.
    kind=refresh — снять и залить свежий срез, rows пуст."""
    j = (await db.execute(select(DedupCorrectionJob).where(
        DedupCorrectionJob.company_id == cid,
        DedupCorrectionJob.status == "pending")
        .order_by(DedupCorrectionJob.created_at).limit(1))).scalar_one_or_none()
    if j is None:
        return None
    j.status = "running"
    j.executed_at = datetime.now(timezone.utc)
    await db.commit()
    rows = []
    for g in (j.payload or {}).get("groups", []):
        for code in g.get("nsCodes", []):
            rows.append({"nsCode": code, "canonGuid": g["canonGuid"],
                         "canonName": g.get("canonName"),
                         "fromGuids": g.get("fromGuids", [])})
    return {"jobId": str(j.id), "kind": j.kind, "dryRun": j.dry_run,
            "warehouse": (j.payload or {}).get("warehouse", "208"), "rows": rows}


async def report_job(db: AsyncSession, cid: uuid.UUID, job_id: uuid.UUID, *,
                     ok: bool, result: dict) -> bool:
    j = await db.get(DedupCorrectionJob, job_id)
    if j is None or j.company_id != cid:
        return False
    j.status = "done" if ok else "error"
    j.result = result
    j.executed_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def merge_map(db: AsyncSession, cid: uuid.UUID, *, group_keys: list[str] | None = None,
                    only_scope_208: bool = True) -> list[dict]:
    """Карта слияния дубль→канон для .epf (ОбщегоНазначения.ЗаменитьСсылки).
    ЗаменитьСсылки НЕ автоматизируем (виснет на активной кассе) — менеджер
    запускает .epf в Предприятии в тихое окно. Канон = статус группы или
    рекомендация по продажам. По умолчанию только контур 208."""
    gs = await groups(db, cid, include_assortment=False, only_scope_208=only_scope_208)
    if group_keys:
        keys = set(group_keys)
        gs = [g for g in gs if g["key"] in keys]
    out = []
    for g in gs:
        # «не дубль» и «не используется» (вывод) в карту слияния не идут
        if g["status"] in ("not_duplicate", "not_used"):
            continue
        canon = g.get("canonGuid") or g.get("recommendedCanon")
        if not canon:
            live = [m for m in g["members"] if not m["marked"]]
            pool = live or g["members"]
            canon = next((m["guid"] for m in pool if m["prefix"] == "008"), pool[0]["guid"])
        canon_m = next((m for m in g["members"] if m["guid"] == canon), None)
        for m in g["members"]:
            if m["guid"] == canon:
                continue
            out.append({
                "dupGuid": m["guid"], "dupCode": m["code"], "dupName": m["name"],
                "canonGuid": canon, "canonCode": canon_m["code"] if canon_m else None,
                "canonName": canon_m["name"] if canon_m else g.get("canonName"),
            })
    return out
