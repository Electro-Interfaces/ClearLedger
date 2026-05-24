"""
Автосопряжение маппингов (ReconcileMapping) — анализирует данные локальной
БД (Counterparty, NomenclatureItem, Warehouse, FuelStation, FuelReceipt,
AccountingDoc.lines) и предлагает соответствия source_key → target_ref.

Виды маппингов:
  - counterparty — наши контрагенты ↔ Catalog.Контрагенты по ИНН+КПП
  - fuel         — подстроки АИ-92/95/98/ДТ ↔ Catalog.Номенклатура (топливо)
  - station      — FuelStation.code ↔ Catalog.Склады по имени
  - paytype      — наличные/карты/талоны ↔ стандартные счета
  - nomenclature — артикул поставщика ↔ Catalog.Номенклатура

Возвращает Suggestion — НЕ записывает сразу. UI показывает с возможностью
accept/reject. По нажатию «Применить всё с confidence ≥ X» — массовый insert.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Counterparty,
    FuelReceipt,
    FuelStation,
    NomenclatureItem,
    ReconcileMapping,
    Warehouse,
)


# Подстроки для классификации топлива
FUEL_PATTERNS = {
    "АИ-92": ["АИ-92", "А-92", "АИ92", "АИ 92"],
    "АИ-95": ["АИ-95", "А-95", "АИ95", "АИ 95"],
    "АИ-98": ["АИ-98", "А-98", "АИ98", "АИ 98"],
    "АИ-100": ["АИ-100", "А-100", "АИ100", "АИ 100"],
    "ДТ": ["ДТ", "Дизель", "Дизельное"],
    "СУГ": ["СУГ", "ПБ", "ПРОПАН", "СПБТ", "Газ моторн"],
}

# Стандартный мап «наш» вид оплаты → счёт БП 3.0
PAYTYPE_TO_ACCOUNT = {
    "cash":     ("50.01", "Касса организации"),
    "card":     ("57.03", "Эквайринг"),
    "voucher":  ("62.Р",  "Расчёты с покупателями (розница)"),
    "yandex":   ("57.03", "Эквайринг (Яндекс)"),
    "talon":    ("62.Р",  "Талоны (розница)"),
    "vedom":    ("62.Р",  "Ведомость (розница)"),
}


@dataclass
class MappingSuggestion:
    kind: str               # counterparty | fuel | station | paytype | nomenclature
    source_key: str
    source_label: str       # человекочитаемое название источника
    target_ref: str
    target_name: str
    confidence: int         # 0..100
    method: str             # 'inn_kpp' | 'fuel_pattern' | 'name_match' | 'sts_code' | 'default'
    note: str | None = None


class MappingAutoDetectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def detect_all(self, company_id: uuid.UUID) -> list[MappingSuggestion]:
        """Запускает все 5 детекторов и возвращает объединённый список предложений."""
        suggestions: list[MappingSuggestion] = []
        # Существующие маппинги — чтобы не предлагать то что уже есть
        existing_keys: set[tuple[str, str]] = set()
        for m in (await self.session.execute(
            select(ReconcileMapping.kind, ReconcileMapping.source_key).where(
                ReconcileMapping.company_id == company_id,
            )
        )).all():
            existing_keys.add((m.kind, m.source_key))

        suggestions += await self._detect_counterparties(company_id, existing_keys)
        suggestions += await self._detect_fuel(company_id, existing_keys)
        suggestions += await self._detect_stations(company_id, existing_keys)
        suggestions += await self._detect_paytypes(existing_keys)
        suggestions += await self._detect_nomenclature_from_receipts(company_id, existing_keys)
        return suggestions

    # ─── 1. counterparty по ИНН+КПП ────────────────────────────────────

    async def _detect_counterparties(
        self, company_id: uuid.UUID, existing: set[tuple[str, str]]
    ) -> list[MappingSuggestion]:
        """В нашей БД могут быть контрагенты введённые вручную (от ТТН) с ИНН/КПП.
        Они должны мэтчиться с Catalog.Контрагенты БП ГИГ по ИНН+КПП.

        Здесь: все Counterparty где есть external_ref — это и есть «факт» уже
        связанный, но в ReconcileMapping этих связей может не быть.
        Создаём предложение source_key=ИНН → target_ref=external_ref.
        """
        result = await self.session.execute(
            select(Counterparty).where(
                Counterparty.company_id == company_id,
                Counterparty.inn.is_not(None),
            )
        )
        out: list[MappingSuggestion] = []
        seen_inn: set[str] = set()
        for cp in result.scalars().all():
            inn = (cp.inn or "").strip()
            if not inn or inn in seen_inn:
                continue
            seen_inn.add(inn)
            key = inn
            if ("counterparty", key) in existing:
                continue
            if not cp.external_ref:
                continue
            out.append(MappingSuggestion(
                kind="counterparty",
                source_key=key,
                source_label=f"{cp.name} (ИНН {inn})",
                target_ref=cp.external_ref,
                target_name=cp.name,
                confidence=100,
                method="inn_kpp",
                note="Найден контрагент с external_ref в локальной БД",
            ))
        return out

    # ─── 2. fuel по подстрокам в имени Catalog.Номенклатура ────────────

    async def _detect_fuel(
        self, company_id: uuid.UUID, existing: set[tuple[str, str]]
    ) -> list[MappingSuggestion]:
        """Ищем в Catalog.Номенклатура (NomenclatureItem) товары которые
        соответствуют топливным группам по подстрокам имени.
        Для каждой группы выбираем ОДИН лучший кандидат (как правило (т) —
        тонны, потому что ТТН в тоннах)."""
        nom_rows = (await self.session.execute(
            select(NomenclatureItem).where(
                NomenclatureItem.company_id == company_id,
                NomenclatureItem.external_ref.is_not(None),
            )
        )).scalars().all()

        out: list[MappingSuggestion] = []
        for fuel_code, patterns in FUEL_PATTERNS.items():
            if ("fuel", fuel_code) in existing:
                continue
            # Ищем кандидатов: имя содержит одну из подстрок
            candidates = []
            for nom in nom_rows:
                name_upper = (nom.name or "").upper()
                for p in patterns:
                    if p.upper() in name_upper:
                        # Предпочитаем (т) — тонны для топлива
                        is_tons = "(Т)" in name_upper or "(ТОНН" in name_upper
                        candidates.append((nom, is_tons))
                        break
            if not candidates:
                continue
            # Сначала тонны, потом литры, потом без указания
            candidates.sort(key=lambda x: (not x[1], len(x[0].name or "")))
            best, _ = candidates[0]
            out.append(MappingSuggestion(
                kind="fuel",
                source_key=fuel_code,
                source_label=f"Топливо {fuel_code}",
                target_ref=best.external_ref,
                target_name=best.name,
                confidence=95 if "(Т)" in (best.name or "").upper() else 80,
                method="fuel_pattern",
                note=f"Найдено {len(candidates)} кандидатов, выбран по приоритету (т)→(л)→прочее",
            ))
        return out

    # ─── 3. station по коду STS → Catalog.Склады ───────────────────────

    async def _detect_stations(
        self, company_id: uuid.UUID, existing: set[tuple[str, str]]
    ) -> list[MappingSuggestion]:
        """FuelStation.code (STS system) — наш source_key. Catalog.Склады
        в БП ГИГ обычно называется типа «АЗС №208», «АКЗС №5», «АЗС Выборг (208)».
        Матчим по числовому коду в имени склада."""
        stations = (await self.session.execute(
            select(FuelStation).where(FuelStation.company_id == company_id)
        )).scalars().all()
        warehouses = (await self.session.execute(
            select(Warehouse).where(
                Warehouse.company_id == company_id,
                Warehouse.external_ref.is_not(None),
            )
        )).scalars().all()
        out: list[MappingSuggestion] = []
        for st in stations:
            key = str(st.code)
            if ("station", key) in existing:
                continue
            # Ищем склад имя которого содержит код станции
            best = None
            best_score = 0
            for wh in warehouses:
                wh_name = (wh.name or "")
                # Совпадение по числу: «АЗС 208», «(208)», «№208»
                if re.search(rf"\b{re.escape(key)}\b", wh_name) or f"({key})" in wh_name:
                    # Бонус если есть имя станции
                    score = 90
                    if st.name and st.name.lower() in wh_name.lower():
                        score = 100
                    if score > best_score:
                        best = wh
                        best_score = score
            if best:
                out.append(MappingSuggestion(
                    kind="station",
                    source_key=key,
                    source_label=f"АЗС {st.name or '?'} (код {key})",
                    target_ref=best.external_ref,
                    target_name=best.name,
                    confidence=best_score,
                    method="sts_code",
                    note=f"Найдено по коду {key} в имени склада",
                ))
        return out

    # ─── 4. paytype дефолтный маппинг на счета БП ──────────────────────

    async def _detect_paytypes(
        self, existing: set[tuple[str, str]]
    ) -> list[MappingSuggestion]:
        """Маппинг видов оплат на типовые счета БП 3.0.
        Это не «найденные» а «дефолтные» предложения."""
        out: list[MappingSuggestion] = []
        for pt_code, (account, name) in PAYTYPE_TO_ACCOUNT.items():
            if ("paytype", pt_code) in existing:
                continue
            out.append(MappingSuggestion(
                kind="paytype",
                source_key=pt_code,
                source_label={
                    "cash": "Наличные", "card": "Карты", "voucher": "Талоны/ведомости",
                    "yandex": "Яндекс.Заправки", "talon": "Талоны топливные", "vedom": "Ведомости",
                }.get(pt_code, pt_code),
                target_ref=account,
                target_name=name,
                confidence=90,
                method="default",
                note="Стандартный счёт БП 3.0 для этого вида оплаты",
            ))
        return out

    # ─── 5. nomenclature из ТТН по артикулу/имени поставщика ──────────

    async def _detect_nomenclature_from_receipts(
        self, company_id: uuid.UUID, existing: set[tuple[str, str]]
    ) -> list[MappingSuggestion]:
        """Из FuelReceipt берём fuel_name (как ввёл поставщик в ТТН) и пробуем
        найти соответствующую Catalog.Номенклатура по совпадению подстроки.

        Это grows маппинг по реальным ТТН — конкретные имена поставщиков, не
        универсальные топливные коды.
        """
        receipts = (await self.session.execute(
            select(FuelReceipt).where(FuelReceipt.company_id == company_id)
        )).scalars().all()
        nom_rows = (await self.session.execute(
            select(NomenclatureItem).where(
                NomenclatureItem.company_id == company_id,
                NomenclatureItem.external_ref.is_not(None),
            )
        )).scalars().all()
        # Группируем ТТН по fuel_name
        unique_fuel_names: dict[str, int] = {}
        for r in receipts:
            nm = (r.fuel_name or "").strip()
            if nm:
                unique_fuel_names[nm] = unique_fuel_names.get(nm, 0) + 1
        out: list[MappingSuggestion] = []
        for fuel_name, freq in unique_fuel_names.items():
            key = fuel_name
            if ("nomenclature", key) in existing:
                continue
            # Ищем точное совпадение или содержащее имя
            name_upper = fuel_name.upper()
            exact = None
            partial = None
            for nom in nom_rows:
                cmp = (nom.name or "").upper()
                if cmp == name_upper:
                    exact = nom
                    break
                if name_upper in cmp:
                    partial = partial or nom
            best = exact or partial
            if best:
                out.append(MappingSuggestion(
                    kind="nomenclature",
                    source_key=key,
                    source_label=f"ТТН: «{fuel_name}» (встречается {freq} раз)",
                    target_ref=best.external_ref,
                    target_name=best.name,
                    confidence=100 if exact else 75,
                    method="name_match" if exact else "name_substring",
                    note=f"Совпадение {'точное' if exact else 'по подстроке'}",
                ))
        return out

    async def apply(
        self,
        company_id: uuid.UUID,
        suggestions: list[MappingSuggestion],
        min_confidence: int = 80,
    ) -> dict[str, int]:
        """Применяет предложения с confidence ≥ min_confidence.
        Идемпотентно — пропускает уже существующие (UQ index по company+kind+source_key).
        """
        details = {"created": 0, "skipped_existing": 0, "skipped_low_confidence": 0}
        for s in suggestions:
            if s.confidence < min_confidence:
                details["skipped_low_confidence"] += 1
                continue
            existing = (await self.session.execute(
                select(ReconcileMapping).where(
                    ReconcileMapping.company_id == company_id,
                    ReconcileMapping.kind == s.kind,
                    ReconcileMapping.source_key == s.source_key,
                ).limit(1)
            )).scalar_one_or_none()
            if existing:
                details["skipped_existing"] += 1
                continue
            self.session.add(ReconcileMapping(
                id=uuid.uuid4(),
                company_id=company_id,
                kind=s.kind,
                source_key=s.source_key,
                target_ref=s.target_ref,
                target_name=s.target_name,
                confidence=s.confidence,
                method=s.method,
                note=s.note,
            ))
            details["created"] += 1
        return details
