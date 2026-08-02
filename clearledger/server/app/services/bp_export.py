"""
Эмиттер пакета «смена ЦБ→БП» (Фаза 2) — Ledger как продюсер пакетов вместо
1С-обработки TL_ЭкспортБП. Собирает JSON-пакет строго по контракту
STORE_BP_EXPORT_CONTRACT.md из наших данных (DataEntry.meta + CbNomenclature/
CbRef/StockOnHand), считает ХешПакета через bp_canon.

СТАТУС: ядро продажного контура (Смена + retail_sale_sidegoods + Оплаты + НСИ).
⚠ ПРОБЕЛЫ Фазы 1 (нужно добрать из ЦБ, помечено TODO-Ф1):
  - НСИ Номенклатура.КодЦБ — не тянули Код (сейчас "" → приёмник мягко матчит по имени).
  - НСИ Организация.ИНН/КПП/ОГРН — не тянули справочник организаций (известные — по карте ORG_REQ).
  - НСИ Склад.ВидСклада — константа "АЗК" (не тянули).
  - Типы purchase(B2B-поля)/production_release/return_purchase/gain/recipe — отдельно.
"""
from __future__ import annotations

import json as _json
import os as _os
import re as _re
import uuid as _uuid
from datetime import datetime

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, CbNomenclature, StockOnHand, CbRef, CbInventoryDoc, CbMovementDoc
from app.services.bp_canon import packet_hash
from app.services.goods_dashboard import _day

_WH_208 = {"208", "20800002"}   # склады станции 208 (Торговый зал + Склад)

# СтавкаНДС ЦБ («22%») → каноническое имя контракта («НДС22»). §4.
_NDS_MAP = {
    "22%": "НДС22", "20%": "НДС20", "18%": "НДС18", "10%": "НДС10",
    "7%": "НДС7", "5%": "НДС5", "0%": "НДС0",
    "18% / 118%": "НДС18_118", "20% / 120%": "НДС20_120", "22% / 122%": "НДС22_122",
    "10% / 110%": "НДС10_110", "5% / 105%": "НДС5_105", "7% / 107%": "НДС7_107",
    "без ндс": "БезНДС", "безндс": "БезНДС",
}

# Ставки, которые сопоставляет приёмник (TL_МаппингЦБ.СопоставитьСтавкуНДС). Всё, что
# вне списка, роняет документ в поступлениях и возвратах поставщику.
_BP_VAT_NAMES = frozenset(_NDS_MAP.values())


def _nds(v: str | None) -> str:
    """Канон-имя ставки. Пусто → "", неизвестное → исходная строка ЦБ.

    Неизвестную ставку нельзя ни обнулять, ни подменять: приёмник на несопоставленной
    ставке роняет документ (`ВызватьИсключение "Ставка НДС '…' не сопоставлена"`), и в
    TL_ОшибкиЗагрузки бухгалтер должен увидеть, ЧТО пришло из ЦБ, — с пустой строкой
    сообщение бесполезно. Возврат исходного значения заодно гасит фолбэк `_nds(строка)
    or _nds(ставка_номенклатуры)`: подставлять справочную ставку вместо непонятой —
    это ошибка приёмника Норд-Лайна (НДС10 пищевки молча становился НДС22), от которой
    контракт и защищается. Фолбэк остаётся работать там, где ставки в ЦБ просто нет.
    """
    v = (v or "").strip()
    return _NDS_MAP.get(v.lower(), _NDS_MAP.get(v, v))


def _iso(v) -> str:
    """ISO с таймзоной +03:00. На входе — ISO-строка из meta (уже +00:00) или пусто."""
    if not v:
        return ""
    s = str(v)
    # meta хранит +00:00; контракт БП — локальное +03:00. Пересчёт не делаем
    # (смены ЦБ уже в локальном времени станции) — только нормализуем суффикс.
    return s.replace("+00:00", "+03:00")


def _new_packet_uuid() -> str:
    return str(_uuid.uuid4())


def package_filename(pkt: dict) -> str:
    """Имя файла пакета по контракту: АЗС{код}_{ГГГГ-ММ-ДД}_смена-{номер}_{uuid}.json."""
    sh = pkt.get("Смена") or {}
    код = str(sh.get("КодАЗС") or 0)
    код = код.zfill(3) if код.isdigit() else "0"
    дата = str(sh.get("Открытие") or "")[:10] or "0000-00-00"
    ном = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(sh.get("НомерСмены") or "").strip()) or "0"
    return f"АЗС{код}_{дата}_смена-{ном}_{pkt.get('ИдентификаторПакета')}.json"


class BpPackageEmitter:
    def __init__(self, session: AsyncSession, company_id):
        self.session = session
        self.company_id = company_id

    async def _nom_map(self) -> dict[str, CbNomenclature]:
        rows = (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()
        return {n.external_ref: n for n in rows}

    async def _refs(self, kind: str) -> dict[str, CbRef]:
        rows = (await self.session.execute(select(CbRef).where(
            CbRef.company_id == self.company_id, CbRef.kind == kind))).scalars().all()
        return {r.external_ref: r for r in rows}

    async def build_shift_package(self, shift_key: str) -> dict:
        """Собрать пакет для одной смены (retail_sale + НСИ). shift_key = GUID смены."""
        # найти retail-запись смены
        rows = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "retail_sale_sidegoods"))).scalars().all()
        target = None
        for r in rows:
            sm = (r.meta or {}).get("Смена") or {}
            k = str(sm.get("Смена") or f"{_day(sm)}|{sm.get('КодАЗС') or '—'}")
            if k == shift_key:
                target = r
                break
        if target is None:
            raise ValueError(f"смена не найдена: {shift_key}")

        meta = target.meta or {}
        sm = meta.get("Смена") or {}
        nom = await self._nom_map()
        orgs = await self._refs("organization")
        whs = await self._refs("warehouse")
        kinds = await self._refs("nom_kind")

        # кэш UUID для НСИ
        nsi_nom: set[str] = set()
        nsi_org: set[str] = set()
        nsi_wh: set[str] = set()
        nsi_contr: set[str] = set()
        contr_names: dict[str, str] = {}
        dish_uuids: set[str] = set()  # блюда общепита смены → эмитим их recipe (ТТК)
        dish_inline_ings: dict[str, list] = {}  # OB-1: inline-ТТК из строк продаж (фолбэк)

        org_uuid = str(sm.get("Организация") or "")
        wh_uuid = str(sm.get("Склад") or "")
        if org_uuid:
            nsi_org.add(org_uuid)
        if wh_uuid:
            nsi_wh.add(wh_uuid)

        # ── Смена (шапка) ──
        код = 0
        try:
            код = int(str(sm.get("КодАЗС") or "0").strip() or 0)
        except ValueError:
            код = 0
        shift = {
            "КодАЗС": код,
            "СкладUUID": wh_uuid,
            "ОрганизацияUUID": org_uuid,
            "НомерСмены": str(sm.get("НомерСмены") or sm.get("ОСЭНомер") or "").strip(),
            "НомерСменыВнутр": sm.get("НомерСменыВнутр") or 0,
            "Открытие": _iso(sm.get("Открытие")),
            "Закрытие": _iso(sm.get("Закрытие")),
            "Оператор": "",
            "Касса": str(sm.get("Касса") or "").strip(),
            "ОСЭНомер": str(sm.get("ОСЭНомер") or sm.get("НомерСмены") or "").strip(),
        }

        # ── retail_sale_sidegoods ──
        sec = meta.get("Секции") or {}
        doc_meta = meta.get("Документ") or {}
        товары = []
        сумма_ндс_итого = 0.0
        сумма_док = 0.0
        n = 0
        for sec_key, класс in (("продажа_сопутка", "Сопутка"), ("продажа_общепит", "Общепит")):
            for ln in (sec.get(sec_key) or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                n += 1
                сумма = float(ln.get("Сумма") or 0)
                ндс = float(ln.get("СуммаНДС") or 0)
                сумма_ндс_итого += ндс
                сумма_док += сумма
                строка = {
                    "НомерСтроки": ln.get("НомерСтроки") or n,
                    "Номенклатура": g,
                    "Единица": (nom[g].unit if nom.get(g) else "") or "",
                    "Количество": float(ln.get("Количество") or 0),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(сумма, 2),
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")),
                    "СуммаНДС": round(ндс, 2),
                    "КлассSKU": класс,
                }
                if класс == "Общепит":
                    строка["ЭтоБлюдо"] = True
                    if g:
                        dish_uuids.add(g)
                        # OB-1: inline-ТТК из строки продажи (cb_normalize._expand_dish) —
                        # фолбэк, если recipe-DataEntry для блюда нет (иначе блюдо ушло
                        # бы в БП без ТТК и списалось с 41.02 в минус).
                        inl = [{"НоменклатураUUID": str(i.get("Номенклатура") or ""),
                                "Количество": float(i.get("Количество") or 0),
                                "БлюдоНаименование": (nom[g].name if nom.get(g) else "")}
                               for i in (ln.get("Ингредиенты") or [])
                               if i.get("Номенклатура")]
                        if inl:
                            dish_inline_ings[g] = inl
                товары.append(строка)

        оплаты = []
        for o in (sec.get("оплаты") or {}).get("строки") or []:
            вид = str(o.get("ФормаОплаты") or o.get("ФормаОплатыКанон") or "").strip()
            if "нал" in вид.lower():
                вид = "Наличные"
            оплаты.append({"ВидОплаты": вид, "Сумма": round(float(o.get("Сумма") or 0), 2)})

        # ── ВозвращенныеТовары (возвраты покупателей смены) — P1-фикс, раньше [] ──
        возвраты = []
        for i, ln in enumerate((sec.get("возвраты") or {}).get("строки") or [], 1):
            g = ln.get("Номенклатура")
            if g:
                nsi_nom.add(g)
            возвраты.append({
                "НомерСтроки": ln.get("НомерСтроки") or i,
                "Номенклатура": g,
                "Единица": (nom[g].unit if nom.get(g) else "") or "",
                "Количество": float(ln.get("Количество") or 0),
                "Цена": float(ln.get("Цена") or 0),
                "Сумма": round(float(ln.get("Сумма") or 0), 2),
                "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nom[g].vat if nom.get(g) else ""),
                "СуммаНДС": round(float(ln.get("СуммаНДС") or 0), 2),
            })

        retail = {
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": str(doc_meta.get("ИсточникUUID") or sm.get("Смена") or ""),
            "Номер": str(sm.get("НомерСмены") or "").strip(),
            "Дата": _iso(sm.get("Закрытие")),
            # П3-фикс: Проведен/ПометкаУдаления из ОРП ЦБ, не хардкод
            "Проведен": bool(doc_meta.get("Проведен", True)),
            "ПометкаУдаления": bool(doc_meta.get("ПометкаУдаления", False)),
            "Организация": org_uuid,
            "Склад": wh_uuid,
            "Подразделение": "",
            "СуммаДокумента": round(сумма_док, 2),
            "ВалютаДокумента": "RUB",
            "СуммаВключаетНДС": True,
            "Товары": товары,
            "ВозвращенныеТовары": возвраты,
            "СуммаНДС": round(сумма_ндс_итого, 2),
            "Оплаты": оплаты,
        }

        # ── purchase (приходы смены) ──
        # приход-DataEntry линкуется к смене через meta.Смена; per-line СтавкаНДС/
        # Единица деривируем из CbNomenclature (в meta прихода их нет).
        purch_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "purchase"))).scalars().all()
        purchases = []
        seen_purch: set[str] = set()   # дедуп ПТУ: двухсменные дни дают дубль DataEntry
        cparty_ref = await self._refs("counterparty")
        shift_day = _day(sm)
        shift_station = str(sm.get("КодАЗС") or "")
        # П1-фикс: линковка документов по ИНТЕРВАЛУ смены [НачалоДня(Открытие)..
        # КонецДня(Закрытие)] как эталон СобратьPurchase — ловит многодневные смены и
        # «сиротские» дни; двухсменный день = 2 пакета по GUID (идемпотентность снимает дубли).
        shift_open = (str(sm.get("Открытие") or "")[:10]) or shift_day
        shift_close = (str(sm.get("Закрытие") or "")[:10]) or shift_day
        if shift_open > shift_close:
            shift_open, shift_close = shift_close, shift_open

        def _in_shift(dsm: dict) -> bool:
            d = _day(dsm)
            return bool(d) and shift_open <= d <= shift_close and str(dsm.get("КодАЗС") or "") == shift_station

        for pe in purch_entries:
            psm = (pe.meta or {}).get("Смена") or {}
            if not _in_shift(psm):
                continue
            pdoc = (pe.meta or {}).get("Документ") or {}
            if pdoc.get("ПометкаУдаления"):   # П3: не эмитим удалённые в ЦБ документы
                continue
            puid = str(pdoc.get("ИсточникUUID") or "")
            if puid in seen_purch:   # дедуп: один ПТУ — один раз в пакете
                continue
            seen_purch.add(puid)
            контр = str(pdoc.get("Контрагент") or "")
            if контр:
                nsi_contr.add(контр)
                if контр in cparty_ref:
                    contr_names[контр] = cparty_ref[контр].name
            ptovары = []
            psum = pnds = 0.0
            for i, ln in enumerate(pdoc.get("Товары") or [], 1):
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                nn = nom.get(g)
                summ = float(ln.get("Сумма") or 0)
                nds = float(ln.get("СуммаНДС") or 0)
                psum += summ
                pnds += nds
                ptovары.append({
                    "НомерСтроки": ln.get("НомерСтроки") or i,
                    "Номенклатура": g,
                    "Количество": float(ln.get("Количество") or 0),
                    "Единица": (nn.unit or "" if nn else ""),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(summ, 2),
                    # П2-фикс: ставка НДС из СТРОКИ документа, карточка — только fallback
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nn.vat if nn else ""),
                    "СуммаНДС": round(nds, 2),
                })
            purchases.append({
                "Тип": "purchase",
                "ИсточникUUID": str(pdoc.get("ИсточникUUID") or ""),
                "Номер": str(pdoc.get("Номер") or "").strip(),
                "Дата": _iso(pdoc.get("Дата")),
                # П3-фикс: Проведен/ПометкаУдаления/Организация из документа ЦБ, не хардкод
                "Проведен": bool(pdoc.get("Проведен", True)),
                "ПометкаУдаления": bool(pdoc.get("ПометкаУдаления", False)),
                "Организация": str(pdoc.get("Организация") or org_uuid),
                "Контрагент": контр,
                "ДоговорКонтрагента": "",   # TODO-Ф1: не тянули договор
                "Склад": wh_uuid,
                "ВидОперации": "ОтПоставщика",   # фильтр пула = только ОтПоставщика
                "СуммаДокумента": round(psum, 2),
                "ВалютаДокумента": "RUB",
                # F8: реальный флаг из ЦБ (default True для старых пакетов до досбора)
                "СуммаВключаетНДС": bool(pdoc.get("СуммаВключаетНДС", True)),
                "НДСНеВыделять": False,
                "НДСВключенВСтоимость": False,
                "НомерВходящегоДокумента": "",   # TODO-Ф1
                "ДатаВходящегоДокумента": "",
                "СуммаНДС": round(pnds, 2),
                "Товары": ptovары,
            })

        # ── production_release (выпуск общепита) ──
        # meta.Документ уже пакет-item; дозаполняем Единица из CbNomenclature.
        prod_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "production_release"))).scalars().all()
        productions = []
        for pr in prod_entries:
            prsm = (pr.meta or {}).get("Смена") or {}
            if not _in_shift(prsm):
                continue
            it = dict((pr.meta or {}).get("Документ") or {})
            it.pop("_station", None)
            it.pop("_day", None)
            it["Дата"] = _iso(it.get("Дата"))
            for блюдо in it.get("ВыпускБлюд") or []:
                g = блюдо.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                блюдо["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
            for ing in it.get("Ингредиенты") or []:
                g = ing.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                ing["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
            productions.append(it)

        # ── gain (оприходование) ──
        gain_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "gain"))).scalars().all()
        gains = []
        for ge in gain_entries:
            gsm = (ge.meta or {}).get("Смена") or {}
            if not _in_shift(gsm):
                continue
            it = dict((ge.meta or {}).get("Документ") or {})
            for k in ("_station", "_day"):
                it.pop(k, None)
            it["Дата"] = _iso(it.get("Дата"))
            for ln in it.get("Товары") or []:
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                ln["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
                ln["СтавкаНДС"] = _nds(ln.pop("СтавкаНДС_raw", "")) or _nds(nom[g].vat if nom.get(g) else "")
            gains.append(it)

        # ── return_purchase (возврат поставщику, F2) ──
        # Эталон СобратьReturnPurchase (bsl:815): на стороне БП → Документ.
        # КорректировкаПоступления с ВидОперации=СогласованноеИзменение. Порядок
        # контракта: после production, перед inventory.
        ret_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "return_purchase"))).scalars().all()
        returns = []
        for re_ in ret_entries:
            rsm = (re_.meta or {}).get("Смена") or {}
            if not _in_shift(rsm):
                continue
            rdoc = (re_.meta or {}).get("Документ") or {}
            if rdoc.get("ПометкаУдаления"):
                continue
            контр = str(rdoc.get("Контрагент") or "")
            if контр:
                nsi_contr.add(контр)
                if контр in cparty_ref:
                    contr_names[контр] = cparty_ref[контр].name
            rtov = []
            rsum = rnds = 0.0
            for i, ln in enumerate(rdoc.get("Товары") or [], 1):
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                nn = nom.get(g)
                summ = float(ln.get("Сумма") or 0)
                nds = float(ln.get("СуммаНДС") or 0)
                rsum += summ
                rnds += nds
                rtov.append({
                    "НомерСтроки": ln.get("НомерСтроки") or i,
                    "Номенклатура": g,
                    "Количество": float(ln.get("Количество") or 0),
                    "Единица": (nn.unit or "" if nn else ""),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(summ, 2),
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nn.vat if nn else ""),
                    "СуммаНДС": round(nds, 2),
                })
            returns.append({
                "Тип": "return_purchase",
                "ИсточникUUID": str(rdoc.get("ИсточникUUID") or ""),
                "Номер": str(rdoc.get("Номер") or "").strip(),
                "Дата": _iso(rdoc.get("Дата")),
                "Проведен": bool(rdoc.get("Проведен", True)),
                "ПометкаУдаления": bool(rdoc.get("ПометкаУдаления", False)),
                "Организация": str(rdoc.get("Организация") or org_uuid),
                "Контрагент": контр,
                "ДоговорКонтрагента": "",
                "ПервичнаяПТУ_UUID": str(rdoc.get("ПервичнаяПТУ_UUID") or ""),
                "Склад": str(rdoc.get("Склад") or wh_uuid),
                "СуммаДокумента": round(rsum, 2) if rsum else float(rdoc.get("СуммаДокумента") or 0),
                "ВалютаДокумента": "RUB",
                "СуммаВключаетНДС": bool(rdoc.get("СуммаВключаетНДС", True)),
                "СуммаНДС": round(rnds, 2),
                "Товары": rtov,
            })

        # ── inventory / writeoff / transfer (движение того же дня) ──
        # строим из Cb*Doc (склады 208); поля пакета деривируем из строк аналитики.
        # интервал смены по дате-части (как эталон): день Открытия..день Закрытия
        _inv_range = func.substr(CbInventoryDoc.doc_date, 1, 10).between(shift_open, shift_close)
        _mov_range = func.substr(CbMovementDoc.doc_date, 1, 10).between(shift_open, shift_close)
        code2guid = {str((r.extra or {}).get("code") or ""): r.external_ref for r in whs.values()}
        inventories = []
        for r in (await self.session.execute(select(CbInventoryDoc).where(
                CbInventoryDoc.company_id == self.company_id,
                _inv_range,
                CbInventoryDoc.warehouse_code.in_(_WH_208)))).scalars().all():
            if r.deleted:   # эталон: «НЕ ПометкаУдаления» в отборе
                continue
            # полная ТЧ Товары (носитель факта): Цена/Сумма/СуммаУчет — из строк ЦБ
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                строки.append({
                    "НомерСтроки": ln.get("n") or i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(float(ln.get("fact") or 0), 3),
                    "КоличествоУчет": round(float(ln.get("uchet") or 0), 3),
                    "Цена": round(float(ln.get("price") or 0), 2),
                    "Сумма": round(float(ln.get("amount") or 0), 2),
                    "СуммаУчет": round(float(ln.get("amount_uchet") or 0), 2),
                })
            inventories.append({
                "Тип": "inventory", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                # BP-4: Склад из САМОГО документа (напр. помещение 20800002), не смены —
                # иначе движения кухни/склада приписывались торговому залу 208.
                "Организация": org_uuid, "Склад": code2guid.get(str(r.warehouse_code or ""), wh_uuid),
                "Комментарий": r.comment or "",
                "ДатаЗаполнения": _iso(r.fill_date) if r.fill_date else "", "Товары": строки,
                "СуммаДокумента": round(sum(s["Сумма"] for s in строки), 2),
            })

        writeoffs = []
        transfers = []
        # transfer: отбор эталона — «СкладОтправитель=смены ИЛИ СкладПолучатель=смены»
        # (входящие на 208 тоже эмитятся); writeoff (warehouse_to_code NULL) не задет.
        for r in (await self.session.execute(select(CbMovementDoc).where(
                CbMovementDoc.company_id == self.company_id,
                _mov_range,
                or_(CbMovementDoc.warehouse_code.in_(_WH_208),
                    CbMovementDoc.warehouse_to_code.in_(_WH_208))))).scalars().all():
            if r.deleted:   # эталон: «НЕ ПометкаУдаления» в отборе
                continue
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                строки.append({
                    "НомерСтроки": ln.get("n") or i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(float(ln.get("qty") or 0), 3),
                    "Цена": round(float(ln.get("price") or 0), 2),
                    "_amount": round(float(ln.get("amount") or 0), 2),
                    "_cost": round(float(ln.get("cost") or 0), 2),
                })
            if r.kind == "writeoff":
                for s in строки:
                    s["Сумма"] = s.pop("_amount")
                    s.pop("_cost")
                writeoffs.append({
                    "Тип": "writeoff", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                    # BP-4: Склад документа (не смены) — списание с реального склада.
                    "Организация": org_uuid, "Склад": code2guid.get(str(r.warehouse_code or ""), wh_uuid),
                    "Подразделение": "",
                    "ИнвентаризацияUUID": r.inventory_ref or "",
                    "СуммаДокумента": round(float(r.total_amount or 0), 2),
                    "НДСвСтоимостиТоваров": "", "ВалютаДокумента": "RUB", "Товары": строки,
                })
            elif r.kind == "transfer":
                for s in строки:
                    s["Себестоимость"] = s.pop("_cost")   # реквизит ТЧ ЦБ (0 у внутренних)
                    s.pop("_amount")
                # Направление относительно складов смены (эталон: отправитель приоритетен)
                si = str(r.warehouse_code or "") in _WH_208
                di = str(r.warehouse_to_code or "") in _WH_208
                # фолбэк wh_uuid — только для складов смены; чужой склад без GUID → ""
                отпр = code2guid.get(str(r.warehouse_code or ""), wh_uuid if si else "")
                получ = code2guid.get(str(r.warehouse_to_code or ""), wh_uuid if di else "")
                if получ:
                    nsi_wh.add(получ)
                if отпр:
                    nsi_wh.add(отпр)
                направление = "Исходящее" if si else ("Входящее" if di else "Транзит")
                transfers.append({
                    "Тип": "transfer", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                    "Организация": org_uuid,
                    "СкладОтправитель": отпр, "СкладПолучатель": получ,
                    "Подразделение": "", "ВидОперации": "ТоварыПродукция",
                    "Направление": направление, "Товары": строки,
                    "СуммаДокумента": round(float(r.total_amount or 0), 2),
                })

        # ── recipe (ТТК блюд, модель B общепита) ──
        # Для блюд смены (общепит-строки retail) эмитим ТТК ПЕРВЫМИ: приёмник строит
        # Справочник.СпецификацияНоменклатуры, из неё генерит Комплектацию (собирает
        # себестоимость), затем блюдо продаётся товаром в ОРП. Без recipe — «продано
        # как товар, себестоимость не собрана».
        recipes = []
        if dish_uuids:
            recipe_entries = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
                DataEntry.doc_type_id == "recipe"))).scalars().all()
            recipe_by_dish: dict[str, dict] = {}
            for re_ in recipe_entries:
                rd = (re_.meta or {}).get("Документ") or {}
                bu = str(rd.get("БлюдоUUID") or "")
                if bu:
                    recipe_by_dish[bu] = rd
            for du in sorted(dish_uuids):
                rd = recipe_by_dish.get(du)
                # OB-1: нет recipe-DataEntry → фолбэк на inline-ТТК строки продажи.
                src_ings = (rd.get("Ингредиенты") if rd else None) or dish_inline_ings.get(du) or []
                ингредиенты = []
                for ing in src_ings:
                    iu = str(ing.get("НоменклатураUUID") or "")
                    if not iu:
                        continue
                    nsi_nom.add(iu)  # ингредиент → в НСИ
                    ингредиенты.append({
                        "НоменклатураUUID": iu,
                        "Количество": float(ing.get("Количество") or 0),
                        "Единица": (nom[iu].unit if nom.get(iu) else "") or "",
                    })
                if not ингредиенты:
                    continue
                nsi_nom.add(du)  # блюдо → в НСИ
                recipes.append({
                    "Тип": "recipe",
                    "ИсточникUUID": str(rd.get("ИсточникUUID") or "") if rd else f"inline:{du}",
                    "БлюдоUUID": du,
                    "БлюдоНаименование": str((rd.get("БлюдоНаименование") if rd else None)
                                             or (nom[du].name if nom.get(du) else "")),
                    "Ингредиенты": ингредиенты,
                })

        # Порядок контракта: recipe → purchase → retail → production → return → inventory → gain → writeoff → transfer
        документы = [*recipes, *purchases, retail, *productions, *returns, *inventories, *gains, *writeoffs, *transfers]

        # ── НСИ ──
        def _s(v) -> str:
            return str(v or "").strip()   # ЦБ хранит ИНН/Код fixed-width → обрезать

        нси = []
        for uid in sorted(nsi_org):
            r = orgs.get(uid)
            ex = (r.extra or {}) if r else {}
            нси.append({
                "Тип": "Организация", "ИсточникUUID": uid,
                "Наименование": _s(r.name if r else ""), "НаименованиеПолное": _s(ex.get("full_name")) or _s(r.name if r else ""),
                "ИНН": _s(ex.get("inn")), "КПП": _s(ex.get("kpp")), "ОГРН": _s(ex.get("ogrn")),
                "ОКПО": _s(ex.get("okpo")), "ЮрФизЛицо": _s(ex.get("jur_fiz")) or "ЮрЛицо",
                "ПометкаУдаления": bool(ex.get("deleted")),
            })
        for uid in sorted(nsi_wh):
            r = whs.get(uid)
            ex = (r.extra or {}) if r else {}
            нси.append({
                "Тип": "Склад", "ИсточникUUID": uid,
                "Наименование": _s(r.name if r else ""), "Код": _s(ex.get("code")),
                "ВидСклада": _s(ex.get("kind_name")) or "АЗК",
                "ПометкаУдаления": bool(ex.get("deleted")),
            })
        for uid in sorted(nsi_contr):
            # Контрагент автосоздаётся приёмником по Наименованию (ИНН/КПП опц.).
            # TODO-Ф1: ИНН/КПП/ВидКонтрагента из Catalog.Контрагенты.
            nm = _s(contr_names.get(uid, ""))
            нси.append({
                "Тип": "Контрагент", "ИсточникUUID": uid,
                "Наименование": nm, "НаименованиеПолное": nm,
                "ИНН": "", "КПП": "", "ВидКонтрагента": "ЮрЛицо",
                "ПометкаУдаления": False,
            })
        for g in sorted(nsi_nom):
            nn = nom.get(g)
            вид = _s(kinds[nn.kind_ref].name) if (nn and nn.kind_ref and nn.kind_ref in kinds) else ""
            класс = "Общепит" if вид == "Набор - комплект" else "Сопутка"
            нси.append({
                "Тип": "Номенклатура", "ИсточникUUID": g,
                "КодЦБ": _s(nn.code if nn else ""),
                "Наименование": _s(nn.name if nn else ""),
                "НаименованиеПолное": _s(nn.full_name if nn else "") or _s(nn.name if nn else ""),
                "Артикул": _s(nn.article if nn else ""),
                "СтавкаНДС": _nds(nn.vat if nn else ""),
                "Единица": _s(nn.unit if nn else ""),
                "ВидНоменклатуры": вид,
                "КлассSKU": класс,
                "ШтрихКоды": [],
                "ПометкаУдаления": False,
            })

        пакет = {
            "ВерсияФормата": "2",
            "ВремяВыгрузки": _iso(datetime.now().astimezone().isoformat(timespec="seconds")),
            "ИдентификаторПакета": _new_packet_uuid(),
            "Источник": "TradeLedger (Ledger)",
            "Смена": shift,
            "Документы": документы,
            "НСИ": нси,
            "ХешПакета": "",
        }
        пакет["ХешПакета"] = packet_hash(пакет)
        return пакет

    async def emit_to_dir(self, shift_key: str, directory: str) -> dict:
        """Собрать пакет и записать JSON-файл в каталог (Ф3). Формат: UTF-8 без
        BOM, отступ таб (как ЗаписатьJSON приёмника). Возвращает сводку."""
        пакет = await self.build_shift_package(shift_key)
        fname = package_filename(пакет)
        _os.makedirs(directory, exist_ok=True)
        path = _os.path.join(directory, fname)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            _json.dump(пакет, f, ensure_ascii=False, indent="\t")
        from collections import Counter
        return {
            "file": fname, "path": path, "hash": пакет["ХешПакета"],
            "documents": dict(Counter(d["Тип"] for d in пакет["Документы"])),
            "nsi": len(пакет["НСИ"]),
        }

    async def verify_shift_package(self, shift_key: str) -> dict:
        """Сверка сопутки: самосогласованность пакета + сверка с источником. Строит
        пакет и прогоняет проверки готовности к загрузке приёмником (без 1С-эталона):
        балансы документов, полнота НСИ, fail-fast НДС, хеш. Возвращает список проверок."""
        pkt = await self.build_shift_package(shift_key)
        docs = pkt["Документы"]
        нси = pkt["НСИ"]
        checks: list[dict] = []

        def add(name: str, ok: bool, detail: str = "") -> None:
            checks.append({"Проверка": name, "ok": bool(ok), "Детали": detail})

        nsi_by_type: dict[str, set] = {}
        for n in нси:
            nsi_by_type.setdefault(n.get("Тип"), set()).add(n.get("ИсточникUUID"))
        nom_set = nsi_by_type.get("Номенклатура", set())

        h = pkt.get("ХешПакета") or ""
        add("Хеш пакета — 64 hex", len(h) == 64 and all(c in "0123456789abcdef" for c in h), (h[:12] + "…") if h else "нет")
        add("Версия формата = 2", pkt.get("ВерсияФормата") == "2", str(pkt.get("ВерсияФормата")))
        add("НСИ-инвариант: документы>0 → НСИ непуста", not (docs and not нси), f"документов={len(docs)} НСИ={len(нси)}")

        ref_nom: set = set(); ref_org: set = set(); ref_wh: set = set()
        for d in docs:
            for t in (d.get("Товары") or []):
                if t.get("Номенклатура"):
                    ref_nom.add(t["Номенклатура"])
            for ing in (d.get("Ингредиенты") or []):
                if ing.get("НоменклатураUUID"):
                    ref_nom.add(ing["НоменклатураUUID"])
            if d.get("БлюдоUUID"):
                ref_nom.add(d["БлюдоUUID"])
            for k in ("Организация",):
                if d.get(k):
                    ref_org.add(d[k])
            for k in ("Склад", "СкладОтправитель", "СкладПолучатель"):
                if d.get(k):
                    ref_wh.add(d[k])
        add("Номенклатура документов вся в НСИ", not (ref_nom - nom_set), f"нет в НСИ: {len(ref_nom - nom_set)}")
        add("Организации документов в НСИ", not (ref_org - nsi_by_type.get("Организация", set())), f"нет: {len(ref_org - nsi_by_type.get('Организация', set()))}")
        add("Склады документов в НСИ", not (ref_wh - nsi_by_type.get("Склад", set())), f"нет: {len(ref_wh - nsi_by_type.get('Склад', set()))}")

        retail = next((d for d in docs if d.get("Тип") == "retail_sale_sidegoods"), None)
        if retail:
            товары = retail.get("Товары") or []
            s_d = float(retail.get("СуммаДокумента") or 0)
            s_t = round(sum(float(t.get("Сумма") or 0) for t in товары), 2)
            add("Розница: Σ строк = СуммаДокумента", abs(s_t - s_d) < 0.02, f"{s_t} ↔ {s_d}")
            s_nds = round(sum(float(t.get("СуммаНДС") or 0) for t in товары), 2)
            add("Розница: Σ СуммаНДС строк = СуммаНДС", abs(s_nds - float(retail.get("СуммаНДС") or 0)) < 0.02, f"{s_nds} ↔ {retail.get('СуммаНДС')}")
            s_p = round(sum(float(o.get("Сумма") or 0) for o in (retail.get("Оплаты") or [])), 2)
            add("Розница: Σ Оплаты = СуммаДокумента", abs(s_p - s_d) < 0.02, f"{s_p} ↔ {s_d}")
            add("Розница: все ставки НДС распознаны", not [t for t in товары if not t.get("СтавкаНДС")], f"пустых: {len([t for t in товары if not t.get('СтавкаНДС')])}")

        purch = [d for d in docs if d.get("Тип") == "purchase"]
        if purch:
            bad = [p.get("Номер") for p in purch
                   if abs(round(sum(float(t.get("Сумма") or 0) for t in (p.get("Товары") or [])), 2) - float(p.get("СуммаДокумента") or 0)) >= 0.02]
            add(f"Поступления ({len(purch)}): Σ строк = СуммаДокумента", not bad, f"расхождения: {bad}")

        recs = [d for d in docs if d.get("Тип") == "recipe"]
        if recs:
            no_ing = [r.get("БлюдоНаименование") for r in recs if not r.get("Ингредиенты")]
            add(f"Рецептуры ({len(recs)}): все с ингредиентами", not no_ing, f"без ингредиентов: {no_ing}")

        # OB-1: КАЖДОЕ блюдо смены (ЭтоБлюдо) должно иметь recipe в пакете — иначе
        # приёмник спишет его товаром с 41.02 в минус. Раньше verify это не ловил.
        dishes_sold = {t.get("Номенклатура") for d in docs
                       if d.get("Тип") == "retail_sale_sidegoods"
                       for t in (d.get("Товары") or []) if t.get("ЭтоБлюдо") and t.get("Номенклатура")}
        recipe_dishes = {r.get("БлюдоUUID") for r in recs}
        missing = dishes_sold - recipe_dishes
        add(f"Все блюда смены ({len(dishes_sold)}) имеют ТТК в пакете",
            not missing, f"без рецепта: {len(missing)}" + (f" {list(missing)[:3]}" if missing else ""))

        empty_vat = [n.get("Наименование") for n in нси if n.get("Тип") == "Номенклатура" and not n.get("СтавкаНДС")]
        add("НСИ: ставки НДС номенклатуры распознаны", not empty_vat, f"пустых: {len(empty_vat)}")

        # Поступление и возврат поставщику приёмник роняет исключением на несопоставленной
        # ставке (в розничных ветках она перекрывается форсом НДС22, поэтому там не важна).
        # Ловим до выгрузки: иначе документ молча не доедет до бухгалтерии.
        unmapped = [f"{d.get('Тип')} №{d.get('Номер')}: {t.get('СтавкаНДС') or 'пусто'}"
                    for d in docs if d.get("Тип") in ("purchase", "return_purchase")
                    for t in (d.get("Товары") or []) if t.get("СтавкаНДС") not in _BP_VAT_NAMES]
        add("Поступления и возвраты: ставки НДС приёмник сопоставит",
            not unmapped, f"строк: {len(unmapped)} {unmapped[:5]}")

        # Приёмник (первая ветка, НЕ правим) принимает НДС18 МОЛЧА: purchase — в документ
        # с ндс=0, retail — форс НДС22. Архаичную ставку ловим у себя ДО выгрузки.
        _archaic = {"НДС18", "НДС18_118"}
        bad_vat = []
        for d in docs:
            for t in (d.get("Товары") or []):
                if t.get("СтавкаНДС") in _archaic:
                    bad_vat.append(f"{d.get('Тип')} №{d.get('Номер')}: {t.get('СтавкаНДС')}")
        bad_vat += [f"НСИ {n.get('Наименование')}: {n.get('СтавкаНДС')}"
                    for n in нси if n.get("СтавкаНДС") in _archaic]
        add("Нет архаичных ставок НДС18 (приёмник ест молча)", not bad_vat, f"строк: {bad_vat[:5]}")

        sm = pkt.get("Смена") or {}
        return {
            "shift_key": shift_key,
            "ok": all(c["ok"] for c in checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "total": len(checks),
            "Документов": len(docs),
            "НСИ": len(нси),
            "ХешПакета": h,
            "КодАЗС": sm.get("КодАЗС"),
            "checks": checks,
        }
