"""Корректировки документов перед выгрузкой в бухгалтерию.

Отчёт о розничных продажах приходит со станции как факт: так продали, так
пробила касса. Бухгалтеру этого иногда мало — цифру нужно поправить перед
проведением. Но исправить факт значит потерять его: через месяц никто не
скажет, что было на самом деле и почему стало иначе.

Поэтому правка не заменяет оригинал, а ложится поверх него отдельной записью с
автором, причиной и временем. В бухгалтерию уходит результат наложения; факт
станции остаётся ровно таким, каким приехал, и «Магазин» показывает его же —
те самые цифры, что видит администратор в агенте.

Канон: `docs/Корректировки_ОРП_перед_выгрузкой.md`.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession



class AdjustmentError(ValueError):
    """Правку применить нельзя — и сказано, почему."""


# Что вообще разрешено править. Список закрытый: правка «любого поля» означает,
# что однажды кто-то переставит идентификатор номенклатуры, и документ уедет в
# бухгалтерию на другой товар.
ПРАВИМЫЕ_ПОЛЯ_СТРОКИ = frozenset({
    "Количество", "Цена", "Сумма", "СуммаНДС", "СтавкаНДС",
})
ПРАВИМЫЕ_ПОЛЯ_ШАПКИ = frozenset({
    "Дата", "Склад", "Комментарий",
})


@dataclass
class Корректировка:
    """Одна правка: что меняем, на что и почему."""

    id: uuid.UUID
    doc_kind: str
    document_id: str
    base_content_hash: str
    patch: dict
    reason: str
    author: str
    created_at: datetime
    status: str = "applied"


@dataclass
class РезультатНаложения:
    """Пакет после наложения правок и что при этом произошло."""

    packet: dict
    применено: list[Корректировка] = field(default_factory=list)
    # Устаревшие: правка сделана на другой версии факта. Молча применять нельзя,
    # молча пропускать — тоже: человек должен решить.
    устарели: list[Корректировка] = field(default_factory=list)

    @property
    def была_правка(self) -> bool:
        return bool(self.применено)


def хеш_документа(документ: dict) -> str:
    """Отпечаток документа для привязки правки к версии факта.

    Считается по сырому документу — до превращения сумм в строки контракта, —
    поэтому канонизацию берём свою: NFC, сортировка ключей, без пробелов, а
    дробные приводим к фиксированной точности. Контрактный `canonical_hash`
    здесь не годится: он запрещает binary float, а в сыром документе суммы
    именно такие.

    Собственная отметка о правках в отпечаток не входит — иначе первая же
    правка сделала бы недействительной саму себя.
    """
    return hashlib.sha256(
        json.dumps(
            _канон(документа_без_служебных(документ)),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _канон(значение: Any) -> Any:
    """Значение в виде, устойчивом к разнице представлений одного и того же числа.

    3 и 3.0 — одна и та же тройка; без приведения правка «слетала» бы после
    пересборки пакета, где то же число пришло другим типом.
    """
    if isinstance(значение, dict):
        return {unicodedata.normalize("NFC", str(k)): _канон(v)
                for k, v in значение.items()}
    if isinstance(значение, (list, tuple)):
        return [_канон(v) for v in значение]
    if isinstance(значение, bool) or значение is None:
        return значение
    if isinstance(значение, (int, float, Decimal)):
        return format(Decimal(str(значение)).normalize(), "f")
    return unicodedata.normalize("NFC", str(значение))


def документа_без_служебных(документ: dict) -> dict:
    return {k: v for k, v in документ.items() if k not in {"Корректировка"}}


async def список_корректировок(
    session: AsyncSession, company_id: uuid.UUID, shift_key: str,
) -> list[Корректировка]:
    """Действующие правки смены, старые первыми: порядок наложения — порядок правок."""
    rows = (await session.execute(text("""
        SELECT id, doc_kind, document_id, base_content_hash, patch, reason,
               author, created_at, status
          FROM accounting_adjustments
         WHERE company_id = :c AND shift_key = :s AND status = 'applied'
         ORDER BY created_at, id
    """), {"c": str(company_id), "s": shift_key})).mappings().all()
    return [Корректировка(
        id=r["id"], doc_kind=r["doc_kind"], document_id=r["document_id"],
        base_content_hash=r["base_content_hash"], patch=r["patch"] or {},
        reason=r["reason"], author=r["author"], created_at=r["created_at"],
        status=r["status"],
    ) for r in rows]


async def история_корректировок(
    session: AsyncSession, company_id: uuid.UUID, shift_key: str,
) -> list[dict]:
    """Все правки смены, включая отменённые: история не редактируется."""
    rows = (await session.execute(text("""
        SELECT id, doc_kind, document_id, patch, reason, author, status,
               created_at, cancelled_at, cancelled_by, base_content_hash
          FROM accounting_adjustments
         WHERE company_id = :c AND shift_key = :s
         ORDER BY created_at DESC, id
    """), {"c": str(company_id), "s": shift_key})).mappings().all()
    return [dict(r) for r in rows]


async def завести_корректировку(
    session: AsyncSession,
    company_id: uuid.UUID,
    *,
    shift_key: str,
    doc_kind: str,
    document_id: str,
    base_content_hash: str,
    patch: dict,
    reason: str,
    author: str,
    business_shift_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Записать правку. Без причины и без содержимого не принимаем."""
    reason = (reason or "").strip()
    if not reason:
        raise AdjustmentError(
            "Причина обязательна: без неё через месяц никто не поймёт, "
            "почему цифра изменилась"
        )
    if not isinstance(patch, dict) or not patch:
        raise AdjustmentError("Пустая правка")
    проверить_правку(patch)
    if len(base_content_hash or "") != 64:
        raise AdjustmentError("Правка должна ссылаться на версию факта (хеш документа)")

    ident = uuid.uuid4()
    await session.execute(text("""
        INSERT INTO accounting_adjustments
            (id, company_id, business_shift_id, shift_key, doc_kind, document_id,
             base_content_hash, patch, reason, author, status)
        VALUES (:id, :c, :bs, :s, :k, :d, :h, CAST(:p AS jsonb), :r, :a, 'applied')
    """), {
        "id": str(ident), "c": str(company_id),
        "bs": str(business_shift_id) if business_shift_id else None,
        "s": shift_key, "k": doc_kind, "d": document_id,
        "h": base_content_hash, "p": _json(patch), "r": reason, "a": author or "",
    })
    return ident


async def отменить_корректировку(
    session: AsyncSession, company_id: uuid.UUID, adjustment_id: uuid.UUID, author: str,
) -> None:
    """Отменить правку. Запись остаётся: история не редактируется, а дополняется."""
    res = await session.execute(text("""
        UPDATE accounting_adjustments
           SET status = 'cancelled', cancelled_at = now(), cancelled_by = :a
         WHERE company_id = :c AND id = :id AND status = 'applied'
    """), {"c": str(company_id), "id": str(adjustment_id), "a": author or ""})
    if res.rowcount == 0:
        raise AdjustmentError("Действующая правка не найдена")


def проверить_правку(patch: dict) -> None:
    """Правка адресная: строка и поле, а не «перебить сумму документа».

    Через полгода в истории должно остаться не «41 889 → 42 100», а «строка 7,
    количество 3 → 2, потому что пересорт».
    """
    строки = patch.get("Строки")
    шапка = patch.get("Шапка")
    if not строки and not шапка:
        raise AdjustmentError("Правка должна менять строки или реквизиты шапки")
    if шапка is not None:
        if not isinstance(шапка, dict):
            raise AdjustmentError("Шапка правки должна быть объектом")
        чужие = set(шапка) - ПРАВИМЫЕ_ПОЛЯ_ШАПКИ
        if чужие:
            raise AdjustmentError(
                "Эти реквизиты шапки править нельзя: " + ", ".join(sorted(чужие))
            )
    if строки is None:
        return
    if not isinstance(строки, list):
        raise AdjustmentError("Строки правки должны быть списком")
    for правка in строки:
        if not isinstance(правка, dict) or "НомерСтроки" not in правка:
            raise AdjustmentError("У правки строки должен быть НомерСтроки")
        поля = set(правка) - {"НомерСтроки"}
        чужие = поля - ПРАВИМЫЕ_ПОЛЯ_СТРОКИ
        if чужие:
            raise AdjustmentError(
                "Эти поля строки править нельзя: " + ", ".join(sorted(чужие)) +
                ". Номенклатуру и идентификаторы меняет станция документом, "
                "а не бухгалтерия правкой"
            )
        if not поля:
            raise AdjustmentError("Правка строки без единого поля")


def наложить(packet: dict, правки: list[Корректировка]) -> РезультатНаложения:
    """Наложить правки на пакет. Оригинал не меняется — работаем с копией.

    Правка применяется, только если факт с тех пор не изменился: хеш документа
    сверяется с тем, на котором её сделали. Иначе она отправляется в «устарели»,
    и решение принимает человек.
    """
    import copy

    итог = РезультатНаложения(packet=copy.deepcopy(packet))
    if not правки:
        return итог
    документы = итог.packet.get("Документы") or []
    по_ключу = {(str(д.get("Тип") or ""), str(д.get("document_id") or д.get("Номер") or "")): д
                for д in документы}
    # Хеши снимаем ОДИН раз, до наложения. Иначе вторая правка, сделанная на той
    # же версии факта, что и первая, объявлялась бы устаревшей — потому что
    # первая уже изменила документ. Устарела правка тогда, когда изменился факт
    # станции, а не когда рядом легла другая правка того же человека.
    оригиналы = {ключ: хеш_документа(док) for ключ, док in по_ключу.items()}

    for правка in правки:
        ключ = (правка.doc_kind, правка.document_id)
        документ = по_ключу.get(ключ)
        if документ is None:
            итог.устарели.append(правка)
            continue
        if оригиналы.get(ключ) != правка.base_content_hash:
            итог.устарели.append(правка)
            continue
        применить_к_документу(документ, правка.patch)
        отметка = документ.setdefault("Корректировка", {
            "Была": True, "ХешОригинала": правка.base_content_hash, "Правки": [],
        })
        отметка["Правки"].append({
            "Автор": правка.author, "Причина": правка.reason,
            "Когда": _iso(правка.created_at), "ID": str(правка.id),
        })
        итог.применено.append(правка)
    return итог


def применить_к_документу(документ: dict, patch: dict) -> None:
    шапка = patch.get("Шапка") or {}
    for поле, значение in шапка.items():
        документ[поле] = значение
    строки = patch.get("Строки") or []
    if not строки:
        return
    товары = документ.get("Товары") or []
    по_номеру = {int(т.get("НомерСтроки") or 0): т for т in товары}
    for правка in строки:
        номер = int(правка.get("НомерСтроки") or 0)
        строка = по_номеру.get(номер)
        if строка is None:
            raise AdjustmentError(
                "Строка %d в документе не найдена: факт изменился" % номер
            )
        for поле, значение in правка.items():
            if поле == "НомерСтроки":
                continue
            строка[поле] = значение


def _iso(значение: Any) -> str:
    if isinstance(значение, datetime):
        if значение.tzinfo is None:
            значение = значение.replace(tzinfo=timezone.utc)
        return значение.isoformat().replace("+00:00", "Z")
    return str(значение or "")


def _json(значение: Any) -> str:
    import json
    return json.dumps(значение, ensure_ascii=False)
