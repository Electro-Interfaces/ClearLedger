"""Три ответа Ядра по заявке звонящего — то, чего в сводке клиента не было.

ЗАЧЕМ. Оператор КЦ отвечает звонящему на десять вопросов разговора. Семь из них
закрывает Поддержка в своей карточке (`scripts/lib/operator-answers.js`), но её
окно в поставке узла может быть выключено, и тогда у оператора остаётся только
сводка Ядра — а она отвечала подсказкой «номер — заголовок (статус)» и молчала
о том, **что сделано**, **применено ли это** и **что можно сказать клиенту**
(аудит 21.10.2026, C-09 и A-16 со стороны Ядра).

ГРАНИЦА. Ядро заявок не ведёт: их состояние, ответственный, срок и эскалация
живут в Поддержке. Своей у Ядра является ровно одна часть ответа — работа
«Трека», которую завёл процесс этой заявки (`eco_approval_requests`), и
состояние доставки её исхода обратно в процесс. Поэтому отвечаем мы только за
неё, и каждый ответ называет свой источник. Там, где Ядру сказать нечего, стоит
подтверждённое отсутствие (`empty`) с причиной, а не выдуманная фраза: неверный
ответ оператора хуже отсутствующего — по нему звонящему дают обещание.

СЛОВАРЬ. Состояния (`available` / `empty` / `partial` / `unavailable`) и форма
факта (`text`, `state`, `source`, `asOf`, `reason`, `value`) — те же, что у
карточки оператора в Поддержке, чтобы обе стороны подписывались одними словами
и потребитель не разбирал два словаря. Слова состояния доставки взяты из её же
`SYNC_WORD`.

Девятый вопрос («что допустимо сообщить клиенту») отдаётся **признаком**, а не
текстом: фразу строит та сторона, что говорит с клиентом, — у неё свой тон, свой
язык и своя оценка того, что уместно.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.process_work import DONE_OUTCOMES, items_by_process

SOURCE = "core.track"

# Исход работы словом — так же, как его называет «Трек» человеку.
OUTCOME_WORD = {
    "approved": "согласовано", "done": "выполнено",
    "rejected": "отказано", "cancelled": "отменено",
}
# Состояние доставки исхода в процесс. Словарь общий с Поддержкой.
SYNC_WORD = {
    "applied": "применено",
    "pending": "ещё доставляется",
    "accepted": "принято, применение не подтверждено",
    "error": "не доставлено, ошибка обмена",
    "none": "исход фиксируется, процесс его не ждёт",
}
# Признак для девятого вопроса, от самого осторожного к самому спокойному:
# пока хоть одна работа не доведена, сказать «принято» нельзя.
TO_CLIENT_ORDER = ("work_delivery_failed", "work_awaiting_decision",
                   "work_awaiting_delivery", "work_rejected", "work_accepted")


def fact(text: str | None, *, state: str = "available", source: str = SOURCE,
         as_of: str | None = None, reason: str | None = None,
         value: Any = None, code: str | None = None) -> dict[str, Any]:
    """Один ответ. Непустая строка ответом сама по себе не считается: состояние
    и причина едут рядом с текстом, иначе «нет данных» читается как «данных нет»."""
    out: dict[str, Any] = {"text": text, "state": state, "source": source,
                           "asOf": as_of, "reason": reason, "value": value}
    if code is not None:
        out["code"] = code
    return out


def _subject(item: dict[str, Any]) -> str:
    """Как назвать предмет работы в одной строке ответа."""
    name = item.get("number") or item.get("title") or "без номера"
    return f"{item.get('kind_name') or item.get('kind')}: {name}"


def _answers(items: list[dict[str, Any]], observed_at: str) -> dict[str, Any]:
    if not items:
        return {
            "done": fact("Работ «Трека» по этой заявке Ядро не заводило",
                         state="empty", reason="no_core_work", as_of=observed_at,
                         value={"items": 0}),
            "delivery": fact("Работ Ядра по заявке нет — применять и доставлять нечего",
                             state="empty", reason="no_core_work", as_of=observed_at,
                             value={"total": 0, "awaited": 0}),
            "toClient": fact(None, state="empty", reason="no_core_work",
                             as_of=observed_at, code="no_core_work",
                             value={"items": 0}),
        }

    lost = [i for i in items if i.get("subject") is None]
    decided = [i for i in items if i.get("outcome")]
    done_ok = [i for i in decided if i["outcome"] in DONE_OUTCOMES]
    refused = [i for i in decided if i["outcome"] not in DONE_OUTCOMES]
    open_work = [i for i in items if not i.get("outcome")]

    # 4. Что фактически уже сделано и с каким результатом.
    parts = []
    for item in items:
        line = _subject(item)
        if item.get("state"):
            line += f" — {item['state']}"
        if item.get("outcome"):
            line += f", {OUTCOME_WORD.get(item['outcome'], item['outcome'])}"
        parts.append(line)
    done_at = max((i["decided_at"] or i["requested_at"] or "" for i in items), default="")
    done = fact("; ".join(parts),
                state="partial" if lost else "available",
                as_of=done_at or observed_at,
                reason="work_subject_missing" if lost else None,
                value={"items": len(items), "decided": len(decided),
                       "done": len(done_ok), "refused": len(refused),
                       "open": len(open_work)})

    # 8. Применено действие или ещё доставляется.
    awaited = [i for i in items if i["delivery"]["awaited"]]
    sync = [i["delivery"]["state"] for i in awaited]
    if not awaited:
        delivery = fact("Процесс исхода этих работ не ждёт — применять нечего",
                        state="empty", reason="outcome_not_awaited",
                        as_of=observed_at, value={"total": len(items), "awaited": 0})
    else:
        broken = [i for i in awaited if i["delivery"]["state"] == "error"]
        delivery = fact(
            "; ".join(f"{_subject(i)} — {SYNC_WORD.get(i['delivery']['state'], i['delivery']['state'])}"
                      for i in awaited),
            state="unavailable" if len(broken) == len(awaited) else
                  "partial" if broken else "available",
            reason="core_delivery_failed" if len(broken) == len(awaited) else
                   "core_delivery_partial" if broken else None,
            as_of=max((i["delivery"]["delivered_at"] or i["decided_at"] or "" for i in awaited),
                      default="") or observed_at,
            value={"total": len(items), "awaited": len(awaited), "failed": len(broken),
                   "applied": sync.count("applied"), "pending": sync.count("pending"),
                   "accepted": sync.count("accepted")})

    # 9. Что допустимо сообщить клиенту — признаком, не фразой.
    codes = set()
    for item in items:
        state = item["delivery"]["state"]
        if state == "error":
            codes.add("work_delivery_failed")
        elif state == "accepted":
            codes.add("work_awaiting_decision")
        elif state == "pending":
            codes.add("work_awaiting_delivery")
        elif item.get("outcome") in DONE_OUTCOMES:
            codes.add("work_accepted")
        elif item.get("outcome"):
            codes.add("work_rejected")
        else:
            # Исхода нет, и процесс его не ждёт: работа идёт, обещать нечего.
            codes.add("work_awaiting_decision")
    code = next((c for c in TO_CLIENT_ORDER if c in codes), "work_awaiting_decision")
    to_client = fact(None, code=code,
                     state="unavailable" if code == "work_delivery_failed" else "available",
                     reason="core_delivery_failed" if code == "work_delivery_failed" else None,
                     as_of=observed_at,
                     value={"codes": sorted(codes), "items": len(items),
                            "done": len(done_ok), "refused": len(refused),
                            "open": len(open_work)})

    return {"done": done, "delivery": delivery, "toClient": to_client}


async def attach(db: AsyncSession, company_id: uuid.UUID,
                 tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Положить в каждую заявку сводки три ответа Ядра.

    Один запрос на всю сводку: заявок в ней не больше двадцати, и ходить за
    каждой отдельно значило бы двадцать раз обойти одну и ту же таблицу.
    """
    if not tickets:
        return tickets
    observed_at = datetime.now(timezone.utc).isoformat()
    by_process = await items_by_process(
        db, company_id, [t.get("ref") for t in tickets if t.get("ref")])
    for ticket in tickets:
        ref = str(ticket.get("ref") or "")[:64]
        ticket["answers"] = _answers(by_process.get(ref, []), observed_at)
    return tickets
