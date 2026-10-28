"""Приложение «Бухгалтерия» пространства: что бухгалтерия знает о наших карточках.

Срез только читает. Сведения бухгалтерии приехали выгруженными отчётами и лежат
строками-источниками (`DataEntry`, слой `raw`) — рабочими карточками пространства они
от этого не становятся. Здесь источник сопоставляется с реестром: договор, контрагент,
площадка. Прямого чтения 1С в этом слое нет и не предполагается: транспорт сменится
(выгрузка → интеграция), а модель сопряжения останется та же.

Три оси различаются и НЕ сводятся в одну галочку:

  сопряжение   `matched` | `related` | `unmatched` | `candidate` — опознана ли запись;
  проверка     какие реквизиты сверены, где расхождения, что не проверяли;
  свежесть     менялась ли карточка после проверки — тогда проверка устарела.

Хеш проверенных значений считается ровно так, как при применении сверки 28.10.2026
(`apply_matched.py`): те же поля, та же сериализация. Сошёлся — проверка в силе,
разошёлся — устарела, и это видно без ручной отметки.

Статус сопряжения берётся ТОЛЬКО из `_accountingReconciliationStatus`. По префиксу
`source_id` (`acct-unmatched:`) его определять нельзя: префикс исторический и стоит
у всех записей партии, включая позднее сопряжённые.

Отметка для карточек и списков (`contract_summary`, `aggregate_summary`,
`entity_summaries`) — продолжение той же механики, без второго способа счёта.
Контракт ручек и правила — `docs/ACCOUNTING_SPACE_STATUS_API.md`. Два правила,
которые нельзя потерять при доработке:

  доказательством сверки считается ТОЛЬКО значение, пришедшее из выгрузки
  (номер и дата). Снимок наших же полей (`target_values`) отвечает за устаревание;

  зелёная отметка договора не переносится на контрагента и площадку: у них своя
  область и агрегат по договорам, а `matched_checked` для них недостижим.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract,
    ContractLocation,
    Counterparty,
    DataEntry,
    ServiceLocation,
)
from app.scope import org_filter, scope_location_conds

# Ключ, по которому запись опознаётся как строка бухгалтерского источника.
STATUS_KEY = "_accountingReconciliationStatus"
# Поля карточки договора, которые сверялись при применении (и входят в хеш).
CHECKED_FIELDS = ("number", "date", "counterparty_id", "type_code")
# Независимая ПОВТОРНАЯ сверка — согласованный envelope (28.10.2026):
#
#   metadata["_accountingRecheck"] = {schema_version, run_id, checked_at,
#       source_as_of, source_sha256, source_rows, overall, source{file,sheet,rows},
#       per_link: [{contract_id, relation, compared_fields[{field,label,source,card,
#           result,basis,source_evidence}], current_hash, unknowns[], open_questions[]}]}
#
# Ключ один и стабильный, дату прогона читаем из `checked_at`: читатель не должен
# знать, какого числа он прошёл, иначе каждый следующий требует правки кода.
# История прогонов живёт отдельно (`_accountingRecheckHistory`) и здесь не
# интерпретируется; прежние `_accountingReconciliations` остаются как есть.
RECHECK_KEY = "_accountingRecheck"
# Отношения, при которых строка описывает ДРУГОЙ документ: дополнения и соглашения.
# Все остальные — включая конфликтные (`number_conflict`, `date_conflict`,
# `joint_party`, `number_missing`, `same_contract_payee_label`, `multiple_cards`) —
# относятся к ТОМУ ЖЕ договору, и его номер с датой сравнивать можно и нужно.
# Перечисляется именно это исключение: белый список молча превращал новые
# конфликтные отношения в «связанный документ» и терял живое сравнение.
OTHER_DOCUMENT_RELATIONS = ("amendment", "amendment_of", "annex", "annex_of",
                            "supplement", "supplement_of", "agreement_of")
# Отношение, которое само означает неоднозначную привязку.
AMBIGUOUS_RELATIONS = ("multiple_cards",)
# Открытый вопрос снимает отметку совпадения, когда он про саму привязку или про
# нехватку сведений в карточке: неоднозначное связывание, противоречие стороны,
# пустая дата карточки. Оговорка о названии стороны и подсказка о роли карточки
# дефектом не являются и зелёного не снимают (калибровка по фактическому набору
# прогона 29.10.2026: party_name_only 425, role_card 152 — подсказки;
# link_ambiguous 66, party_ambiguous_identity 6, card_date_empty 5,
# source_ambiguous 2 — требуют уточнения).
BLOCKING_QUESTION_MARKERS = ("contradict", "ambig", "multiple_cards",
                             "party_conflict", "party_mismatch", "wrong_party")
BLOCKING_QUESTION_CODES = ("card_date_empty",)

LINK_STATUS_LABEL = {
    "matched": "Сопряжено",
    "related": "Связанный документ",
    "candidate": "Нужна проверка",
    "unmatched": "Не сопряжено",
}
VERIFICATION_LABEL = {
    "verified": "Реквизиты сверены",
    "partial": "Часть реквизитов сверена",
    "differences": "Есть расхождения",
    "not_checked": "Не проверено",
    "stale": "Нужна повторная сверка",
}


def _js(value: Any) -> str:
    """Сериализация, на которой считался хеш проверенных значений."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(_js(value).encode()).hexdigest()


def compact(value: Any) -> str:
    """Номер договора без разделителей и регистра: «41-09/ЭЗС-23» ≡ «41 09 ЭЗС 23».

    Мелкая разница в записи номера не делает договор другим (решение по сверке
    28.10.2026), поэтому расхождением считается только несовпадение значимых знаков.

    ⚠ Номер из одних разделителей («-», «б/н») сворачивается в пустую строку, и
    два таких номера нельзя считать совпавшими: сравнивать было нечего. Проверять
    результат на непустоту обязан вызывающий (см. `_compare`).
    """
    return re.sub(r"[^0-9a-zа-я]", "", str(value or "").casefold().replace("ё", "е"))


def _recheck_run(meta: dict[str, Any]) -> dict[str, Any]:
    """Конверт независимой повторной сверки из `metadata` строки источника.

    Ключ ровно один — `_accountingRecheck`. Ключей с датой в имени читатель не
    знает: дата прогона берётся из `checked_at` внутри конверта, иначе каждый
    следующий круг требовал бы правки кода.
    """
    raw = (meta or {}).get(RECHECK_KEY)
    run = raw if isinstance(raw, dict) else _loads(raw)
    return run if isinstance(run, dict) else {}


def _as_iso_date(value: Any) -> str:
    """«15.08.2024» и «2024-08-15» — одна дата: выгрузка пишет и так, и так."""
    text = str(value or "").strip()
    m = re.match(r"^(\d{2})[.\-/](\d{2})[.\-/](\d{4})$", text)
    return f"{m[3]}-{m[2]}-{m[1]}" if m else text


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _loads(raw: Any) -> Any:
    """`_accountingReconciliations` и соседи лежат сериализованным JSON в строке."""
    if isinstance(raw, (list, dict)):
        return raw
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


@dataclass
class Link:
    """Одна связь строки источника с карточкой пространства."""
    entity_type: str
    entity_id: str
    relation: str
    status: str
    verification: str           # verified | partial | differences | not_checked
    stale: bool                 # карточка менялась после проверки
    source_number: str
    source_date: str
    checked_hash: str
    current_hash: str
    checked_values: dict[str, Any]
    current_values: dict[str, Any]
    differences: list[dict[str, Any]]
    location_ids: list[str]
    subject_status: str
    snapshot_at: str
    exists: bool                # карточка ещё существует в реестре
    # Что при сверке НЕ проверяли: сопряжение и проверка реквизитов — разные признаки.
    inn_kpp_checked: bool
    original_document_checked: bool
    # Текущие значения карточки, которые можно сравнивать с источником (шире
    # состава хеша: там только четыре поля устаревания).
    card_values: dict[str, Any] = field(default_factory=dict)
    # Запись независимой ПОВТОРНОЙ сверки по этой связи (`per_link`) и то, можно
    # ли вообще принимать её свидетельство (совпала ли редакция файла).
    recheck: dict[str, Any] = field(default_factory=dict)
    recheck_applicable: bool = True
    recheck_reject_reason: str = ""
    recheck_source: dict[str, Any] = field(default_factory=dict)

    @property
    def same_document(self) -> bool:
        """Описывает ли строка источника сам этот договор, а не другой документ.

        Исключение — только дополнения и соглашения. Конфликтные отношения
        (`number_conflict`, `date_conflict`, `joint_party`, `multiple_cards`…)
        относятся к тому же договору: их номер и дату сравнивать обязательно.
        """
        return self.relation not in OTHER_DOCUMENT_RELATIONS

    @property
    def ambiguous(self) -> bool:
        """Неоднозначная привязка: отметку совпадения ставить нельзя."""
        if self.relation in AMBIGUOUS_RELATIONS:
            return True
        return any(_blocking_question(q) for q in self.open_questions)

    @property
    def open_questions(self) -> list[dict[str, Any]]:
        if not self.recheck_applicable:
            return []
        return [q for q in (self.recheck.get("open_questions") or []) if isinstance(q, dict)]


@dataclass
class Record:
    """Строка бухгалтерского источника вместе с её сопряжениями."""
    id: str
    status: str
    counterparty_name: str
    contract_label: str
    kind: str                   # «Тип по бухгалтерии» / «Предмет»
    reason: str                 # основание сопряжения или разбора
    source_file: str
    source_sheet: str
    source_rows: str
    source_period: str
    source_as_of: str
    source_sha256: str
    source_key: str
    source_key_type: str
    batch_id: str
    entry_status: str
    layer: str
    station_hint: str           # номера ЭЗС из бухгалтерии (подсказка ВПР)
    candidates: str
    links: list[Link] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: Any = None
    # Прогон независимой повторной сверки: `verified_at`, `overall`, `proven`,
    # `not_proven`. Время этого прогона — НЕ `snapshot_at` прежнего применения.
    recheck: dict[str, Any] = field(default_factory=dict)
    # Были ли у строки связи, снятые по недоступному юрлицу: строка целиком
    # относится к чужому разрезу и в ответ не попадает.
    org_hidden: bool = False

    @property
    def verification(self) -> str:
        """Проверка строки: худшее из её связей; устаревшая важнее частичной."""
        if not self.links:
            return "not_checked"
        states = [_link_verification(l) for l in self.links]
        if "stale" in states:
            return "stale"
        for state in VERIFICATION_ORDER:
            if state in states:
                return state
        return "not_checked"

    @property
    def location_ids(self) -> list[str]:
        out: list[str] = []
        for link in self.links:
            for loc in link.location_ids:
                if loc not in out:
                    out.append(loc)
        return out


@dataclass
class Slice:
    """Готовый срез: записи источника плюс карточки пространства, на которые они легли."""
    records: list[Record]
    contracts: dict[str, Contract]
    counterparties: dict[str, Counterparty]
    locations: dict[str, ServiceLocation]
    contract_locations: dict[str, list[str]]
    space_contracts_total: int
    space_counterparties_total: int
    space_locations_total: int


def _blocking_question(question: dict[str, Any]) -> bool:
    """Снимает ли открытый вопрос прогона отметку совпадения.

    Блокируют доказанное противоречие стороны и неоднозначность связывания.
    Подсказка о виде или роли договора — нет: у РусГидро аренда площадки и
    получение электроэнергии часто заведены двумя карточками с одним номером и
    датой, и «карточка другой роли» конфликтом не является.
    """
    code = str((question or {}).get("code") or "").casefold()
    return (code in BLOCKING_QUESTION_CODES
            or any(marker in code for marker in BLOCKING_QUESTION_MARKERS))


def _contract_values(c: Contract) -> dict[str, Any]:
    """Состав хеша устаревания. Менять нельзя: он совпадает с применённой сверкой."""
    return {
        "number": c.number,
        "date": c.date,
        "counterparty_id": str(c.counterparty_id),
        "type_code": c.type_code,
    }


def _card_values(c: Contract, cp: Counterparty | None) -> dict[str, Any]:
    """Всё, что у карточки можно сравнить с источником, а не только состав хеша."""
    return {
        **_contract_values(c),
        "type": c.type,
        "title": c.title or "",
        "counterparty_name": cp.name if cp else "",
        "counterparty_inn": (cp.inn if cp else "") or "",
        "counterparty_kpp": (cp.kpp if cp else "") or "",
    }


FIELD_LABEL = {
    "number": "Номер",
    "date": "Дата",
    "counterparty_name": "Сторона договора",
    "counterparty_inn": "ИНН стороны",
    "counterparty_kpp": "КПП стороны",
    "type_code": "Вид договора",
    "type": "Вид договора",
}


def _compare(field_name: str, source: Any, card: Any) -> tuple[str, str]:
    """Сравнить значение источника с ТЕКУЩИМ значением карточки.

    Возвращает (`match` | `difference` | `unknown`, основание). Недостаток
    сведений и неразобранное значение — это `unknown`, а НЕ расхождение:
    «неизвестно» нельзя показывать менеджеру как конфликт.

    Сравнивает сервер сам, по своим правилам. Сохранённому результату прогона
    здесь не доверяют: он мог считаться по другой редакции карточки.
    """
    if field_name == "number":
        a, b = compact(source), compact(card)
        if not a:
            return "unknown", "номер источника без значимых знаков — сравнивать нечего"
        if not b:
            return "unknown", "в карточке номера нет"
        return ("match" if a == b else "difference"), "значимые знаки номера"
    if field_name == "date":
        a, b = _as_iso_date(source), _as_iso_date(card)
        if not a:
            return "unknown", "в выгрузке даты нет"
        if not b:
            return "unknown", "в карточке даты нет"
        return ("match" if a == b else "difference"), "точное значение даты"
    if field_name in ("counterparty_inn", "counterparty_kpp"):
        a, b = _digits(source), _digits(card)
        if not a or not b:
            return "unknown", "реквизит известен не с обеих сторон"
        return ("match" if a == b else "difference"), "точные цифры реквизита"
    if field_name in ("counterparty_name", "party", "counterparty"):
        # Совместимость названий сервер не пересчитывает и доказательством
        # идентичности стороны не считает: ИНН в выгрузке нет.
        return "unknown", ("совместимость названий — не юридическая проверка стороны, "
                           "ИНН и КПП выгрузка не содержит")
    if field_name in ("type_code", "type"):
        return "unknown", ("вид договора выгрузка не подтверждает: одна площадка "
                           "заводится двумя карточками — аренда и электроэнергия")
    return "unknown", "это поле сервер не сравнивает"


def _comparison(link: Link, field_name: str, source: Any, *, origin: str,
                claimed: str | None = None, basis: str = "", label: str = "",
                evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    card = link.card_values.get(field_name, "")
    if not link.exists:
        result, why = "unknown", "карточка недоступна — сверить нечем"
    elif (origin == "row" and field_name in ("number", "date")
            and not link.same_document):
        # Номер и дата СТРОКИ у дополнения — реквизиты его самого. Конверт
        # повторной сверки отдаёт для дополнения номер и дату ОСНОВНОГО договора
        # (разобраны отдельно), поэтому его значения сравнивать можно.
        result, why = "unknown", "другой документ: это не реквизит паспорта договора"
    else:
        result, why = _compare(field_name, source, card)
    return {
        "field": field_name,
        "label": label or FIELD_LABEL.get(field_name, field_name),
        "source": "" if source is None else str(source),
        "space": "" if card is None else str(card),
        # `equal` остаётся для совместимости с интерфейсом: true/false/null.
        "equal": True if result == "match" else (False if result == "difference" else None),
        "result": result,
        "basis": why,
        # Откуда взялось значение источника: строка выгрузки или конверт прогона.
        "origin": origin,
        # Что записал об этом поле сам прогон. Показывается, но на отметку не влияет.
        "claimed": claimed,
        "claimed_basis": basis or None,
        "evidence": evidence or None,
    }


def comparisons(link: Link) -> list[dict[str, Any]]:
    """Все сравнения связи: что сошлось с источником, что разошлось, что неизвестно.

    Доказательство всегда пересчитывается здесь. Из прогона берутся ЗНАЧЕНИЯ
    стороны источника, а не его вердикт: иначе достаточно записать `match`, чтобы
    отметка стала зелёной. Прогон, выполненный по другой редакции файла, в
    доказательства не допускается вовсе.
    """
    out = [_comparison(link, name, src, origin="row")
           for name, src in (("number", link.source_number), ("date", link.source_date))]
    positions = {item["field"]: index for index, item in enumerate(out)}
    rechecked_fields: set[str] = set()
    if not link.recheck_applicable:
        return out
    for raw in (link.recheck.get("compared_fields") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("field") or "")
        if not name:
            continue
        claimed = str(raw.get("result") or "") or None
        basis = str(raw.get("basis") or "")
        evidence = raw.get("source_evidence") or link.recheck_source or None
        item = _comparison(link, name, raw.get("source"), origin="recheck",
                           claimed=claimed, basis=basis, evidence=evidence,
                           label=str(raw.get("label") or ""))
        if name in positions and name not in rechecked_fields:
            # Повторная сверка разбирает исходную ячейку заново. Её значение
            # заменяет прежний разбор ТОГО ЖЕ поля, а не становится вторым
            # источником: в легаси номере мог остаться текст «Договор аренды».
            # Старое представление сохраняем для трассы, не как расхождение.
            previous = out[positions[name]]
            if previous["source"] != item["source"]:
                item["legacy_source"] = previous["source"]
            out[positions[name]] = item
        else:
            # Если сам конверт дал несколько значений поля, сохраняем их все:
            # последнее значение не должно молча спрятать противоречие.
            positions.setdefault(name, len(out))
            out.append(item)
        rechecked_fields.add(name)
    return out


def _link_differences(link: Link) -> list[dict[str, Any]]:
    """Расхождения связи — только поля, которые сервер сравнил сам и они разошлись."""
    return [{"field": c["field"], "label": c["label"],
             "source": c["source"], "space": c["space"], "basis": c["basis"]}
            for c in comparisons(link) if c["result"] == "difference"]


def contract_acl(organization_id: str | None = None) -> list:
    """Условия доступа к договору: активное юрлицо запроса плюс выбор в интерфейсе.

    Юрлицо приходит двумя путями, и учитывать надо ОБА. `org_filter` — закреплённая
    за участником организация и заголовок `X-Organization-Id` (ставятся в
    `assert_company_member` и middleware), параметр ручки — текущий выбор на экране.
    Пока здесь стоял только параметр, аутсорсер, закреплённый за одним ООО, видел
    сопряжения второго юрлица того же владельца, просто не передав параметр.

    Скоуп объектов участника сюда не входит: договор — не объект, и площадки у него
    бывают разные. Он держится на автоматическом сужении `ServiceLocation`
    (`scope.install_orm_scope`), поэтому площадки вне скоупа в срез не попадают.
    """
    conds = [org_filter(Contract.organization_id)]
    if organization_id and _is_uuid(organization_id):
        conds.append(Contract.organization_id == uuid.UUID(organization_id))
    return conds


async def load_slice(db: AsyncSession, company_id: uuid.UUID,
                     organization_id: str | None = None) -> Slice:
    """Читает все строки бухгалтерского источника компании и их окружение.

    ponytail: срез целиком в память — на 28.10.2026 это 395 строк и 901 договор.
    Числа плиток, списков и выгрузки обязаны происходить из одного отбора, а один
    проход это гарантирует дешевле, чем пять согласованных SQL. Когда источников
    станет десятки тысяч строк, отбор уедет в SQL с теми же правилами.
    """
    rows = (await db.execute(
        select(DataEntry)
        .where(DataEntry.company_id == company_id, DataEntry.meta.has_key(STATUS_KEY))
        # Вторым ключом — id: вся партия приехала одной транзакцией с одинаковым
        # `created_at`, и без него порядок строк между запросами плавает, а страницы
        # теряют и повторяют записи.
        .order_by(DataEntry.created_at, DataEntry.id)
    )).scalars().all()

    records: list[Record] = []
    contract_ids: set[str] = set()
    for e in rows:
        m = e.meta or {}
        rec = Record(
            id=str(e.id),
            status=str(m.get(STATUS_KEY) or ""),
            counterparty_name=str(m.get("Контрагент в бухгалтерии") or ""),
            contract_label=str(m.get("Договор или основание") or ""),
            kind=str(m.get("Тип по бухгалтерии") or m.get("Предмет") or ""),
            reason=str(m.get("Основание сопряжения") or m.get("Основание разбора") or ""),
            source_file=str(m.get("Файл источника") or ""),
            source_sheet=str(m.get("Лист источника") or ""),
            source_rows=str(m.get("Строки источника") or ""),
            source_period=str(m.get("Период источника") or ""),
            source_as_of=str(m.get("_accountingSourceAsOf") or ""),
            source_sha256=str(m.get("_accountingSourceSha256") or ""),
            source_key=str(m.get("_accountingSourceKey") or ""),
            source_key_type=str(m.get("_accountingSourceKeyType") or ""),
            batch_id=str(m.get("_accountingBatchId") or ""),
            entry_status=e.status,
            layer=e.layer,
            station_hint=str(m.get("Номера ЭЗС из бухгалтерии") or ""),
            candidates=str(m.get("Кандидаты в пространстве") or ""),
            meta=m,
            created_at=e.created_at,
            recheck=_recheck_run(m),
        )
        # Прогон, выполненный по другой редакции файла, свидетельством не является:
        # его значения источника взяты не из той выгрузки, что лежит в строке.
        envelope_sha = str(rec.recheck.get("source_sha256") or "")
        applicable, reject = True, ""
        if envelope_sha and rec.source_sha256 and envelope_sha != rec.source_sha256:
            applicable, reject = False, ("повторная сверка выполнена по другой редакции "
                                         "файла источника")
        envelope_source = rec.recheck.get("source") if isinstance(
            rec.recheck.get("source"), dict) else {}
        by_contract_recheck = {str(x.get("contract_id") or x.get("entity_id") or ""): x
                               for x in (rec.recheck.get("per_link") or [])
                               if isinstance(x, dict)}
        for raw in _loads(m.get("_accountingReconciliations")):
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or "")
            if raw.get("entity_type") == "contract" and entity_id:
                contract_ids.add(entity_id)
            rec.links.append(Link(
                entity_type=str(raw.get("entity_type") or ""),
                entity_id=entity_id,
                relation=str(raw.get("relation") or ""),
                status=str(raw.get("status") or rec.status),
                verification=str(raw.get("verification_status") or "not_checked"),
                stale=False,
                source_number=str(raw.get("source_number") or ""),
                source_date=str(raw.get("source_date") or ""),
                checked_hash=str(raw.get("target_checked_hash") or ""),
                current_hash="",
                checked_values=raw.get("target_values") or {},
                current_values={},
                differences=[],
                location_ids=[str(x) for x in (raw.get("location_ids") or [])],
                subject_status=str(raw.get("subject_status") or ""),
                snapshot_at=str(raw.get("snapshot_at") or ""),
                exists=False,
                inn_kpp_checked=bool(raw.get("inn_kpp_checked")),
                original_document_checked=bool(raw.get("original_document_checked")),
                recheck=by_contract_recheck.get(entity_id) or {},
                recheck_applicable=applicable,
                recheck_reject_reason=reject,
                recheck_source=envelope_source,
            ))
        records.append(rec)

    contracts: dict[str, Contract] = {}
    in_company: set[str] = set()
    if contract_ids:
        valid = [uuid.UUID(x) for x in contract_ids if _is_uuid(x)]
        if valid:
            stmt = select(Contract).where(Contract.company_id == company_id,
                                          Contract.id.in_(valid),
                                          *contract_acl(organization_id))
            for c in (await db.execute(stmt)).scalars().all():
                contracts[str(c.id)] = c
            # Отдельно — только ID, без содержимого: по ним отличается «карточки
            # нет вообще» (целостность, это показываем) от «карточка чужого
            # юрлица» (скрываем целиком — вместе с названиями из её строк).
            in_company = {str(x) for x in (await db.execute(
                select(Contract.id).where(Contract.company_id == company_id,
                                          Contract.id.in_(valid)))).scalars().all()}

    cp_ids = {str(c.counterparty_id) for c in contracts.values()}
    counterparties: dict[str, Counterparty] = {}
    if cp_ids:
        valid_cp = [uuid.UUID(x) for x in cp_ids if _is_uuid(x)]
        if valid_cp:
            for cp in (await db.execute(select(Counterparty).where(
                    Counterparty.company_id == company_id,
                    Counterparty.id.in_(valid_cp)))).scalars().all():
                counterparties[str(cp.id)] = cp

    # Текущее состояние карточки против проверенного: расхождения и устаревшая проверка.
    for rec in records:
        visible: list[Link] = []
        for link in rec.links:
            c = contracts.get(link.entity_id)
            if c is None:
                # Карточка есть в компании, но не в доступном юрлице — связь
                # вместе с её сведениями из ответа убирается.
                if link.entity_id in in_company:
                    rec.org_hidden = True
                    continue
                visible.append(link)
                continue
            visible.append(link)
            link.exists = True
            link.current_values = _contract_values(c)
            link.card_values = _card_values(c, counterparties.get(str(c.counterparty_id)))
            link.current_hash = digest(link.current_values)
            # База устаревания — самый свежий известный хеш: если повторная сверка
            # уже учла правку, устаревшей проверку второй раз не объявляем. Прогон
            # по другой редакции файла базой быть не может.
            baseline = link.checked_hash
            if link.recheck_applicable and link.recheck.get("current_hash"):
                baseline = str(link.recheck["current_hash"])
            link.stale = bool(baseline) and baseline != link.current_hash
            link.differences = _link_differences(link)
        rec.links = visible
    # Строка, у которой все связи оказались чужого юрлица, относится к чужому
    # разрезу целиком: её контрагент и основание в ответ не попадают.
    records = [r for r in records if r.links or not r.org_hidden]

    contract_locations: dict[str, list[str]] = {}
    for contract_id, location_id in (await db.execute(
        select(ContractLocation.contract_id, ContractLocation.location_id)
        .where(ContractLocation.company_id == company_id,
               # Привязки к объектам вне скоупа участника не показываются даже
               # счётчиком: пустая строка площадки — тоже сведение о ней.
               *scope_location_conds(ContractLocation.location_id))
    )).all():
        contract_locations.setdefault(str(contract_id), []).append(str(location_id))

    loc_ids = {loc for ids in contract_locations.values() for loc in ids}
    locations: dict[str, ServiceLocation] = {}
    if loc_ids:
        # Скоуп объектов участника — условием запроса, а не только автоматическим
        # сужением ORM: ACL должен держаться и там, где событие сессии не поставлено.
        for loc in (await db.execute(select(ServiceLocation).where(
                ServiceLocation.company_id == company_id,
                ServiceLocation.id.in_(loc_ids),
                *scope_location_conds(ServiceLocation.id)))).scalars().all():
            locations[str(loc.id)] = loc

    # Итоги пространства — в том же разрезе, что и сам срез: иначе плитка
    # «договоров в пространстве» считает чужое юрлицо и чужие объекты.
    totals = (await db.execute(select(
        select(func.count()).select_from(Contract)
        .where(Contract.company_id == company_id,
               *contract_acl(organization_id)).scalar_subquery(),
        select(func.count()).select_from(Counterparty)
        .where(Counterparty.company_id == company_id).scalar_subquery(),
        select(func.count()).select_from(ServiceLocation)
        .where(ServiceLocation.company_id == company_id,
               *scope_location_conds(ServiceLocation.id)).scalar_subquery(),
    ))).one()

    return Slice(
        records=records, contracts=contracts, counterparties=counterparties,
        locations=locations, contract_locations=contract_locations,
        space_contracts_total=int(totals[0] or 0),
        space_counterparties_total=int(totals[1] or 0),
        space_locations_total=int(totals[2] or 0),
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def contract_brief(slice_: Slice, contract_id: str) -> dict[str, Any]:
    """Карточка договора так, как её видит бухгалтерский экран (сторона пространства)."""
    c = slice_.contracts.get(contract_id)
    if c is None:
        # Карточку удалили или она вне выбранного юрлица — молча не исчезаем.
        return {"id": contract_id, "exists": False}
    cp = slice_.counterparties.get(str(c.counterparty_id))
    locs = slice_.contract_locations.get(contract_id, [])
    return {
        "id": contract_id, "exists": True,
        "number": c.number, "date": c.date, "title": c.title,
        "type": c.type, "type_code": c.type_code, "basis": c.basis,
        "valid_until": c.valid_until,
        "signed": c.signed, "signed_at": c.signed_at,
        "counterparty_id": str(c.counterparty_id),
        "counterparty_name": cp.name if cp else "",
        "counterparty_inn": (cp.inn if cp else None) or "",
        "counterparty_kpp": (cp.kpp if cp else None) or "",
        "organization_id": str(c.organization_id),
        "locations": [{
            "id": loc,
            "code": slice_.locations[loc].code if loc in slice_.locations else "",
            "name": slice_.locations[loc].name if loc in slice_.locations else "",
        } for loc in locs],
    }


def record_row(rec: Record, slice_: Slice) -> dict[str, Any]:
    """Строка списка: сведения источника плюс чем они легли в пространство."""
    cards = [contract_brief(slice_, l.entity_id) for l in rec.links
             if l.entity_type == "contract"]
    return {
        "id": rec.id,
        "status": rec.status,
        "status_label": LINK_STATUS_LABEL.get(rec.status, rec.status),
        "verification": rec.verification,
        "verification_label": VERIFICATION_LABEL.get(rec.verification, rec.verification),
        "counterparty_name": rec.counterparty_name,
        "contract_label": rec.contract_label,
        "kind": rec.kind,
        "reason": rec.reason,
        "entry_status": rec.entry_status,
        "layer": rec.layer,
        "source_file": rec.source_file,
        "source_sheet": rec.source_sheet,
        "source_rows": rec.source_rows,
        "source_period": rec.source_period,
        "source_as_of": rec.source_as_of,
        "batch_id": rec.batch_id,
        "station_hint": rec.station_hint,
        "candidates": rec.candidates,
        "links_count": len(rec.links),
        "differences_count": sum(len(l.differences) for l in rec.links),
        "stale_count": sum(1 for l in rec.links if l.stale),
        # Когда прошла независимая повторная сверка этой строки и чем кончилась.
        "rechecked_at": str(rec.recheck.get("checked_at") or "") or None,
        "recheck_overall": str(rec.recheck.get("overall") or "") or None,
        "location_ids": rec.location_ids,
        "cards": cards,
        "card_labels": [
            (f"{c.get('number', '')} от {c.get('date', '')}" if c.get("exists")
             else "карточка не найдена") for c in cards
        ],
    }


def record_card(rec: Record, slice_: Slice) -> dict[str, Any]:
    """Карточка строки: обе стороны, перечень сверенных полей и расшифровка до источника."""
    row = record_row(rec, slice_)
    row["source_side"] = {
        "counterparty": rec.counterparty_name,
        "contract": rec.contract_label,
        "kind": rec.kind,
        "period": rec.source_period,
        "as_of": rec.source_as_of,
        "file": rec.source_file,
        "sheet": rec.source_sheet,
        "rows": rec.source_rows,
        "sha256": rec.source_sha256,
        "key": rec.source_key,
        "key_type": rec.source_key_type,
        "record_kind": str(rec.meta.get("_accountingRecordKind") or ""),
        "station_hint": rec.station_hint,
        # Признака проведения документа выгрузка не содержит — показываем неизвестным.
        "posted": None,
        "original_document": None,
    }
    # Независимая повторная сверка строки: своё время, свой вердикт и кандидаты,
    # которые она нашла в реестре для несопряжённой строки.
    row["recheck"] = {
        "run_id": str(rec.recheck.get("run_id") or ""),
        "checked_at": str(rec.recheck.get("checked_at") or "") or None,
        "overall": str(rec.recheck.get("overall") or "") or None,
        "candidates_in_registry": rec.recheck.get("candidates_in_registry"),
        "public_note": str(rec.meta.get("Повторная сверка") or ""),
    } if rec.recheck else None
    row["links"] = [{
        "entity_type": l.entity_type,
        "entity_id": l.entity_id,
        "relation": l.relation,
        "status": l.status,
        "status_label": LINK_STATUS_LABEL.get(l.status, l.status),
        "verification": _link_verification(l),
        "verification_label": VERIFICATION_LABEL.get(
            _link_verification(l), l.verification),
        "stale": l.stale,
        "subject_status": l.subject_status,
        "snapshot_at": l.snapshot_at,
        # Сверено с источником — только то, что сошлось с его собственным значением.
        # Снимок полей карточки лежит рядом и сверкой не называется.
        "checked_fields": sorted({c["field"] for c in comparisons(l)
                                  if c["result"] == "match"}),
        "compared_fields": comparisons(l),
        "snapshot_fields": sorted(l.checked_values),
        "unchecked_fields": _unchecked_fields([l]),
        "recheck": _recheck_block([l], rec.recheck),
        "checked_values": l.checked_values,
        "current_values": l.current_values,
        "checked_hash": l.checked_hash,
        "current_hash": l.current_hash,
        "differences": l.differences,
        # Что НЕ проверялось — отдельными признаками: сопряжение не означает ни сверки
        # ИНН/КПП, ни проверки по оригиналу документа.
        "inn_kpp_checked": l.inn_kpp_checked,
        "original_document_checked": l.original_document_checked,
        "card": contract_brief(slice_, l.entity_id),
        "location_ids": l.location_ids,
    } for l in rec.links]
    return row


def summary(slice_: Slice) -> dict[str, Any]:
    """Плитки обзора: что загружено, насколько разобрано и что требует внимания."""
    recs = slice_.records
    by_status: dict[str, int] = {}
    by_verification: dict[str, int] = {}
    for r in recs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_verification[r.verification] = by_verification.get(r.verification, 0) + 1

    linked_contracts = {l.entity_id for r in recs for l in r.links
                        if l.entity_type == "contract" and l.entity_id}
    missing_cards = {l.entity_id for r in recs for l in r.links if not l.exists and l.entity_id}
    linked_locations = {loc for r in recs for loc in r.location_ids}
    return {
        "source_rows": len(recs),
        "by_status": by_status,
        "by_verification": by_verification,
        "differences": sum(1 for r in recs if r.verification == "differences"),
        "stale": sum(1 for r in recs if r.verification == "stale"),
        "linked_contracts": len(linked_contracts),
        "linked_locations": len(linked_locations),
        "missing_cards": len(missing_cards),
        "counterparties_in_source": len({r.counterparty_name for r in recs if r.counterparty_name}),
        "contracts_in_source": len({r.contract_label for r in recs if r.contract_label}),
        "space": {
            "contracts": slice_.space_contracts_total,
            "counterparties": slice_.space_counterparties_total,
            "locations": slice_.space_locations_total,
            "contracts_without_source": max(slice_.space_contracts_total - len(linked_contracts), 0),
        },
        "periods": sorted({r.source_period for r in recs if r.source_period}),
        "as_of": sorted({r.source_as_of for r in recs if r.source_as_of}),
        # Периметр выгрузки уже ограничен: в отчёт попали только расчёты за 9 месяцев
        # 2026. «Нет в бухгалтерии» для остальных карточек значит «нет сведений для
        # сравнения», а не отсутствие договора в учёте.
        "scope": ("Выгрузка охватывает расчёты за указанный период. Договор пространства "
                  "без строки источника не значит, что его нет в бухгалтерии: вне периметра "
                  "выгрузки сведений для сравнения нет."),
    }


def sources(slice_: Slice) -> list[dict[str, Any]]:
    """Журнал источников: файл, партия, период, SHA-256 и что из него разобрано."""
    groups: dict[tuple, dict[str, Any]] = {}
    for r in slice_.records:
        key = (r.batch_id, r.source_file, r.source_sheet, r.source_period,
               r.source_as_of, r.source_sha256)
        g = groups.setdefault(key, {
            "batch_id": r.batch_id, "file": r.source_file, "sheet": r.source_sheet,
            "period": r.source_period, "as_of": r.source_as_of,
            "sha256": r.source_sha256, "key_type": r.source_key_type,
            "rows": 0, "by_status": {}, "loaded_at": None,
            # Дату выгрузки из 1С источник не сообщает: «на 30.09» — дата данных,
            # не дата формирования файла. Не выдумываем её.
            "exported_at": None,
        })
        g["rows"] += 1
        g["by_status"][r.status] = g["by_status"].get(r.status, 0) + 1
        if r.created_at and (g["loaded_at"] is None or r.created_at < g["loaded_at"]):
            g["loaded_at"] = r.created_at
    return sorted(groups.values(), key=lambda g: (g["file"], g["batch_id"]))


def objects_report(slice_: Slice) -> list[dict[str, Any]]:
    """Отчёт по объекту: на каких основаниях стоит площадка и что об этом знает учёт.

    Аренда земли и получение электроэнергии — первый предметный контур: именно они
    отвечают на вопрос «чем обоснована площадка». Техприсоединение сюда не
    приравнивается — это отдельное основание.
    """
    # Договор → строки источника, которые на него легли.
    by_contract: dict[str, list[tuple[Record, Link]]] = {}
    for r in slice_.records:
        for l in r.links:
            if l.entity_type == "contract" and l.entity_id:
                by_contract.setdefault(l.entity_id, []).append((r, l))

    out: list[dict[str, Any]] = []
    for loc_id, loc in slice_.locations.items():
        contracts = [cid for cid, locs in slice_.contract_locations.items()
                     if loc_id in locs and cid in slice_.contracts]
        if not contracts:
            continue
        rent, energy, other = [], [], []
        for cid in contracts:
            c = slice_.contracts[cid]
            item = {
                "contract": contract_brief(slice_, cid),
                "source": [{
                    "record_id": r.id, "status": r.status,
                    "status_label": LINK_STATUS_LABEL.get(r.status, r.status),
                    "verification": _link_verification(l),
                    "counterparty": r.counterparty_name,
                    "contract_label": r.contract_label,
                    "file": r.source_file, "rows": r.source_rows,
                    "as_of": r.source_as_of,
                } for r, l in by_contract.get(cid, [])],
            }
            (rent if c.type_code == "rent" else
             energy if c.type_code == "energy_supply" else other).append(item)
        items = rent + energy + other
        linked = sum(1 for i in items if i["source"])
        unchecked = sum(1 for i in items for s in i["source"]
                        if s["verification"] in ("not_checked", "stale", "differences"))
        out.append({
            "id": loc_id, "code": loc.code, "name": loc.name,
            "address": loc.address or "", "status": loc.status,
            "rent": rent, "energy": energy, "other": other,
            "contracts_count": len(items),
            "with_source": linked,
            "without_source": len(items) - linked,
            "unchecked": unchecked,
            "has_rent": bool(rent), "has_energy": bool(energy),
        })
    return sorted(out, key=lambda o: (o["code"] or "", o["name"] or ""))


def entity_links(slice_: Slice, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    """Сопряжения конкретной карточки — для бейджа в её собственном экране.

    Общая механика живёт здесь, а не внутри страницы «Бухгалтерия»: карточке договора
    нужен тот же ответ «что об этом знает бухгалтерия», что и очереди разбора.
    """
    out: list[dict[str, Any]] = []
    for r in slice_.records:
        for l in r.links:
            if l.entity_type != entity_type or l.entity_id != entity_id:
                continue
            compared = comparisons(l)
            state = _link_verification(l)
            out.append({
                "record_id": r.id,
                "status": l.status,
                "status_label": LINK_STATUS_LABEL.get(l.status, l.status),
                "verification": state,
                "verification_label": VERIFICATION_LABEL.get(state, state),
                "stale": l.stale,
                "relation": l.relation,
                # Та же честность, что в карточке строки: «сверены поля» — это
                # поля источника, сошедшиеся с карточкой, а не снимок карточки.
                "checked_fields": sorted({c["field"] for c in compared
                                          if c["result"] == "match"}),
                "compared_fields": compared,
                "snapshot_fields": sorted(l.checked_values),
                "unchecked_fields": _unchecked_fields([l]),
                "recheck": _recheck_block([l], r.recheck),
                "differences": l.differences,
                "source": {
                    "counterparty": r.counterparty_name,
                    "contract": r.contract_label,
                    "file": r.source_file, "sheet": r.source_sheet,
                    "rows": r.source_rows, "period": r.source_period,
                    "as_of": r.source_as_of,
                },
            })
    return out


# ── Сводка сопряжения для карточек и списков ─────────────────────────────────
#
# Тот же срез, но свёрнутый до одной отметки у карточки: списки договоров,
# контрагентов и площадок показывают доказанную сверку и необходимость уточнения
# прямо в строке, не заставляя человека открывать «Бухгалтерию». Механизм ОДИН на
# все виды карточек: второй отметки, которая считается иначе, здесь быть не должно.

ENTITY_TYPES = ("contract", "counterparty", "location")

ENTITY_STATE_LABEL = {
    "matched_checked": "Совпадает по сверенным реквизитам",
    "contracts_checked": "Договоры сверены, карточка не сверялась",
    "differences": "Расхождения с бухгалтерией",
    "stale": "Устарело, нужна повторная сверка",
    "needs_check": "Требует сверки",
    "no_source": "Нет данных для сравнения",
}
ENTITY_STATE_NOTE = {
    "matched_checked": ("Сверены только реквизиты из состава сверки — это не полная "
                        "проверка договора: ИНН и КПП, оригинал документа и проведение "
                        "в 1С не проверялись."),
    "contracts_checked": ("Сверка относится к договорам этой карточки, а не к самой "
                          "карточке: её реквизиты с бухгалтерией не сверялись."),
    "differences": "Значение выгрузки не совпало с карточкой — нужно уточнение.",
    "stale": ("Карточку правили после сверки: сверенные значения изменились, "
              "проверку нужно повторить."),
    "needs_check": "Сопряжение есть, но сверка реквизитов не подтверждена.",
    "no_source": ("Строк выгрузки на эту карточку не легло. Выгрузка охватывает свой "
                  "период: отсутствие строки не означает, что договора нет в учёте 1С."),
}
# Худшее состояние показывается первым: менеджеру важнее то, что требует работы.
STATE_ORDER = ("differences", "stale", "needs_check", "matched_checked",
               "contracts_checked", "no_source")
# То же для оси проверки — у неё свой словарь значений (`VERIFICATION_LABEL`).
VERIFICATION_ORDER = ("differences", "not_checked", "partial", "verified")

# Чего сверка НЕ касалась НИ В ОДНОМ случае. Перечисляется всегда и явно:
# «сопряжено» не значит «проверено целиком», и список непроверенного — часть
# ответа, а не примечание. К этому перечню добавляются поля, которые не подтвердил
# именно этот источник (см. `_unchecked_fields`).
UNCHECKED_ALWAYS = [
    {"field": "inn_kpp", "label": "ИНН и КПП", "reason": "в выгрузке не сопоставлялись"},
    {"field": "original_document", "label": "Оригинал документа",
     "reason": "первичные документы не предоставлены"},
    {"field": "posted_in_1c", "label": "Проведение в 1С",
     "reason": "признака проведения выгрузка не содержит"},
    {"field": "signing", "label": "Подписание",
     "reason": "сведений о подписании в выгрузке нет"},
    {"field": "amounts", "label": "Суммы и расчёты",
     "reason": "денежных величин в принятых данных нет"},
]
UNCHECKED_LABEL = {
    "number": ("Номер", "в выгрузке номера нет — сравнивать было нечего"),
    "date": ("Дата", "в выгрузке даты нет — сравнивать было нечего"),
    "counterparty_id": ("Идентичность стороны",
                        "источник дал только название; ИНН и КПП не сверялись"),
    "type_code": ("Вид договора",
                  "вид в выгрузке не подтверждён — значение снято с карточки"),
}
SCOPE_LABEL = {
    "self": "Сверка самой карточки",
    "contracts_of_counterparty": "Сводка по договорам контрагента",
    "contracts_of_location": "Сводка по договорам площадки",
}
DISCLAIMER = ("Нет строки источника — значит нет сведений для сравнения в пределах "
              "периметра выгрузки, а не отсутствие договора в бухгалтерии.")


def _unchecked_fields(links: list[Link]) -> list[dict[str, Any]]:
    """Что осталось непроверенным у ИМЕННО ЭТОЙ карточки.

    Постоянного перечня мало: если источник не дал номера или даты, их тоже никто
    не сверял, а идентичность стороны и вид договора выгрузка не подтверждала
    никогда — они лежат в снимке карточки, а не в сведениях источника.
    """
    out: list[dict[str, Any]] = []
    fields = [c for link in links for c in comparisons(link)]
    matched = {c["field"] for c in fields if c["result"] == "match"}
    compared = {c["field"] for c in fields if c["result"] != "unknown"}
    for name in ("number", "date", "counterparty_id", "type_code"):
        if name in compared:
            continue
        # Идентичность стороны остаётся непроверенной, пока не сошлись её
        # реквизиты: совместимость названий юридической проверкой не является.
        if name == "counterparty_id" and "counterparty_inn" in matched:
            continue
        label, reason = UNCHECKED_LABEL[name]
        if name in ("number", "date"):
            reasons = list(dict.fromkeys(c["basis"] for c in fields
                if c["field"] == name and c["result"] == "unknown"))
            reason = "; ".join(reasons) or reason
        out.append({"field": name, "label": label, "reason": reason})
    always = [x for x in UNCHECKED_ALWAYS
              if not (x["field"] == "inn_kpp" and "counterparty_inn" in matched)]
    # Чего не смог разобрать сам прогон — его собственный перечень.
    for l in links:
        if not l.recheck_applicable:
            continue
        for unknown in (l.recheck.get("unknowns") or []):
            if not isinstance(unknown, dict):
                continue
            name = str(unknown.get("field") or "")
            if not name or name in compared or any(x["field"] == name for x in out):
                continue
            out.append({"field": name,
                        "label": str(unknown.get("label") or FIELD_LABEL.get(name, name)),
                        "reason": str(unknown.get("reason") or "прогон не смог сравнить")})
    return out + always


def _link_proven(link: Link) -> bool:
    """Есть ли у связи хотя бы одно поле источника, сошедшееся с текущей карточкой."""
    return link.exists and any(c["result"] == "match" for c in comparisons(link))


def _link_differs(link: Link) -> bool:
    """Расходится ли связь сейчас.

    Для доступной карточки решает ЖИВОЕ сравнение, а не прежний вердикт:
    исправленный номер расхождением быть перестаёт (и уходит в устаревание),
    испорченный — становится. Прежний вердикт остаётся единственным источником
    только там, где сравнить нечем: карточка недоступна.
    """
    if link.exists:
        return bool(link.differences)
    return link.verification == "differences"


def _link_verification(link: Link) -> str:
    """Ось проверки одной связи с поправкой на живое сравнение.

    Прежний вердикт «расхождение» снимается, когда расхождения больше нет, но
    проверенной связь от этого не становится: остаётся то, что реально доказано.
    """
    if link.stale:
        return "stale"
    if link.exists:
        if link.differences:
            return "differences"
        if link.recheck_applicable and link.recheck and _link_proven(link):
            # Новый разбор мог подтвердить реквизиты ОСНОВНОГО договора из
            # соглашения. Его прежнее «не проверено» относится к прошлому
            # кругу; теперь доказан узкий состав полей, не весь документ.
            return "partial"
        if link.verification == "differences":
            return "partial" if _link_proven(link) else "not_checked"
    return link.verification


def _links_state(links: list[Link]) -> str:
    """Состояние карточки по её связям. Хуже — важнее."""
    if not links:
        return "no_source"
    if any(_link_differs(l) for l in links):
        return "differences"
    if any(l.stale for l in links):
        return "stale"
    # Карточка недоступна (удалена) — подтвердить сверку нечем.
    if any(not l.exists for l in links):
        return "needs_check"
    if any(_link_verification(l) == "not_checked"
           or l.status in ("candidate", "unmatched") for l in links):
        return "needs_check"
    # Неоднозначная привязка и доказанное противоречие стороны зелёного не дают.
    # Подсказка о виде договора — даёт: одна площадка законно заведена двумя
    # карточками (аренда и получение электроэнергии) с одним номером и датой.
    if any(l.ambiguous for l in links):
        return "needs_check"
    if not all(_link_proven(l) for l in links):
        return "needs_check"
    return "matched_checked"


def _links_of(slice_: Slice, entity_type: str, entity_id: str) -> list[tuple[Record, Link]]:
    return [(r, l) for r in slice_.records for l in r.links
            if l.entity_type == entity_type and l.entity_id == entity_id]


def _verification_block(links: list[Link], run: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ось проверки: состояние, что сверено с источником, что только снято, что нет."""
    snapshot: list[str] = []
    for l in links:
        for key in l.checked_values:
            if key not in snapshot:
                snapshot.append(key)
    compared: list[dict[str, Any]] = []
    for l in links:
        compared.extend(comparisons(l))
    # Состояние — худшее из связей, с той же поправкой на живое сравнение, что и
    # в самих связях: иначе сводка противоречила бы своему списку расхождений.
    states = [_link_verification(l) for l in links]
    status = "stale" if "stale" in states else next(
        (s for s in VERIFICATION_ORDER if s in states), "not_checked")
    return {
        "status": status,
        "label": VERIFICATION_LABEL.get(status, VERIFICATION_LABEL["not_checked"]),
        "compared_fields": compared,
        # Сверено с источником — только то, что сошлось с его собственным значением.
        "checked_fields": sorted({f["field"] for f in compared if f["result"] == "match"}),
        "snapshot_fields": sorted(snapshot),
        "snapshot_basis": ("снимок карточки на момент сверки — основание устаревания, "
                           "а не сверка с источником"),
        "unchecked_fields": _unchecked_fields(links),
        "recheck": _recheck_block(links, run),
    }


def _recheck_block(links: list[Link], run: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Независимая повторная сверка: её вопросы и то, принято ли её свидетельство.

    Вердикт прогона здесь показывается, но отметку не ставит: состояние считается
    пересчётом (`comparisons`). Непринятый прогон (другая редакция файла) честно
    говорит об этом вместо того, чтобы молча исчезнуть.
    """
    per_link = [l for l in links if l.recheck]
    if not per_link and not run:
        return None
    questions: list[dict[str, Any]] = []
    for l in per_link:
        for q in l.open_questions:
            item = {"code": str(q.get("code") or ""),
                    "label": str(q.get("label") or ""),
                    "reason": str(q.get("reason") or ""),
                    "blocking": _blocking_question(q)}
            if item not in questions:
                questions.append(item)
    rejected = [l.recheck_reject_reason for l in per_link
                if not l.recheck_applicable and l.recheck_reject_reason]
    return {
        "schema_version": (run or {}).get("schema_version"),
        "run_id": str((run or {}).get("run_id") or ""),
        "checked_at": str((run or {}).get("checked_at") or "") or None,
        "overall": str((run or {}).get("overall") or "") or None,
        "applicable": not rejected,
        "not_applicable_reason": rejected[0] if rejected else None,
        "open_questions": questions,
        "blocking_questions": [q for q in questions if q["blocking"]],
        # Что записал о полях сам прогон — для прозрачности, не для отметки.
        "claims": [{"field": f, "result": r} for f, r in
                   sorted({(c["field"], c["claimed"]) for l in per_link
                           for c in comparisons(l) if c["claimed"]})],
        "candidates_in_registry": (run or {}).get("candidates_in_registry"),
    }


def _freshness_block(links: list[Link], *, hashes: bool = True,
                     rechecked_at: str | None = None) -> dict[str, Any]:
    """Ось свежести: считается пересчётом хеша сверенных значений из текущей карточки."""
    stale = [l for l in links if l.stale]
    snapshots = sorted({l.snapshot_at for l in links if l.snapshot_at})
    return {
        "stale": bool(stale),
        "stale_records": len(stale),
        # Время ПРЕЖНЕГО применения, как его записало оно само; своего времени
        # проверки сервер не выдумывает — он её не выполнял.
        "checked_at": snapshots[-1] if snapshots else None,
        "checked_at_basis": "snapshot_at применённой сверки" if snapshots else None,
        # Время НЕЗАВИСИМОЙ повторной сверки — отдельным полем: это другое
        # событие, и подменять им дату прежнего применения нельзя.
        "rechecked_at": rechecked_at,
        "baseline": ("повторная сверка"
                     if any(l.recheck_applicable and l.recheck.get("current_hash")
                            for l in links)
                     else "прежнее применение" if snapshots else None),
        "checked_hash": next((l.checked_hash for l in links if l.checked_hash), "") if hashes else "",
        "current_hash": next((l.current_hash for l in links if l.current_hash), "") if hashes else "",
    }


def _source_block(pairs: list[tuple[Record, Link]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r, _ in pairs:
        item = {"record_id": r.id, "file": r.source_file, "sheet": r.source_sheet,
                "rows": r.source_rows, "period": r.source_period,
                "as_of": r.source_as_of, "batch_id": r.batch_id,
                "counterparty": r.counterparty_name, "contract": r.contract_label,
                "status": r.status}
        if item not in out:
            out.append(item)
    return out


def _state_note(state: str, links: list[Link]) -> str:
    """Пояснение состояния с конкретной причиной: что именно нужно уточнить.

    Менеджеру нужен не только цвет: «требует сверки» без причины отправляет его
    искать её на другом экране. Поэтому к общему тексту состояния добавляются
    расходящиеся реквизиты и открытые вопросы прогона, которые сняли отметку.
    """
    note = ENTITY_STATE_NOTE[state]
    fields = []
    for l in links:
        for d in l.differences:
            if d["label"] not in fields:
                fields.append(d["label"])
    if fields:
        note += " Расходятся: " + ", ".join(fields) + "."
    reasons = []
    for l in links:
        for q in l.open_questions:
            if not _blocking_question(q):
                continue
            label = str(q.get("label") or q.get("code") or "").strip()
            reason = str(q.get("reason") or "").strip()
            text = f"{label} — {reason}" if label and reason else label or reason
            if text and text not in reasons:
                reasons.append(text)
    if any(l.relation in AMBIGUOUS_RELATIONS for l in links):
        text = "Строка источника легла на несколько карточек — связь неоднозначна"
        if text not in reasons:
            reasons.append(text)
    if reasons:
        note += " Что уточнить: " + "; ".join(reasons) + "."
    return note


def _state_payload(entity_type: str, entity_id: str, state: str, scope: str,
                   pairs: list[tuple[Record, Link]], *, exists: bool,
                   aggregate: dict[str, Any] | None) -> dict[str, Any]:
    links = [l for _, l in pairs]
    # Самый свежий конверт повторной сверки среди строк карточки: его время и
    # вопросы показываются отдельно от прежнего применения.
    runs = sorted((r.recheck for r, _ in pairs if r.recheck),
                  key=lambda x: str(x.get("checked_at") or ""))
    run = runs[-1] if runs else None
    by_status: dict[str, int] = {}
    for l in links:
        by_status[l.status] = by_status.get(l.status, 0) + 1
    differences: list[dict[str, Any]] = []
    for l in links:
        for d in l.differences:
            if d not in differences:
                differences.append(d)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "exists": exists,
        "scope": scope,
        "scope_label": SCOPE_LABEL[scope],
        "state": state,
        "state_label": ENTITY_STATE_LABEL[state],
        # Пояснение называет, ЧТО уточнить: общего текста состояния менеджеру мало,
        # а отдельного места для причины в интерфейсе нет — он показывает это поле.
        "state_note": _state_note(state, links),
        # Карточка целиком не сверялась НИКОГДА: сверка охватывает только состав
        # полей выше. Отметка договора не переносится на контрагента и площадку.
        "entity_verified": False,
        "matching": {
            "by_status": by_status,
            "labels": {k: LINK_STATUS_LABEL.get(k, k) for k in by_status},
        },
        "verification": _verification_block(links, run),
        # Хеши сверенных значений относятся к одной карточке: в сводке по договорам
        # общего хеша нет, и выдавать чей-то один как «хеш контрагента» нельзя.
        "freshness": _freshness_block(
            links, hashes=scope == "self",
            rechecked_at=str((run or {}).get("checked_at") or "") or None),
        "differences": differences,
        "sources": _source_block(pairs),
        "records": len({r.id for r, _ in pairs}),
        "aggregate": aggregate,
        "disclaimer": DISCLAIMER,
    }


def contract_summary(slice_: Slice, contract_id: str, *, exists: bool = True) -> dict[str, Any]:
    """Отметка договора: три оси и состав сверенного — для его строки и карточки."""
    pairs = _links_of(slice_, "contract", contract_id)
    state = _links_state([l for _, l in pairs])
    if not exists:
        # Чужая, удалённая или недоступная карточка отвечает так же, как карточка
        # без сведений: отличать их наружу нельзя — это подсказка о чужих данных.
        state, pairs = "no_source", []
    return _state_payload("contract", contract_id, state, "self", pairs,
                          exists=exists, aggregate=None)


def aggregate_summary(slice_: Slice, entity_type: str, entity_id: str,
                      contract_ids: list[str], *, exists: bool = True) -> dict[str, Any]:
    """Отметка контрагента или площадки — ТОЛЬКО сводка по их договорам.

    Зелёная отметка договора на контрагента и площадку не переносится: у них своя
    область (`scope`), и состояние «договоры сверены» ставится лишь когда сверены
    ВСЕ доступные договоры. Один договор без сведений превращает сводку в
    «требует сверки», а не в «сверено».
    """
    scope = ("contracts_of_counterparty" if entity_type == "counterparty"
             else "contracts_of_location")
    rows: list[dict[str, Any]] = []
    pairs: list[tuple[Record, Link]] = []
    by_state: dict[str, int] = {}
    for cid in contract_ids:
        cpairs = _links_of(slice_, "contract", cid)
        cstate = _links_state([l for _, l in cpairs])
        pairs.extend(cpairs)
        by_state[cstate] = by_state.get(cstate, 0) + 1
        card = slice_.contracts.get(cid)
        rows.append({
            "id": cid,
            "number": card.number if card else "",
            "date": card.date if card else "",
            "type_code": card.type_code if card else "",
            "state": cstate,
            "state_label": ENTITY_STATE_LABEL[cstate],
            "records": len({r.id for r, _ in cpairs}),
        })
    states = [r["state"] for r in rows]
    if not states:
        state = "no_source"
    elif "differences" in states:
        state = "differences"
    elif "stale" in states:
        state = "stale"
    elif all(s == "matched_checked" for s in states):
        state = "contracts_checked"
    elif all(s == "no_source" for s in states):
        state = "no_source"
    else:
        state = "needs_check"
    if not exists:
        state, pairs, rows, by_state = "no_source", [], [], {}
    with_source = sum(1 for r in rows if r["records"])
    aggregate = {
        "contracts_total": len(rows),
        "with_source": with_source,
        "without_source": len(rows) - with_source,
        "by_state": by_state,
        "contracts": sorted(rows, key=lambda r: (STATE_ORDER.index(r["state"]),
                                                 r["number"], r["date"])),
    }
    payload = _state_payload(entity_type, entity_id, state, scope, pairs,
                             exists=exists, aggregate=aggregate)
    return payload


async def load_entity_contracts(
    db: AsyncSession, company_id: uuid.UUID, entity_type: str, entity_ids: list[str],
    organization_id: str | None = None,
) -> tuple[dict[str, list[str]], dict[str, Contract]]:
    """Договоры запрошенных карточек — двумя запросами на весь batch, не по карточке.

    Отметку в списке нужно получить для сотни строк сразу, и запрос на строку
    (`N+1`) превратил бы открытие списка в сотню обходов. Здесь на любой размер
    партии ровно два запроса: существование карточек и их договоры.

    Площадка проверяется выборкой `ServiceLocation` — её автоматически сужает
    скоуп объектов участника (`scope.install_orm_scope`), поэтому чужая площадка
    отвечает так же, как несуществующая.
    """
    found: dict[str, list[str]] = {}
    cards: dict[str, Contract] = {}
    if not entity_ids:
        return found, cards
    acl = contract_acl(organization_id)

    if entity_type == "location":
        live = (await db.execute(select(ServiceLocation.id).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id.in_(entity_ids),
            *scope_location_conds(ServiceLocation.id)))).scalars().all()
        found = {str(x): [] for x in live}
        if found:
            rows = (await db.execute(
                select(ContractLocation.location_id, Contract)
                .join(Contract, Contract.id == ContractLocation.contract_id)
                .where(ContractLocation.company_id == company_id,
                       ContractLocation.location_id.in_(list(found)),
                       Contract.company_id == company_id, *acl)
            )).all()
            for loc_id, contract in rows:
                cards[str(contract.id)] = contract
                bucket = found.setdefault(str(loc_id), [])
                if str(contract.id) not in bucket:
                    bucket.append(str(contract.id))
        return found, cards

    valid = [uuid.UUID(x) for x in entity_ids if _is_uuid(x)]
    if not valid:
        return found, cards

    if entity_type == "counterparty":
        live = (await db.execute(select(Counterparty.id).where(
            Counterparty.company_id == company_id,
            Counterparty.id.in_(valid)))).scalars().all()
        found = {str(x): [] for x in live}
        if found:
            for contract in (await db.execute(select(Contract).where(
                    Contract.company_id == company_id,
                    Contract.counterparty_id.in_([uuid.UUID(x) for x in found]),
                    *acl))).scalars().all():
                cards[str(contract.id)] = contract
                found.setdefault(str(contract.counterparty_id), []).append(str(contract.id))
        return found, cards

    for contract in (await db.execute(select(Contract).where(
            Contract.company_id == company_id, Contract.id.in_(valid),
            *acl))).scalars().all():
        cards[str(contract.id)] = contract
        found[str(contract.id)] = [str(contract.id)]
    return found, cards


async def entity_summaries(
    db: AsyncSession, slice_: Slice, company_id: uuid.UUID,
    entity_type: str, entity_ids: list[str], organization_id: str | None = None,
) -> list[dict[str, Any]]:
    """Сводки сопряжения на весь список карточек: ответ есть у КАЖДОГО запрошенного id.

    Отсутствующий ключ в ответе список прочитал бы как «ещё грузится», и строка
    осталась бы без отметки. Поэтому недоступная или неизвестная карточка получает
    то же «нет данных для сравнения», что и карточка без строк выгрузки: разницу
    наружу не выдаём.
    """
    found, cards = await load_entity_contracts(db, company_id, entity_type,
                                               entity_ids, organization_id)
    # Договоры карточек докладываются в срез: `contract_brief` и номера в сводке
    # берутся из него же, вторым проходом по базе ходить не за чем.
    for cid, contract in cards.items():
        slice_.contracts.setdefault(cid, contract)
    out: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        exists = entity_id in found
        if entity_type == "contract":
            out.append(contract_summary(slice_, entity_id, exists=exists))
        else:
            out.append(aggregate_summary(slice_, entity_type, entity_id,
                                         found.get(entity_id, []), exists=exists))
    return out
