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

from app.models import DataEntry, CbNomenclature, CbRef, CbBarcode, StockOnHand, CbInventoryDoc, CbMovementDoc

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

    # ── Общепит — инжиниринг меню (продажи блюд + состав ТТК + динамика) ──
    async def catering_menu(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        """Менеджерская аналитика общепита: по каждому блюду — продажи, фудкост, маржа,
        класс меню (Звезда/Загадка/Рабочая лошадка/Собака), состав ТТК (ингредиенты с
        себестоимостью на порцию) и дневная динамика продаж (для раскрытия строки)."""
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        avgc = self._avg_cost(await self._load_purchases(date_from, date_to, stations))
        nom = await self._names()

        def _dish():
            return {"qty": 0.0, "rev": 0.0, "revnet": 0.0, "cost": 0.0, "cost_known": False,
                    "ings": defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "known": False}),
                    "daily": defaultdict(lambda: {"qty": 0.0, "rev": 0.0})}
        dishes: dict[str, dict] = defaultdict(_dish)
        for m in sale_metas:
            day = _day(m.get("Смена") or {})
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                q = float(ln.get("Количество") or 0)
                rev = float(ln.get("Сумма") or 0)
                revnet = rev - float(ln.get("СуммаНДС") or 0)
                d = dishes[g]
                d["qty"] += q; d["rev"] += rev; d["revnet"] += revnet
                dd = d["daily"][day]; dd["qty"] += q; dd["rev"] += rev
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура"); iq = float(ing.get("Количество") or 0)
                    ii = d["ings"][ig]; ii["qty"] += iq
                    if ig in avgc:
                        c = iq * avgc[ig]; ii["cost"] += c; ii["known"] = True
                        d["cost"] += c; d["cost_known"] = True

        total_rev = sum(x["rev"] for x in dishes.values()) or 1.0
        total_qty = sum(x["qty"] for x in dishes.values()) or 1.0
        n_dishes = len(dishes) or 1
        # классический порог популярности Kasavana–Smith: 70% от равной доли
        pop_threshold = (100.0 / n_dishes) * 0.7
        costed_margin = sum((x["revnet"] - x["cost"]) for x in dishes.values() if x["cost_known"])
        costed_qty = sum(x["qty"] for x in dishes.values() if x["cost_known"]) or 1.0
        avg_cm = costed_margin / costed_qty  # средняя вклад-маржа на порцию

        matrix: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
        rows = []
        for g, d in dishes.items():
            nnn = nom.get(g)
            qty, rev, revnet = d["qty"], d["rev"], d["revnet"]
            cost = d["cost"] if d["cost_known"] else None
            margin = (revnet - cost) if cost is not None else None
            food_cost = (100 * cost / revnet) if cost is not None and revnet else None
            margin_pct = (100 * margin / revnet) if margin is not None and revnet else None
            cm_unit = (margin / qty) if margin is not None and qty else None
            pop = 100 * qty / total_qty
            if cost is None:
                cls = "unknown"
            else:
                high_pop = pop >= pop_threshold
                high_cm = (cm_unit or 0) >= avg_cm
                cls = ("star" if high_pop and high_cm else
                       "plowhorse" if high_pop and not high_cm else
                       "puzzle" if not high_pop and high_cm else "dog")
            matrix[cls]["count"] += 1; matrix[cls]["revenue"] += rev
            ings = []
            for ig, ii in d["ings"].items():
                inm = nom.get(ig)
                ings.append({
                    "ref": ig, "name": (inm.name if inm else str(ig)[:8]),
                    "marked": bool(inm and inm.marked),
                    "qty_total": round(ii["qty"], 3),
                    "qty_per_portion": round(ii["qty"] / qty, 4) if qty else None,
                    "cost_total": round(ii["cost"], 2) if ii["known"] else None,
                    "cost_per_portion": round(ii["cost"] / qty, 4) if ii["known"] and qty else None,
                })
            ings.sort(key=lambda x: -(x["cost_total"] or 0))
            daily = [{"date": dt, "qty": round(v["qty"], 2), "revenue": round(v["rev"], 2)}
                     for dt, v in sorted(d["daily"].items())]
            rows.append({
                "guid": g, "name": (nnn.name if nnn else str(g)[:8]),
                "qty": round(qty, 2), "revenue": round(rev, 2), "revenue_net": round(revnet, 2),
                "avg_price": round(rev / qty, 2) if qty else 0.0,
                "cost": round(cost, 2) if cost is not None else None,
                "cost_per_portion": round(cost / qty, 2) if cost is not None and qty else None,
                "margin": round(margin, 2) if margin is not None else None,
                "food_cost_pct": round(food_cost, 1) if food_cost is not None else None,
                "margin_pct": round(margin_pct, 1) if margin_pct is not None else None,
                "cm_unit": round(cm_unit, 2) if cm_unit is not None else None,
                "share": round(100 * rev / total_rev, 1),
                "popularity_pct": round(pop, 1),
                "menu_class": cls,
                "ing_count": len(ings),
                "ingredients": ings,
                "daily": daily,
            })
        rows.sort(key=lambda x: -x["revenue"])

        tot_cost = sum(r["cost"] for r in rows if r["cost"] is not None)
        tot_revnet_costed = sum(r["revenue_net"] for r in rows if r["cost"] is not None)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": {
                "dishes_count": len(rows),
                "dishes_costed": sum(1 for r in rows if r["cost"] is not None),
                "revenue": round(sum(r["revenue"] for r in rows), 2),
                "revenue_net": round(sum(r["revenue_net"] for r in rows), 2),
                "portions": round(sum(r["qty"] for r in rows), 2),
                "cost": round(tot_cost, 2),
                "margin": round(tot_revnet_costed - tot_cost, 2),
                "food_cost_pct": round(100 * tot_cost / tot_revnet_costed, 1) if tot_revnet_costed else None,
                "margin_pct": round(100 * (tot_revnet_costed - tot_cost) / tot_revnet_costed, 1) if tot_revnet_costed else None,
            },
            "matrix": {k: {"count": v["count"], "revenue": round(v["revenue"], 2)} for k, v in matrix.items()},
            "dishes": rows,
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

    # ── Остатки: достоверный остаток из регистров ЦБ (StockOnHand) ──
    async def stock_onhand(self, *, warehouse: str | None = None, q: str = "",
                           marked: str = "all", only_negative: bool = False) -> dict:
        """Достоверный остаток товара (снимок регистров ЦБ), не оценка stock_est.

        warehouse — код склада (по умолчанию склад с наибольшим числом SKU, обычно 208
        Торговый зал). Возвращает позиции выбранного склада + список складов для селектора.
        """
        rows = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id))).scalars().all()
        nom = await self._names()

        # склады: сводка (код → имя, SKU, стоимость остатка) для селектора
        wh_agg: dict[str, dict] = defaultdict(lambda: {"name": None, "sku": 0, "retail_value": 0.0})
        for r in rows:
            w = wh_agg[r.warehouse_code]
            w["name"] = r.warehouse_name
            w["sku"] += 1
            w["retail_value"] += float(r.quantity or 0) * float(r.retail_price or 0)
        warehouses = [{
            "code": c, "name": v["name"], "sku": v["sku"],
            "retail_value": round(v["retail_value"], 2),
        } for c, v in wh_agg.items()]
        warehouses.sort(key=lambda x: -x["sku"])

        # склад по умолчанию — с наибольшим числом SKU
        wh = warehouse or (warehouses[0]["code"] if warehouses else None)
        ql = (q or "").lower().strip()

        items = []
        for r in rows:
            if wh and r.warehouse_code != wh:
                continue
            n = nom.get(r.nomenclature_ref)
            is_marked = bool(n and n.marked)
            if marked == "marked" and not is_marked:
                continue
            if marked == "plain" and is_marked:
                continue
            name = n.name if n else r.nomenclature_ref[:8]
            if ql and not (ql in (name or "").lower() or ql in (r.barcode or "")):
                continue
            qty = float(r.quantity or 0)
            if only_negative and qty >= 0:
                continue
            price = float(r.retail_price) if r.retail_price is not None else None
            retail_value = round(qty * price, 2) if price is not None else None
            # себест. остатка и маржа из удельной себест. партий (базовые единицы —
            # совпадают с остатком, корректно для блоков/весовых).
            cu = float(r.cost_unit) if r.cost_unit is not None else None
            cost_amount = round(qty * cu, 2) if cu is not None else None
            margin = (round(retail_value - cost_amount, 2)
                      if retail_value is not None and cost_amount is not None else None)
            margin_pct = (round(100 * margin / retail_value, 1)
                          if margin is not None and retail_value else None)
            items.append({
                "guid": r.nomenclature_ref,
                "name": name,
                "article": (n.article if n else None),
                "vat": (n.vat if n else None),
                "marked": is_marked,
                "weighed": bool(n and n.weighed),
                "barcode": r.barcode,
                "qty": round(qty, 3),
                "negative": qty < 0,
                "retail_price": round(price, 2) if price is not None else None,
                "retail_value": retail_value,
                "cost_unit": round(cu, 4) if cu is not None else None,
                "cost_amount": cost_amount,
                "margin": margin,
                "margin_pct": margin_pct,
            })
        items.sort(key=lambda x: (x["retail_value"] is None, -(x["retail_value"] or 0)))

        pos = [i for i in items if i["qty"] > 0]
        neg = [i for i in items if i["qty"] < 0]
        costed = [i for i in pos if i["cost_amount"] is not None]
        cost_value = sum(i["cost_amount"] for i in costed)
        retail_costed = sum((i["retail_value"] or 0) for i in costed)
        return {
            "warehouse": wh,
            "warehouses": warehouses,
            "items": items,
            "summary": {
                "sku_count": len(items),
                "positive": len(pos),
                "negative": len(neg),
                # стоимость товара на полке (только положительный остаток) — надёжная метрика;
                # retail_value_all включает отрицательные позиции (для сверки).
                "retail_value_positive": round(sum((i["retail_value"] or 0) for i in pos), 2),
                "retail_value_all": round(sum((i["retail_value"] or 0) for i in items), 2),
                # себест. остатка (закуп.) и потенц. маржа «на полке» — по costed-позициям
                "cost_value": round(cost_value, 2),
                "costed_count": len(costed),
                "margin_value": round(retail_costed - cost_value, 2),
                "margin_pct": round(100 * (retail_costed - cost_value) / retail_costed, 1) if retail_costed else None,
                "marked_count": sum(1 for i in items if i["marked"]),
                "units_positive": round(sum(i["qty"] for i in pos), 3),
            },
        }

    # ── Инвентаризация: реестр + отклонения факт↔учёт (недостачи/излишки) ──
    async def inventory(self, *, warehouse: str | None = None, only_dev: bool = False) -> dict:
        """Реестр инвентаризаций ЦБ + агрегаты недостач/излишков (shrinkage).

        warehouse — код склада (по умолч. все склады магазина). only_dev — только
        документы с отклонениями. Строки-отклонения (lines) — для drill-down.
        """
        docs = (await self.session.execute(select(CbInventoryDoc).where(
            CbInventoryDoc.company_id == self.company_id))).scalars().all()

        # склады для селектора
        wh_agg: dict[str, dict] = defaultdict(lambda: {"name": None, "count": 0})
        for d in docs:
            w = wh_agg[d.warehouse_code]
            w["name"] = d.warehouse_name
            w["count"] += 1
        warehouses = [{"code": c, "name": v["name"], "count": v["count"]}
                      for c, v in sorted(wh_agg.items(), key=lambda x: -x[1]["count"])]

        sel = [d for d in docs if (not warehouse or d.warehouse_code == warehouse)]
        if only_dev:
            sel = [d for d in sel if d.dev_positions]

        out_docs = []
        sku_short: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_sh = tot_su = 0.0
        dates = []
        for d in sel:
            tot_sh += float(d.shortage_amount or 0)
            tot_su += float(d.surplus_amount or 0)
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                if ln.get("dev", 0) < 0:  # недостача — копим по SKU
                    k = ln.get("ref") or ln.get("name")
                    s = sku_short[k]
                    s["name"] = ln.get("name")
                    s["qty"] += float(ln.get("dev") or 0)
                    s["amount"] += float(ln.get("amount_dev") or 0)
                    s["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "comment": d.comment, "dev_positions": d.dev_positions,
                "shortage_qty": float(d.shortage_qty or 0), "shortage_amount": float(d.shortage_amount or 0),
                "surplus_qty": float(d.surplus_qty or 0), "surplus_amount": float(d.surplus_amount or 0),
                "net_amount": float(d.net_amount or 0),
                "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        top_short = sorted(sku_short.values(), key=lambda x: x["amount"])[:12]
        for t in top_short:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "warehouse": warehouse,
            "warehouses": warehouses,
            "docs": out_docs,
            "top_shortage": top_short,
            "summary": {
                "docs_count": len(sel),
                "docs_with_dev": sum(1 for d in sel if d.dev_positions),
                "shortage_amount": round(tot_sh, 2),
                "surplus_amount": round(tot_su, 2),
                "net_amount": round(tot_sh + tot_su, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Списания: реестр + причины (недостача/брак/…) + топ списанных SKU ──
    async def writeoffs(self, *, warehouse: str | None = None, reason: str | None = None) -> dict:
        """Реестр списаний ЦБ (СписаниеТоваров) + разбивка по причинам и топ SKU."""
        docs = (await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.kind == "writeoff"))).scalars().all()

        wh_agg: dict[str, dict] = defaultdict(lambda: {"name": None, "count": 0})
        reasons_all: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for d in docs:
            w = wh_agg[d.warehouse_code]; w["name"] = d.warehouse_name; w["count"] += 1
        warehouses = [{"code": c, "name": v["name"], "count": v["count"]}
                      for c, v in sorted(wh_agg.items(), key=lambda x: -x[1]["count"])]

        sel = [d for d in docs if (not warehouse or d.warehouse_code == warehouse)
               and (not reason or d.reason == reason)]

        out_docs = []
        sku: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_amt = inv_amt = 0.0
        dates = []
        for d in sel:
            amt = float(d.total_amount or 0)
            tot_amt += amt
            if d.from_inventory:
                inv_amt += amt
            reasons_all[d.reason or "Прочее"]["count"] += 1
            reasons_all[d.reason or "Прочее"]["amount"] += amt
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                k = ln.get("ref") or ln.get("name")
                sk = sku[k]; sk["name"] = ln.get("name")
                sk["qty"] += float(ln.get("qty") or 0)
                sk["amount"] += float(ln.get("amount") or 0)
                sk["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "reason": d.reason, "from_inventory": d.from_inventory, "comment": d.comment,
                "positions": d.positions, "total_qty": float(d.total_qty or 0),
                "total_amount": amt, "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        by_reason = [{"reason": r, "count": v["count"], "amount": round(v["amount"], 2)}
                     for r, v in sorted(reasons_all.items(), key=lambda x: -x[1]["amount"])]
        top_sku = sorted(sku.values(), key=lambda x: -x["amount"])[:12]
        for t in top_sku:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "warehouse": warehouse,
            "warehouses": warehouses,
            "docs": out_docs,
            "by_reason": by_reason,
            "top_sku": top_sku,
            "summary": {
                "docs_count": len(sel),
                "total_amount": round(tot_amt, 2),
                "from_inventory_amount": round(inv_amt, 2),
                "other_amount": round(tot_amt - inv_amt, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Перемещения: реестр откуда→куда + направления (внутр/приход/расход) ──
    async def transfers(self, *, direction: str | None = None) -> dict:
        """Реестр перемещений ЦБ (ПеремещениеТоваров) относительно складов магазина.

        Сумма = розн. стоимость перемещённого (Количество × Цена; себестоимость у
        внутренних перемещений не заполнена). direction — фильтр по направлению.
        """
        docs = (await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.kind == "transfer"))).scalars().all()

        dirs_all: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for d in docs:
            dirs_all[d.reason or "Прочее"]["count"] += 1
            dirs_all[d.reason or "Прочее"]["amount"] += float(d.total_amount or 0)

        sel = [d for d in docs if (not direction or d.reason == direction)]

        out_docs = []
        sku: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_amt = 0.0
        dates = []
        for d in sel:
            amt = float(d.total_amount or 0)
            tot_amt += amt
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                k = ln.get("ref") or ln.get("name")
                sk = sku[k]; sk["name"] = ln.get("name")
                sk["qty"] += float(ln.get("qty") or 0)
                sk["amount"] += float(ln.get("amount") or 0)
                sk["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "from_code": d.warehouse_code, "from_name": d.warehouse_name,
                "to_code": d.warehouse_to_code, "to_name": d.warehouse_to_name,
                "direction": d.reason, "comment": d.comment,
                "positions": d.positions, "total_qty": float(d.total_qty or 0),
                "total_amount": amt, "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        by_direction = [{"direction": r, "count": v["count"], "amount": round(v["amount"], 2)}
                        for r, v in sorted(dirs_all.items(), key=lambda x: -x[1]["amount"])]
        top_sku = sorted(sku.values(), key=lambda x: -x["amount"])[:12]
        for t in top_sku:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "direction": direction,
            "docs": out_docs,
            "by_direction": by_direction,
            "top_sku": top_sku,
            "summary": {
                "docs_count": len(sel),
                "total_amount": round(tot_amt, 2),
                "inbound_amount": round(dirs_all.get("Приход (на 208)", {}).get("amount", 0.0), 2),
                "outbound_amount": round(dirs_all.get("Расход (с 208)", {}).get("amount", 0.0), 2),
                "internal_amount": round(dirs_all.get("Внутреннее (склад↔зал)", {}).get("amount", 0.0), 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Переоценка: реестр изменений цен + подорожания/удешевления ──
    async def revaluation(self, *, reason: str | None = None) -> dict:
        """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая розн. цена,
        Δ%, влияние на стоимость остатка (Σ Δ×кол). reason — фильтр направления."""
        docs = (await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.kind == "revaluation"))).scalars().all()

        reasons_all: dict[str, dict] = defaultdict(lambda: {"count": 0})
        for d in docs:
            reasons_all[d.reason or "—"]["count"] += 1

        sel = [d for d in docs if (not reason or d.reason == reason)]

        out_docs = []
        up_lines = down_lines = 0
        pct_sum = pct_n = 0.0
        impact = 0.0
        dates = []
        best_by_sku: dict[str, dict] = {}  # SKU → строка с макс |delta|
        for d in sel:
            impact += float(d.total_amount or 0)
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                delta = float(ln.get("delta") or 0)
                if delta > 0:
                    up_lines += 1
                elif delta < 0:
                    down_lines += 1
                if ln.get("pct") is not None:
                    pct_sum += float(ln["pct"]); pct_n += 1
                k = ln.get("ref") or ln.get("name")
                prev = best_by_sku.get(k)
                if prev is None or abs(delta) > abs(prev["delta"]):
                    best_by_sku[k] = {"name": ln.get("name"), "old": ln.get("old"),
                                      "new": ln.get("new"), "delta": delta, "pct": ln.get("pct")}
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "reason": d.reason, "comment": d.comment,
                "positions": d.positions, "up_count": int(d.total_qty or 0),
                "value_impact": float(d.total_amount or 0), "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        moves = list(best_by_sku.values())
        top_up = sorted([m for m in moves if (m["pct"] or 0) > 0], key=lambda x: -(x["pct"] or 0))[:10]
        top_down = sorted([m for m in moves if (m["pct"] or 0) < 0], key=lambda x: (x["pct"] or 0))[:10]
        by_reason = [{"reason": r, "count": v["count"]}
                     for r, v in sorted(reasons_all.items(), key=lambda x: -x[1]["count"])]

        return {
            "reason": reason,
            "docs": out_docs,
            "by_reason": by_reason,
            "top_up": top_up,
            "top_down": top_down,
            "summary": {
                "docs_count": len(sel),
                "up_lines": up_lines, "down_lines": down_lines,
                "avg_pct": round(pct_sum / pct_n, 1) if pct_n else None,
                "value_impact": round(impact, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
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
