"""
Агрегатор дашборда «Обзор магазина» (сопутка + общепит) — аналог fuel_dashboard,
но источник = DataEntry(layer='clean', doc_type_id='retail_sale_sidegoods') из
канала ЦБ ЭЛСИ.АЗК. Данные лежат в meta (JSONB): meta.Секции.продажа_сопутка /
продажа_общепит (строки SKU + суммы + НДС), meta.Секции.оплаты, meta.Смена (станция/дата).

KPI на имеющихся данных (продажи): выручка (всего/сопутка/общепит), НДС, число
позиций/единиц, число смен, средний чек ≈, структура категорий, оплаты (нал/безнал),
дневная динамика, разрез по АЗС, Δ% к прошлому периоду.

Маржа/себестоимость (нужен FIFO-матч с поступлениями) — отдельным блоком, не здесь.
"""
import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, CbNomenclature, CbRef, CbBarcode

# секция meta → категория UI
_SECTIONS = (("продажа_сопутка", "Сопутка"), ("продажа_общепит", "Общепит"))


def _day(smena: dict) -> str:
    """Дата смены для группировки — по закрытию (фолбэк — открытие)."""
    return str(smena.get("Закрытие") or smena.get("Открытие") or "")[:10]


class GoodsDashboardService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _load(self) -> list[DataEntry]:
        """Все clean-продажи сопутки/общепита компании (объём мал — фильтр по дате в Python)."""
        return (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id,
            DataEntry.layer == "clean",
            DataEntry.doc_type_id == "retail_sale_sidegoods",
        ))).scalars().all()

    def _select(self, rows: list[DataEntry], df: date, dt: date,
                stations: list[str] | None) -> list[dict]:
        """Отобрать meta записей в периоде/станциях."""
        df_iso, dt_iso = df.isoformat(), dt.isoformat()
        out = []
        for e in rows:
            m = e.meta or {}
            smena = m.get("Смена") or {}
            d = _day(smena)
            if not (df_iso <= d <= dt_iso):
                continue
            if stations and str(smena.get("КодАЗС") or "") not in stations:
                continue
            out.append(m)
        return out

    def _kpis(self, metas: list[dict]) -> dict:
        cat = defaultdict(lambda: {"revenue": 0.0, "vat": 0.0, "positions": 0, "units": 0.0})
        pay = defaultdict(float)      # cash / card
        returns_sum = 0.0
        shifts = len(metas)
        for m in metas:
            sec = m.get("Секции") or {}
            for key, catname in _SECTIONS:
                s = sec.get(key) or {}
                lines = s.get("строки") or []
                cat[catname]["revenue"] += float(s.get("сумма") or 0)
                cat[catname]["vat"] += float(s.get("сумма_ндс") or 0)
                cat[catname]["positions"] += len(lines)
                cat[catname]["units"] += sum(float(ln.get("Количество") or 0) for ln in lines)
            returns_sum += float((sec.get("возвраты") or {}).get("сумма") or 0)
            for o in (sec.get("оплаты") or {}).get("строки") or []:
                kanon = str(o.get("ФормаОплатыКанон") or o.get("ФормаОплаты") or "")
                amt = float(o.get("Сумма") or 0)
                pay["cash" if "Наличн" in kanon else "card"] += amt

        total_rev = sum(c["revenue"] for c in cat.values())
        total_vat = sum(c["vat"] for c in cat.values())
        total_pos = sum(c["positions"] for c in cat.values())
        total_units = sum(c["units"] for c in cat.values())
        by_category = [{
            "category": name,
            "revenue": round(d["revenue"], 2),
            "positions": d["positions"],
            "units": round(d["units"], 3),
            "percent": round(100 * d["revenue"] / total_rev, 1) if total_rev else 0.0,
        } for name, d in sorted(cat.items(), key=lambda x: -x[1]["revenue"]) if d["revenue"] or d["positions"]]

        return {
            "financial": {
                "total_revenue": round(total_rev, 2),
                "returns": round(returns_sum, 2),
                "vat": round(total_vat, 2),
                "net_revenue": round(total_rev - total_vat, 2),
                "avg_check_approx": round(total_rev / shifts, 2) if shifts else 0.0,
                "payments": {"cash": round(pay.get("cash", 0.0), 2), "card": round(pay.get("card", 0.0), 2)},
            },
            "units": {
                "total_positions": total_pos,
                "total_units": round(total_units, 3),
                "by_category": by_category,
            },
            "operational": {"shifts_count": shifts},
        }

    def _charts(self, metas: list[dict], df: date, dt: date) -> dict:
        day_agg = {}
        d = df
        while d <= dt:
            day_agg[d.isoformat()] = {"date": d.isoformat(), "revenue": 0.0, "soputka": 0.0, "obshepit": 0.0}
            d += timedelta(days=1)
        for m in metas:
            key = _day(m.get("Смена") or {})
            g = day_agg.get(key)
            if g is None:
                continue
            sec = m.get("Секции") or {}
            sop = float((sec.get("продажа_сопутка") or {}).get("сумма") or 0)
            obsh = float((sec.get("продажа_общепит") or {}).get("сумма") or 0)
            g["soputka"] += sop
            g["obshepit"] += obsh
            g["revenue"] += sop + obsh
        daily = [{
            "date": v["date"], "revenue": round(v["revenue"], 2),
            "soputka": round(v["soputka"], 2), "obshepit": round(v["obshepit"], 2),
        } for v in sorted(day_agg.values(), key=lambda x: x["date"])]
        return {"daily": daily}

    def _by_station(self, metas: list[dict]) -> list[dict]:
        agg = defaultdict(lambda: {"revenue": 0.0, "positions": 0, "shifts": 0})
        for m in metas:
            st = str((m.get("Смена") or {}).get("КодАЗС") or "—")
            sec = m.get("Секции") or {}
            rev = pos = 0.0
            for key, _ in _SECTIONS:
                s = sec.get(key) or {}
                rev += float(s.get("сумма") or 0)
                pos += len(s.get("строки") or [])
            agg[st]["revenue"] += rev
            agg[st]["positions"] += int(pos)
            agg[st]["shifts"] += 1
        out = [{
            "station": st, "revenue": round(d["revenue"], 2),
            "positions": d["positions"], "shifts": d["shifts"],
        } for st, d in agg.items()]
        out.sort(key=lambda x: -x["revenue"])
        return out

    def _trends(self, cur: dict, prev: dict) -> dict:
        def tr(c, p):
            delta = c - p
            pct = (delta / p * 100) if p else (100.0 if c > 0 else 0.0)
            return {
                "current": round(c, 2), "previous": round(p, 2), "delta": round(delta, 2),
                "percent": round(pct, 1),
                "direction": "up" if pct > 0.5 else ("down" if pct < -0.5 else "neutral"),
            }
        return {
            "revenue": tr(cur["financial"]["total_revenue"], prev["financial"]["total_revenue"]),
            "shifts": tr(cur["operational"]["shifts_count"], prev["operational"]["shifts_count"]),
            "avg_check": tr(cur["financial"]["avg_check_approx"], prev["financial"]["avg_check_approx"]),
        }

    async def compute(self, date_from: date, date_to: date,
                      stations: list[str] | None = None, compare: bool = False) -> dict:
        rows = await self._load()
        metas = self._select(rows, date_from, date_to, stations)
        kpis = self._kpis(metas)
        result = {
            "period": {
                "from": date_from.isoformat(), "to": date_to.isoformat(),
                "days": (date_to - date_from).days + 1,
            },
            **kpis,
            "charts": self._charts(metas, date_from, date_to),
            "by_station": self._by_station(metas),
        }
        result["operational"]["stations_count"] = len(result["by_station"])
        if compare:
            days = (date_to - date_from).days + 1
            cmp_to = date_from - timedelta(days=1)
            cmp_from = cmp_to - timedelta(days=days - 1)
            c_metas = self._select(rows, cmp_from, cmp_to, stations)
            result["trends"] = self._trends(kpis, self._kpis(c_metas))
        return result

    # ── SKU-аналитика: реестр товаров с маржой + ABC (Ассортимент/Цены/Номенклатура) ──

    async def _load_purchases(self, df: date, dt: date, stations: list[str] | None) -> list[dict]:
        rows = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.layer == "clean",
            DataEntry.doc_type_id == "purchase"))).scalars().all()
        return self._select(rows, df, dt, stations)

    async def _names(self) -> dict:
        return {n.external_ref: n for n in (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()}

    async def sku_analytics(self, date_from: date, date_to: date,
                            stations: list[str] | None = None) -> dict:
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        purch_metas = await self._load_purchases(date_from, date_to, stations)
        nom = await self._names()

        sku: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "revenue_net": 0.0, "qty": 0.0, "category": None})
        for m in sale_metas:
            sec = m.get("Секции") or {}
            for key, catname in _SECTIONS:
                for ln in (sec.get(key) or {}).get("строки") or []:
                    g = ln.get("Номенклатура")
                    if not g:
                        continue
                    summ = float(ln.get("Сумма") or 0)
                    vat = float(ln.get("СуммаНДС") or 0)
                    s = sku[g]
                    s["revenue"] += summ
                    s["revenue_net"] += summ - vat
                    s["qty"] += float(ln.get("Количество") or 0)
                    s["category"] = catname

        purch: dict[str, dict] = defaultdict(lambda: {"cost_net": 0.0, "qty": 0.0})
        for m in purch_metas:
            for ln in (m.get("Документ") or {}).get("Товары") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                summ = float(ln.get("Сумма") or 0)
                vat = float(ln.get("СуммаНДС") or 0)
                purch[g]["cost_net"] += summ - vat        # закупка net (Сумма включает НДС)
                purch[g]["qty"] += float(ln.get("Количество") or 0)

        rows = []
        for g, s in sku.items():
            n = nom.get(g)
            p = purch.get(g)
            avg_cost = (p["cost_net"] / p["qty"]) if p and p["qty"] else None
            cogs = (avg_cost * s["qty"]) if avg_cost is not None else None
            margin = (s["revenue_net"] - cogs) if cogs is not None else None
            rows.append({
                "guid": g,
                "name": (n.name if n else g[:8]),
                "article": (n.article if n else None),
                "vat": (n.vat if n else None),
                "marked": bool(n.marked) if n else False,
                "weighed": bool(n.weighed) if n else False,
                "category": s["category"],
                "revenue": round(s["revenue"], 2),
                "revenue_net": round(s["revenue_net"], 2),
                "qty": round(s["qty"], 3),
                "avg_price": round(s["revenue"] / s["qty"], 2) if s["qty"] else 0.0,
                "cost_net": round(avg_cost, 4) if avg_cost is not None else None,
                "cogs": round(cogs, 2) if cogs is not None else None,
                "margin": round(margin, 2) if margin is not None else None,
                "margin_pct": round(100 * margin / s["revenue_net"], 1) if margin is not None and s["revenue_net"] else None,
                "markup_pct": round(100 * margin / cogs, 1) if margin is not None and cogs else None,
                "purch_qty": round(p["qty"], 3) if p else 0.0,
                "stock_est": round((p["qty"] if p else 0.0) - s["qty"], 3),
            })

        # ABC по выручке (накопительная доля)
        rows.sort(key=lambda x: -x["revenue"])
        total_rev = sum(r["revenue"] for r in rows) or 1.0
        cum = 0.0
        abc = {c: {"count": 0, "revenue": 0.0} for c in ("A", "B", "C")}
        for r in rows:
            cum += r["revenue"]
            share = 100 * cum / total_rev
            cls = "A" if share <= 80 else ("B" if share <= 95 else "C")
            r["abc"] = cls
            abc[cls]["count"] += 1
            abc[cls]["revenue"] += r["revenue"]
        for c in abc.values():
            c["share"] = round(100 * c["revenue"] / total_rev, 1) if total_rev else 0.0
            c["revenue"] = round(c["revenue"], 2)

        costed = [r for r in rows if r["margin"] is not None]
        net_costed = sum(r["revenue_net"] for r in costed)
        margin_costed = sum(r["margin"] for r in costed)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": {
                "sku_count": len(rows),
                "sku_costed": len(costed),
                "revenue": round(sum(r["revenue"] for r in rows), 2),
                "revenue_net": round(sum(r["revenue_net"] for r in rows), 2),
                "cogs_costed": round(sum(r["cogs"] for r in costed), 2),
                "margin_costed": round(margin_costed, 2),
                "margin_pct_costed": round(100 * margin_costed / net_costed, 1) if net_costed else None,
                "marked_count": sum(1 for r in rows if r["marked"]),
            },
            "abc": abc,
            "skus": rows,
        }

    async def _refs(self, kind: str) -> dict:
        return {r.external_ref: r.name for r in (await self.session.execute(select(CbRef).where(
            CbRef.company_id == self.company_id, CbRef.kind == kind))).scalars().all()}

    def _avg_cost(self, purch_metas: list[dict]) -> dict:
        """Средневзвешенная net-себестоимость по GUID из поступлений."""
        pc: dict[str, dict] = defaultdict(lambda: {"c": 0.0, "q": 0.0})
        for m in purch_metas:
            for ln in (m.get("Документ") or {}).get("Товары") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                pc[g]["c"] += float(ln.get("Сумма") or 0) - float(ln.get("СуммаНДС") or 0)
                pc[g]["q"] += float(ln.get("Количество") or 0)
        return {g: (v["c"] / v["q"]) for g, v in pc.items() if v["q"]}

    # ── Приёмка (реестр поступлений) ──
    async def receipts(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = await self._load_purchases(date_from, date_to, stations)
        cparty = await self._refs("counterparty")
        docs = []
        tot_net = tot_vat = 0.0
        for m in metas:
            d = m.get("Документ") or {}
            lines = d.get("Товары") or []
            amt = sum(float(l.get("Сумма") or 0) for l in lines)
            vat = sum(float(l.get("СуммаНДС") or 0) for l in lines)
            docs.append({
                "date": str(d.get("Дата") or "")[:10],
                "number": d.get("Номер"),
                "supplier": cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—"),
                "positions": len(lines),
                "amount": round(amt, 2), "vat": round(vat, 2), "amount_net": round(amt - vat, 2),
            })
            tot_net += amt - vat
            tot_vat += vat
        docs.sort(key=lambda x: x["date"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "docs": docs,
            "summary": {"count": len(docs), "amount_net": round(tot_net, 2), "vat": round(tot_vat, 2)},
        }

    # ── Поставщики ──
    async def suppliers(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = await self._load_purchases(date_from, date_to, stations)
        cparty = await self._refs("counterparty")
        agg: dict[str, dict] = defaultdict(lambda: {"net": 0.0, "docs": 0, "skus": set()})
        for m in metas:
            d = m.get("Документ") or {}
            c = d.get("Контрагент") or "—"
            lines = d.get("Товары") or []
            agg[c]["net"] += sum(float(l.get("Сумма") or 0) - float(l.get("СуммаНДС") or 0) for l in lines)
            agg[c]["docs"] += 1
            for l in lines:
                agg[c]["skus"].add(l.get("Номенклатура"))
        rows = [{
            "name": cparty.get(c) or c, "amount_net": round(v["net"], 2),
            "docs": v["docs"], "sku_count": len(v["skus"]),
        } for c, v in agg.items()]
        rows.sort(key=lambda x: -x["amount_net"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "suppliers": rows,
            "summary": {"count": len(rows), "amount_net": round(sum(r["amount_net"] for r in rows), 2)},
        }

    # ── Общепит (блюда + food-cost по ТТК) ──
    async def catering(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        avgc = self._avg_cost(await self._load_purchases(date_from, date_to, stations))
        nom = await self._names()
        dish: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "rev": 0.0, "revnet": 0.0, "cost": 0.0, "cost_known": False})
        for m in sale_metas:
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                q = float(ln.get("Количество") or 0)
                d = dish[g]
                d["qty"] += q
                d["rev"] += float(ln.get("Сумма") or 0)
                d["revnet"] += float(ln.get("Сумма") or 0) - float(ln.get("СуммаНДС") or 0)
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура")
                    iq = float(ing.get("Количество") or 0)
                    if ig in avgc:
                        d["cost"] += iq * avgc[ig]
                        d["cost_known"] = True
        rows = []
        for g, d in dish.items():
            n = nom.get(g)
            fc = (100 * d["cost"] / d["revnet"]) if d["cost_known"] and d["revnet"] else None
            rows.append({
                "guid": g, "name": (n.name if n else g[:8]),
                "qty": round(d["qty"], 2), "revenue": round(d["rev"], 2),
                "revenue_net": round(d["revnet"], 2),
                "cost": round(d["cost"], 2) if d["cost_known"] else None,
                "food_cost_pct": round(fc, 1) if fc is not None else None,
            })
        rows.sort(key=lambda x: -x["revenue"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "dishes": rows,
            "summary": {"count": len(rows), "revenue": round(sum(r["revenue"] for r in rows), 2)},
        }

    # ── Категории (Сопутка/Общепит) ──
    async def categories(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        skus = (await self.sku_analytics(date_from, date_to, stations))["skus"]
        agg: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "revenue_net": 0.0, "margin": 0.0, "margin_known": 0.0, "sku": 0, "qty": 0.0})
        for s in skus:
            c = s["category"] or "—"
            a = agg[c]
            a["revenue"] += s["revenue"]
            a["revenue_net"] += s["revenue_net"]
            a["sku"] += 1
            a["qty"] += s["qty"]
            if s["margin"] is not None:
                a["margin"] += s["margin"]
                a["margin_known"] += s["revenue_net"]
        total = sum(a["revenue"] for a in agg.values()) or 1.0
        rows = [{
            "category": c, "revenue": round(a["revenue"], 2), "revenue_net": round(a["revenue_net"], 2),
            "sku_count": a["sku"], "qty": round(a["qty"], 2),
            "share": round(100 * a["revenue"] / total, 1),
            "margin": round(a["margin"], 2) if a["margin_known"] else None,
            "margin_pct": round(100 * a["margin"] / a["margin_known"], 1) if a["margin_known"] else None,
        } for c, a in agg.items()]
        rows.sort(key=lambda x: -x["revenue"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "categories": rows,
            "summary": {"count": len(rows), "revenue": round(sum(r["revenue"] for r in rows), 2)},
        }

    # ── Штрихкоды (справочник, не по периоду) ──
    async def barcodes(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        rows = (await self.session.execute(select(CbBarcode).where(
            CbBarcode.company_id == self.company_id))).scalars().all()
        by_type: dict[str, int] = defaultdict(int)
        for r in rows:
            by_type[r.btype or "—"] += 1
        items = [{"barcode": r.barcode, "owner_name": r.owner_name, "type": r.btype, "main": r.main} for r in rows]
        items.sort(key=lambda x: x["owner_name"])
        return {
            "total": len(rows),
            "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "items": items,
        }

    # ── Рецептуры (ТТК): блюда общепита → ингредиенты ──
    async def recipes(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = self._select(await self._load(), date_from, date_to, stations)
        nom = await self._names()
        dishes: dict[str, dict] = {}
        for m in metas:
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g or g in dishes:
                    continue
                ings = []
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура")
                    n = nom.get(ig)
                    ings.append({"name": (n.name if n else str(ig)[:8]), "qty": round(float(ing.get("Количество") or 0), 3)})
                if ings:
                    dn = nom.get(g)
                    dishes[g] = {"name": (dn.name if dn else str(g)[:8]), "ingredients": ings, "ing_count": len(ings)}
        rows = sorted(dishes.values(), key=lambda x: x["name"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "recipes": rows,
            "summary": {"count": len(rows)},
        }

    # ── Номенклатура: полный справочник НСИ + обогащение продажами/ШК (главный товарный экран) ──
    async def nomenclature_catalog(self, date_from: date, date_to: date, *, kind: str = "all",
                                   marked: str = "all", weighed: str = "all", has_sales: str = "all",
                                   q: str = "", stations: list[str] | None = None) -> dict:
        nom = (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()
        kinds = await self._refs("nom_kind")
        sk = {s["guid"]: s for s in (await self.sku_analytics(date_from, date_to, stations))["skus"]}
        bc_names = {r[0] for r in (await self.session.execute(select(CbBarcode.owner_name).where(
            CbBarcode.company_id == self.company_id))).all()}
        ql = (q or "").lower().strip()

        items = []
        kinds_seen: set = set()
        for n in nom:
            if ql and not (ql in (n.name or "").lower() or ql in (n.article or "").lower()):
                continue
            if marked == "marked" and not n.marked:
                continue
            if marked == "plain" and n.marked:
                continue
            if weighed == "weighed" and not n.weighed:
                continue
            s = sk.get(n.external_ref)
            if has_sales == "yes" and not s:
                continue
            if has_sales == "no" and s:
                continue
            kind_name = (kinds.get(n.kind_ref) or "— вид не указан") if n.kind_ref else "— вид не указан"
            if kind != "all" and kind_name != kind:
                continue
            kinds_seen.add(kind_name)
            items.append({
                "guid": n.external_ref, "name": n.name, "article": n.article, "vat": n.vat,
                "marked": n.marked, "weighed": n.weighed, "kind": kind_name,
                "has_barcode": n.name in bc_names,
                "revenue": s["revenue"] if s else 0.0, "qty": s["qty"] if s else 0.0,
            })
        items.sort(key=lambda x: (-x["revenue"], x["name"]))
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "marked": sum(1 for i in items if i["marked"]),
                "weighed": sum(1 for i in items if i["weighed"]),
                "with_sales": sum(1 for i in items if i["revenue"]),
                "with_barcode": sum(1 for i in items if i["has_barcode"]),
            },
            "kinds": sorted(kinds_seen),
        }

    # ── Продажи: гибкая группировка + фильтры (инструмент менеджера) ──
    async def sales_analysis(self, date_from: date, date_to: date, *, group_by: str = "sku",
                             category: str = "all", marked: str = "all", q: str = "",
                             stations: list[str] | None = None) -> dict:
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        nom = await self._names()
        kinds = await self._refs("nom_kind")
        ql = (q or "").lower().strip()

        agg: dict[str, dict] = defaultdict(lambda: {"rev": 0.0, "net": 0.0, "vat": 0.0, "qty": 0.0, "skus": set(), "label": ""})
        shifts = len(sale_metas)

        # payment — по секции оплат, не по строкам товаров
        if group_by == "payment":
            for m in sale_metas:
                for o in ((m.get("Секции") or {}).get("оплаты") or {}).get("строки") or []:
                    kanon = str(o.get("ФормаОплатыКанон") or o.get("ФормаОплаты") or "—")
                    amt = float(o.get("Сумма") or 0)
                    a = agg[kanon]
                    a["rev"] += amt
                    a["net"] += amt * 100.0 / 122.0
                    a["vat"] += amt - amt * 100.0 / 122.0
                    a["label"] = kanon
        else:
            for m in sale_metas:
                day = _day(m.get("Смена") or {})
                sec = m.get("Секции") or {}
                for sec_key, catname in _SECTIONS:
                    if category == "soputka" and sec_key != "продажа_сопутка":
                        continue
                    if category == "obshepit" and sec_key != "продажа_общепит":
                        continue
                    for ln in (sec.get(sec_key) or {}).get("строки") or []:
                        g = ln.get("Номенклатура")
                        n = nom.get(g)
                        is_marked = bool(n and n.marked)
                        if marked == "marked" and not is_marked:
                            continue
                        if marked == "plain" and is_marked:
                            continue
                        if ql and not ((n and ql in (n.name or "").lower()) or (ql in str(g or "").lower())):
                            continue
                        summ = float(ln.get("Сумма") or 0)
                        vat = float(ln.get("СуммаНДС") or 0)
                        qty = float(ln.get("Количество") or 0)

                        if group_by == "category":
                            key, label = catname, catname
                        elif group_by == "kind":
                            kr = n.kind_ref if n else None
                            key = kr or "—"
                            label = kinds.get(kr, "— вид не указан")
                        elif group_by == "marking":
                            key = "marked" if is_marked else "plain"
                            label = "Маркированные (ЧЗ)" if is_marked else "Обычные товары"
                        elif group_by == "vat":
                            key = str(ln.get("СтавкаНДС") or (n.vat if n else None) or "—")
                            label = key
                        elif group_by == "day":
                            key = label = day
                        else:  # sku
                            key = g or "—"
                            label = (n.name if n else str(g)[:8])

                        a = agg[key]
                        a["rev"] += summ
                        a["net"] += summ - vat
                        a["vat"] += vat
                        a["qty"] += qty
                        a["skus"].add(g)
                        a["label"] = label

        total = sum(a["rev"] for a in agg.values()) or 1.0
        groups = [{
            "key": k, "label": a["label"] or k,
            "revenue": round(a["rev"], 2), "revenue_net": round(a["net"], 2), "vat": round(a["vat"], 2),
            "qty": round(a["qty"], 3), "sku_count": len(a["skus"]),
            "share": round(100 * a["rev"] / total, 1),
        } for k, a in agg.items()]
        groups.sort(key=lambda x: (x["key"] if group_by == "day" else -x["revenue"]))

        all_skus: set = set()
        for a in agg.values():
            all_skus |= a["skus"]
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "group_by": group_by,
            "filters": {"category": category, "marked": marked, "q": q},
            "groups": groups,
            "summary": {
                "revenue": round(sum(a["rev"] for a in agg.values()), 2),
                "revenue_net": round(sum(a["net"] for a in agg.values()), 2),
                "vat": round(sum(a["vat"] for a in agg.values()), 2),
                "qty": round(sum(a["qty"] for a in agg.values()), 3),
                "sku_count": len(all_skus),
                "shifts": shifts,
                "groups_count": len(groups),
            },
        }
