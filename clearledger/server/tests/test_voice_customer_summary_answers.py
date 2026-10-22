"""Сводка клиента отвечает на три вопроса разговора и честна о молчании источника.

Кластер R11 аудита 21.10.2026 (остатки C-09 и A-16 со стороны Ядра). Оператор КЦ
отвечает звонящему на десять вопросов; три из них сводка Ядра не закрывала вовсе
и отвечала только вложенным окном Поддержки, которого в поставке узла может не
быть:

  4. что фактически уже сделано и с каким результатом;
  8. применено ли действие или оно только ожидает доставки/подтверждения;
  9. что допустимо сообщить клиенту.

Отдельно: поведение при молчании источника. Выключенное приложение, незаполненная
карта компаний, таймаут и ответ не того вида сворачивались в одно слово
`unavailable`, и «источник не ответил» выглядело как «данных нет».

Ловим:
  * ответов нет вовсе либо они не названы источником и свежестью;
  * доставленный исход, недоставленный и потерянный неразличимы;
  * подтверждённое отсутствие работ путается с ошибкой чтения;
  * признак «что сказать клиенту» подменён свободным текстом;
  * прежние поля сводки (`tickets`, `ticketAvailability`) изменились — узел
    прежней сборки выкатывается позже Ядра и не должен заметить разницы.
"""
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from sqlalchemy import select

from app.models import App, ApprovalRequest, Task
from app.services import app_registry
from tests.test_voice_core import _company, _key, _seed_caller, _voice
from tests.test_voice_support_context import support_map
from tests.test_voice_tokens import sso_key  # noqa: F401 — fixture ключа RS256

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Прежние поля заявки в сводке: узел читает ровно их (contact-hub
# node/src/adapters/core.ts, summaryOf).
LEGACY_TICKET_FIELDS = {"ref", "number", "title", "status", "priority", "category",
                        "objectRef", "slaDeadline"}
ANSWER_KEYS = ("done", "delivery", "toClient")


class _Support:
    """Поддельная Поддержка: отвечает тем, что положили в `state`."""

    def __init__(self):
        self.state = {"status": 200, "body": {}, "delay": 0.0}
        self.seen = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.seen.append((self.path, self.headers.get("Authorization"), body))
                if stub.state["delay"]:
                    import time
                    time.sleep(stub.state["delay"])
                raw = json.dumps(stub.state["body"]).encode()
                self.send_response(stub.state["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"


def _evidence(name, payload):
    """Снимок ответа в доказательства — когда прогон запущен за ними.

    Тот же ответ, по которому проверка выносит суждение, читает потом узел в
    положительном контроле: иначе контроль проверял бы выдуманный пример.
    """
    import os
    import pathlib

    target = os.environ.get("FIX_R11_EVIDENCE")
    if not target:
        return
    path = pathlib.Path(target) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _ticket(ref, number, **extra):
    return {"ref": ref, "number": number, "title": f"Заявка {number}",
            "status": "open", **extra}


async def _errand(db, company_id, process_id, title, **fields):
    """Поручение «Трека», заведённое процессом заявки, и просьба процесса."""
    task = Task(company_id=company_id, title=title, status=fields.pop("status", "open"))
    db.add(task)
    await db.flush()
    row = ApprovalRequest(company_id=company_id, request_id=f"r-{uuid.uuid4().hex[:12]}",
                          process_id=process_id, kind="errand", task_id=task.id,
                          on_approved=fields.pop("on_approved", "выполнено"), **fields)
    db.add(row)
    await db.commit()
    return task, row


async def test_summary_answers_done_delivery_and_what_to_tell_the_client(client, db, sso_key):
    """Три недостающих ответа есть, и каждое состояние доставки названо своим словом."""
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    await _seed_caller(db, own, phone)
    now = datetime.now(timezone.utc)
    refs = {name: str(uuid.uuid4()) for name in
            ("open", "pending", "applied", "failed", "bare")}

    # Работа заведена, решения ещё нет.
    await _errand(db, own.id, refs["open"], "Выехать на объект")
    # Решение есть, исход едет в процесс.
    await _errand(db, own.id, refs["pending"], "Заменить коннектор",
                  outcome="done", decided_at=now - timedelta(minutes=5), attempts=1)
    # Исход доставлен и применён.
    await _errand(db, own.id, refs["applied"], "Перезапустить станцию", status="done",
                  outcome="done", decided_at=now - timedelta(hours=2),
                  delivered_at=now - timedelta(hours=2), attempts=1)
    # Доставка не удалась.
    await _errand(db, own.id, refs["failed"], "Согласовать выезд подрядчика",
                  outcome="done", decided_at=now - timedelta(hours=3),
                  attempts=12, last_error="HTTPError: сосед не ответил")
    # Пятая заявка без работ Ядра — подтверждённое отсутствие.

    with _Support() as support:
        support.state["body"] = {"availability": "available", "tickets": [
            _ticket(refs["open"], "TS-1"), _ticket(refs["pending"], "TS-2"),
            _ticket(refs["applied"], "TS-3"), _ticket(refs["failed"], "TS-4"),
            _ticket(refs["bare"], "TS-5"),
        ]}
        async with support_map(db, own.id) as (app, support_id):
            app.config = {**(app.config or {}), "internalUrl": support.url}
            await db.commit()
            r = await client.post("/api/eco/ezs/customer-summary",
                                  json={"phone": phone, "limit": 10},
                                  headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200, r.text
    data = r.json()
    _evidence("summary-answers.json", data)
    assert data["ticketAvailability"] == "available"
    by_number = {t["number"]: t for t in data["tickets"]}
    assert set(by_number) == {"TS-1", "TS-2", "TS-3", "TS-4", "TS-5"}

    # Каждая заявка отвечает на все три вопроса, и каждый ответ назван.
    for number, ticket in by_number.items():
        answers = ticket.get("answers")
        assert answers, f"{number}: сводка не отвечает на вопросы разговора"
        for field in ANSWER_KEYS:
            answer = answers.get(field)
            assert answer, f"{number}: нет ответа «{field}»"
            assert answer["state"] in ("available", "empty", "partial", "unavailable"), answer
            assert answer["source"], f"{number}/{field}: ответ без источника"
            assert answer["asOf"], f"{number}/{field}: ответ без свежести"
        assert answers["toClient"]["code"], f"{number}: нет признака для клиента"
        assert answers["toClient"]["text"] is None, "девятый ответ — признак, не фраза"

    # 4. Что сделано и с каким результатом.
    done = by_number["TS-3"]["answers"]["done"]
    assert done["state"] == "available"
    assert "Поручение" in done["text"] and "Выполнено" in done["text"]
    assert done["value"] == {"items": 1, "decided": 1, "done": 1, "refused": 0, "open": 0}
    assert by_number["TS-1"]["answers"]["done"]["value"]["open"] == 1

    # 8. Применено или ещё доставляется — четыре состояния, четыре слова.
    expect = {"TS-1": ("accepted", "принято, применение не подтверждено", "available"),
              "TS-2": ("pending", "ещё доставляется", "available"),
              "TS-3": ("applied", "применено", "available"),
              "TS-4": ("error", "не доставлено, ошибка обмена", "unavailable")}
    for number, (count_key, word, state) in expect.items():
        delivery = by_number[number]["answers"]["delivery"]
        assert delivery["state"] == state, (number, delivery)
        assert word in delivery["text"], (number, delivery["text"])
        if count_key != "error":
            assert delivery["value"][count_key] == 1, (number, delivery["value"])
        else:
            assert delivery["value"]["failed"] == 1, delivery["value"]
            assert delivery["reason"] == "core_delivery_failed"
    assert "сосед не ответил" not in r.text, "текст ошибки доставки наружу не уходит"

    # 9. Что допустимо сообщить клиенту — признаком.
    assert {n: t["answers"]["toClient"]["code"] for n, t in by_number.items()} == {
        "TS-1": "work_awaiting_decision", "TS-2": "work_awaiting_delivery",
        "TS-3": "work_accepted", "TS-4": "work_delivery_failed",
        "TS-5": "no_core_work"}
    assert by_number["TS-4"]["answers"]["toClient"]["state"] == "unavailable"

    # Подтверждённое отсутствие работ — не ошибка чтения.
    bare = by_number["TS-5"]["answers"]
    assert bare["done"]["state"] == "empty" and bare["done"]["reason"] == "no_core_work"
    assert bare["delivery"]["state"] == "empty"
    assert bare["toClient"]["state"] == "empty"


async def test_summary_tells_silence_from_error_and_keeps_legacy_availability(client, db, sso_key):
    """Молчание, ошибка и подтверждённое отсутствие — разные состояния источника.

    Второе утверждение проверки — положительный контроль совместимости: прежнее
    поле `ticketAvailability` в каждом случае остаётся тем же, что и до правки.
    """
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    await _seed_caller(db, own, phone)
    ref = str(uuid.uuid4())

    async def summary():
        r = await client.post("/api/eco/ezs/customer-summary",
                              json={"phone": phone, "limit": 10},
                              headers={"X-Cloud-API-Key": key})
        assert r.status_code == 200, r.text
        return r.json()

    seen = []
    with _Support() as support:
        async with support_map(db, own.id) as (app, _support_id):
            app.config = {**(app.config or {}), "internalUrl": support.url}
            await db.commit()

            cases = [
                ("живой источник с заявками", 200,
                 {"availability": "available", "tickets": [_ticket(ref, "TS-9")]},
                 0.0, "available", None, "available"),
                ("живой источник без открытых заявок", 200,
                 {"availability": "available", "tickets": []},
                 0.0, "empty", "no_open_tickets", "available"),
                ("часть строк не прошла проверку", 200,
                 {"availability": "available",
                  "tickets": [_ticket(ref, "TS-9"), {"bad": "data"}]},
                 0.0, "partial", "source_rows_dropped", "unavailable"),
                ("источник вернул код ошибки", 503, {}, 0.0,
                 "unavailable", "source_rejected", "unavailable"),
                ("источник ответил не тем", 200, [], 0.0,
                 "unavailable", "source_unexpected_answer", "unavailable"),
                ("источник не ответил вовремя", 200,
                 {"availability": "available", "tickets": []}, 1.0,
                 "unavailable", "source_timeout", "unavailable"),
            ]
            for name, status, body, delay, state, reason, availability in cases:
                support.state.update(status=status, body=body, delay=delay)
                data = await summary()
                _evidence(f"summary-source-{state}-{reason or 'ok'}.json",
                          {k: data[k] for k in
                           ("tickets", "ticketAvailability", "ticketSource") if k in data})
                source = data.get("ticketSource")
                assert source, f"{name}: состояние источника в сводке не названо"
                assert (source["state"], source["reason"]) == (state, reason), (name, source)
                assert source["source"] == "support.tickets" and source["asOf"], (name, source)
                assert data["ticketAvailability"] == availability, name
                assert data["sessions"], f"{name}: отказ источника не стирает данные Ядра"
                seen.append(name)
            assert support.state["status"] == 200
            # Код ответа источника назван: по нему видно, отказ это или молчание.
            support.state.update(status=503, body={}, delay=0.0)
            assert (await summary())["ticketSource"]["status"] == 503

        # Карта компаний не заполнена — спросить нечем, но это не молчание
        # источника: причина названа отдельно.
        from app.models import AppCompanyLink

        for link in (await db.execute(select(AppCompanyLink).join(
                App, App.id == AppCompanyLink.app_id).where(
                App.code == "support", AppCompanyLink.company_id == own.id))).scalars().all():
            await db.delete(link)
        await db.commit()
        data = await summary()
        assert data["ticketSource"]["state"] == "unavailable"
        assert data["ticketSource"]["reason"] == "support_not_linked"
        assert data["ticketAvailability"] == "unavailable"

    # «Поддержка» компании не подключена — заявок не бывает: подтверждённое
    # отсутствие, а не недоступность.
    await app_registry.seed_apps(db)
    app_row = (await db.execute(select(App).where(App.code == "support"))).scalar_one()
    await app_registry.set_app(db, own.id, app_row.id, False)
    data = await summary()
    assert data["ticketSource"]["state"] == "empty"
    assert data["ticketSource"]["reason"] == "support_not_enabled"
    assert data["ticketAvailability"] == "unavailable", "прежнее поле не меняется"
    assert len(seen) == 6


async def test_legacy_shape_and_one_assembly_for_core_work(client, db, sso_key):
    """Положительные контроли: узел работает на прежних полях, Поддержка — на своей ручке.

    Правка не должна запретить ничего из того, что шло и раньше: узел читает ту
    же сводку теми же полями, Поддержка теми же правами читает работу процесса,
    а служебный токен Ядра по-прежнему называет арендатора (исправление R8).
    """
    own = await _company(db, "gig")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    await _seed_caller(db, own, phone)
    ref = str(uuid.uuid4())
    task, request = await _errand(db, own.id, ref, "Проверить питание",
                                  outcome="done", delivered_at=datetime.now(timezone.utc))

    with _Support() as support:
        support.state["body"] = {"availability": "available",
                                 "tickets": [_ticket(ref, "TS-7", priority="high",
                                                     category="power",
                                                     slaDeadline="2026-10-22T10:00:00+00:00")]}
        async with support_map(db, own.id) as (app, support_id):
            app.config = {**(app.config or {}), "internalUrl": support.url}
            await db.commit()
            r = await client.post("/api/eco/ezs/customer-summary",
                                  json={"phone": phone, "limit": 10},
                                  headers={"X-Cloud-API-Key": key})
            assert r.status_code == 200, r.text
            ticket = r.json()["tickets"][0]
            # Прежние поля на месте и не переименованы; новое — только `answers`.
            assert LEGACY_TICKET_FIELDS <= set(ticket)
            assert set(ticket) - LEGACY_TICKET_FIELDS == {"answers"}
            assert ticket["priority"] == "high" and ticket["category"] == "power"
            assert ticket["slaDeadline"] == "2026-10-22T10:00:00+00:00"

            # Служебный токен по-прежнему называет арендатора (R8).
            _path, header, _body = support.seen[-1]
            claims = jwt.decode(header.removeprefix("Bearer "), sso_key,
                                algorithms=["RS256"], audience="support")
            assert claims["cid"] == support_id and claims["svc"] == "voice.context"

    # Та же работа, прочитанная Поддержкой своей ручкой, — один сборщик: строка
    # витрины совпадает с тем, из чего собран ответ оператору.
    app_key = await _key(db, own.id, [])
    r = await client.get(f"/api/eco/process/{ref}/work",
                         headers={"X-Cloud-API-Key": app_key})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["number"] == f"№{task.number}"
    assert items[0]["kind_name"] == "Поручение" and items[0]["outcome"] == "done"
    assert items[0]["delivery"]["state"] == "applied"
    assert items[0]["delivery"]["error"] is False
    assert items[0]["id"] == str(request.id)
