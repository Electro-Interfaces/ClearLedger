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

import uuid as _uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, CbNomenclature, StockOnHand
from app.services.bp_canon import packet_hash
from app.services.goods_dashboard import _day

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


# Реквизиты известных организаций ЦБ (Организация не автосоздаётся, ищется по ИНН).
# TODO-Ф1: заменить пулом Catalog.Организации из ЦБ.
ORG_REQ = {
    # gig ГАЗИНВЕСТГРУПП
    "8cfc4701-63e6-11f1-bdff-0050568cc25a": {
        "Наименование": 'ООО "ГАЗИНВЕСТГРУПП"', "НаименованиеПолное": 'ООО "ГАЗИНВЕСТГРУПП"',
        "ИНН": "7839440090", "КПП": "780401001", "ОГРН": "", "ОКПО": "", "ЮрФизЛицо": "ЮрЛицо",
    },
}


class BpPackageEmitter:
    def __init__(self, session: AsyncSession, company_id):
        self.session = session
        self.company_id = company_id

    async def _nom_map(self) -> dict[str, CbNomenclature]:
        rows = (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()
        return {n.external_ref: n for n in rows}

    async def _wh_map(self) -> dict[str, dict]:
        """warehouse_code / GUID → {name, code}. Смена.Склад — GUID, а StockOnHand
        хранит код → имя. Склад в НСИ идёт по UUID из Смена/документов, имя/код — из склада."""
        out: dict[str, dict] = {}
        for s in (await self.session.execute(select(StockOnHand).where(
                StockOnHand.company_id == self.company_id))).scalars().all():
            out.setdefault(s.warehouse_code, {"Наименование": s.warehouse_name or s.warehouse_code,
                                              "Код": s.warehouse_code})
        return out

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

        # кэш UUID для НСИ
        nsi_nom: set[str] = set()
        nsi_org: set[str] = set()
        nsi_wh: set[str] = set()

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

        документы = [retail]  # TODO-Ф1: recipe/purchase/production_release/… перед/после

        # ── НСИ ──
        нси = []
        wh_info = await self._wh_map()
        for uid in sorted(nsi_org):
            req = ORG_REQ.get(uid, {})
            нси.append({
                "Тип": "Организация", "ИсточникUUID": uid,
                "Наименование": req.get("Наименование", ""), "НаименованиеПолное": req.get("НаименованиеПолное", ""),
                "ИНН": req.get("ИНН", ""), "КПП": req.get("КПП", ""), "ОГРН": req.get("ОГРН", ""),
                "ОКПО": req.get("ОКПО", ""), "ЮрФизЛицо": req.get("ЮрФизЛицо", "ЮрЛицо"),
                "ПометкаУдаления": False,
            })
        for uid in sorted(nsi_wh):
            info = wh_info.get(str(код), {"Наименование": "", "Код": str(код)})
            нси.append({
                "Тип": "Склад", "ИсточникUUID": uid,
                "Наименование": info["Наименование"], "Код": info["Код"],
                "ВидСклада": "АЗК",  # TODO-Ф1: тянуть из ЦБ
                "ПометкаУдаления": False,
            })
        for g in sorted(nsi_nom):
            nn = nom.get(g)
            вид = ""  # kind_ref→name; TODO: резолв через CbRef
            класс = "Сопутка"
            нси.append({
                "Тип": "Номенклатура", "ИсточникUUID": g,
                "КодЦБ": "",  # TODO-Ф1: не тянули Код номенклатуры
                "Наименование": (nn.name if nn else ""),
                "НаименованиеПолное": (nn.full_name or nn.name if nn else ""),
                "Артикул": (nn.article or "" if nn else ""),
                "СтавкаНДС": _nds(nn.vat if nn else ""),
                "Единица": (nn.unit or "" if nn else ""),
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
