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

from sqlalchemy import select
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


def _nds(v: str | None) -> str:
    """Канон-имя ставки. Неизвестное → "" (сигнал fail-fast приёмника — ловим рано)."""
    return _NDS_MAP.get((v or "").strip().lower(), _NDS_MAP.get((v or "").strip(), ""))


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
                товары.append(строка)

        оплаты = []
        for o in (sec.get("оплаты") or {}).get("строки") or []:
            вид = str(o.get("ФормаОплаты") or o.get("ФормаОплатыКанон") or "").strip()
            if "нал" in вид.lower():
                вид = "Наличные"
            оплаты.append({"ВидОплаты": вид, "Сумма": round(float(o.get("Сумма") or 0), 2)})

        retail = {
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": str(doc_meta.get("ИсточникUUID") or sm.get("Смена") or ""),
            "Номер": str(sm.get("НомерСмены") or "").strip(),
            "Дата": _iso(sm.get("Закрытие")),
            "Проведен": True,
            "ПометкаУдаления": False,
            "Организация": org_uuid,
            "Склад": wh_uuid,
            "Подразделение": "",
            "СуммаДокумента": round(сумма_док, 2),
            "ВалютаДокумента": "RUB",
            "СуммаВключаетНДС": True,
            "Товары": товары,
            "ВозвращенныеТовары": [],
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
        cparty_ref = await self._refs("counterparty")
        shift_day = _day(sm)
        shift_station = str(sm.get("КодАЗС") or "")
        for pe in purch_entries:
            psm = (pe.meta or {}).get("Смена") or {}
            # приход не несёт GUID смены → линк по (дата открытия, станция)
            if _day(psm) != shift_day or str(psm.get("КодАЗС") or "") != shift_station:
                continue
            pdoc = (pe.meta or {}).get("Документ") or {}
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
                    "СтавкаНДС": _nds(nn.vat if nn else ""),   # дерив. из карточки
                    "СуммаНДС": round(nds, 2),
                })
            purchases.append({
                "Тип": "purchase",
                "ИсточникUUID": str(pdoc.get("ИсточникUUID") or ""),
                "Номер": str(pdoc.get("Номер") or "").strip(),
                "Дата": _iso(pdoc.get("Дата")),
                "Проведен": True,
                "ПометкаУдаления": False,
                "Организация": org_uuid,
                "Контрагент": контр,
                "ДоговорКонтрагента": "",   # TODO-Ф1: не тянули договор
                "Склад": wh_uuid,
                "ВидОперации": "ОтПоставщика",   # фильтр пула = только ОтПоставщика
                "СуммаДокумента": round(psum, 2),
                "ВалютаДокумента": "RUB",
                "СуммаВключаетНДС": True,
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
            if _day(prsm) != shift_day or str(prsm.get("КодАЗС") or "") != shift_station:
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
            if _day(gsm) != shift_day or str(gsm.get("КодАЗС") or "") != shift_station:
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

        # ── inventory / writeoff / transfer (движение того же дня) ──
        # строим из Cb*Doc (склады 208); поля пакета деривируем из строк аналитики.
        dl = shift_day + "%"
        code2guid = {str((r.extra or {}).get("code") or ""): r.external_ref for r in whs.values()}
        inventories = []
        for r in (await self.session.execute(select(CbInventoryDoc).where(
                CbInventoryDoc.company_id == self.company_id,
                CbInventoryDoc.doc_date.like(dl),
                CbInventoryDoc.warehouse_code.in_(_WH_208)))).scalars().all():
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                fact = float(ln.get("fact") or 0)
                uchet = float(ln.get("uchet") or 0)
                dev = float(ln.get("dev") or 0)
                amt_dev = float(ln.get("amount_dev") or 0)
                цена = round(amt_dev / dev, 4) if dev else 0.0   # Цена = стоим.откл / кол-во откл
                строки.append({
                    "НомерСтроки": i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(fact, 3), "КоличествоУчет": round(uchet, 3),
                    "Цена": цена, "Сумма": round(fact * цена, 2), "СуммаУчет": round(uchet * цена, 2),
                })
            inventories.append({
                "Тип": "inventory", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                "Дата": _iso(r.doc_date), "Проведен": True, "ПометкаУдаления": False,
                "Организация": org_uuid, "Склад": wh_uuid, "Комментарий": r.comment or "",
                "ДатаЗаполнения": "", "Товары": строки,
                "СуммаДокумента": round(sum(s["Сумма"] for s in строки), 2),
            })

        writeoffs = []
        transfers = []
        for r in (await self.session.execute(select(CbMovementDoc).where(
                CbMovementDoc.company_id == self.company_id,
                CbMovementDoc.doc_date.like(dl),
                CbMovementDoc.warehouse_code.in_(_WH_208)))).scalars().all():
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                строки.append({
                    "НомерСтроки": i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(float(ln.get("qty") or 0), 3),
                    "Цена": round(float(ln.get("price") or 0), 2),
                    "_amount": round(float(ln.get("amount") or 0), 2),
                })
            if r.kind == "writeoff":
                for s in строки:
                    s["Сумма"] = s.pop("_amount")
                writeoffs.append({
                    "Тип": "writeoff", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": True, "ПометкаУдаления": False,
                    "Организация": org_uuid, "Склад": wh_uuid, "Подразделение": "",
                    "ИнвентаризацияUUID": "", "СуммаДокумента": round(float(r.total_amount or 0), 2),
                    "НДСвСтоимостиТоваров": "", "ВалютаДокумента": "RUB", "Товары": строки,
                })
            elif r.kind == "transfer":
                for s in строки:
                    s["Себестоимость"] = s.pop("_amount")   # TODO: реальная себест. (сейчас = стоимость строки)
                отпр = code2guid.get(str(r.warehouse_code or ""), wh_uuid)
                получ = code2guid.get(str(r.warehouse_to_code or ""), "")
                if получ:
                    nsi_wh.add(получ)
                if отпр:
                    nsi_wh.add(отпр)
                transfers.append({
                    "Тип": "transfer", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": True, "ПометкаУдаления": False,
                    "Организация": org_uuid,
                    "СкладОтправитель": отпр, "СкладПолучатель": получ,
                    "Подразделение": "", "ВидОперации": "ТоварыПродукция",
                    "Направление": "Исходящее", "Товары": строки,
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
                if not rd:
                    continue
                ингредиенты = []
                for ing in rd.get("Ингредиенты") or []:
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
                    "ИсточникUUID": str(rd.get("ИсточникUUID") or ""),
                    "БлюдоUUID": du,
                    "БлюдоНаименование": str(rd.get("БлюдоНаименование") or ""),
                    "Ингредиенты": ингредиенты,
                })

        # Порядок контракта: recipe → purchase → retail → production → [return] → inventory → gain → writeoff → transfer
        документы = [*recipes, *purchases, retail, *productions, *inventories, *gains, *writeoffs, *transfers]

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
