"""Шина событий пространства: конверт, подпись, темп повторов.

Ловим то, из-за чего событие молча не доедет: лишний атрибут в конверте (чужой
разбор его не ждёт), подпись не по той строке (получатель отвергнет всё), шаг
повтора короче тика планировщика (доставка выродится в долбёжку каждый тик).
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.space_events import (
    BACKOFF_CAP, EVENT_TYPES, _backoff, envelope, sign,
)

_WHEN = datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc)
_EVENT_ID = uuid.UUID("018f2c9e-7d21-7a53-9a10-0b6f2c4de001")


def test_конверт_несёт_ровно_восемь_атрибутов_cloudevents():
    # Тот же набор, что у шины Поддержки: лишнее поле — это уже другой формат,
    # и разбор на той стороне придётся переписывать.
    out = envelope(_EVENT_ID, "doc.registered", "9c1b", _WHEN, {"a": 1})
    assert set(out) == {"specversion", "id", "source", "type", "subject",
                        "time", "datacontenttype", "data"}
    assert out["specversion"] == "1.0"
    assert out["id"] == str(_EVENT_ID)
    assert out["time"] == "2026-08-20T09:30:00Z"
    assert out["datacontenttype"] == "application/json"


def test_время_события_приводится_к_utc():
    local = datetime(2026, 8, 20, 12, 30,
                     tzinfo=timezone(timedelta(hours=3)))
    assert envelope(_EVENT_ID, "doc.registered", "x", local, {})["time"] == (
        "2026-08-20T09:30:00Z")


def test_подпись_считается_по_строке_id_время_тело():
    secret = "whsec_" + base64.b64encode(b"0123456789abcdef").decode()
    body = json.dumps({"a": 1}, ensure_ascii=False, separators=(",", ":"))
    got = sign(secret, str(_EVENT_ID), 1787227800, body)

    key = base64.b64decode(secret[6:])
    want = base64.b64encode(hmac.new(
        key, f"{_EVENT_ID}.1787227800.{body}".encode(), hashlib.sha256,
    ).digest()).decode()
    assert got == "v1," + want


def test_секрет_без_префикса_берётся_как_есть():
    # Подписчик мог завести свой секрет руками, без нашего префикса.
    assert sign("простой-секрет", "id", 1, "{}").startswith("v1,")


def test_шаг_повтора_растёт_и_упирается_в_потолок():
    # Шаг обязан быть кратен тику планировщика (5 минут), иначе первые попытки
    # придутся на один и тот же тик и повтор выродится в долбёжку.
    assert _backoff(1) == timedelta(minutes=5)
    assert _backoff(2) == timedelta(minutes=10)
    assert _backoff(3) == timedelta(minutes=20)
    assert _backoff(12) == BACKOFF_CAP


def test_каталог_типов_закрыт():
    # Подписка не может ссылаться на событие, которого система не издаёт.
    assert "doc.registered" in EVENT_TYPES
    assert "doc.approval.cancelled" not in EVENT_TYPES


async def test_публикация_неизвестного_типа_запрещена():
    from app.services import space_events

    with pytest.raises(ValueError):
        await space_events.publish(None, uuid.uuid4(), "doc.выдумка", "x", {})


# Настоящие bytes HTTPX Request через MockTransport, без сокетов, DNS и БД.
@pytest.fixture
def signed_delivery(monkeypatch):
    from types import SimpleNamespace
    from app.services import space_events
    import httpx

    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-event-encryption-test-key")
    secret_bytes = b"synthetic-webhook-key-24b"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode()
    sub = SimpleNamespace(id=uuid.uuid4(), target_kind="url", url="https://subscriber.example.test/hook",
        app_code=None, path="/hook", secret_enc=space_events.encrypt_secret(secret), enabled=True,
        stop_day_count=7, last_delivery_at=None, last_status=None, last_error=None,
        failure_streak=0, failing_since=None)
    row = SimpleNamespace(event_id=_EVENT_ID, subscription_id=sub.id, company_id=uuid.uuid4(),
        type="doc.registered", subject="synthetic-document", occurred_at=_WHEN,
        data={"title": "Проверка байтов", "companyId": "core-company"},
        status="pending", next_attempt_at=_WHEN, attempts=0, delivered_at=None, last_error=None)
    clock = SimpleNamespace(value=_WHEN + timedelta(hours=6))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return clock.value
    monkeypatch.setattr(space_events, "datetime", Clock)
    requests, outcomes = [], []
    def receive(request):
        requests.append(request)
        result = outcomes.pop(0) if outcomes else 204
        if isinstance(result, Exception):
            raise result
        return httpx.Response(result, headers={"Location": "https://other.example.test/hook"} if result == 307 else {})
    real_client = httpx.AsyncClient
    clients = []
    def mock_client(**kwargs):
        assert kwargs == {"timeout": space_events.DELIVERY_TIMEOUT}
        client = real_client(transport=httpx.MockTransport(receive), trust_env=False, **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(space_events.httpx, "AsyncClient", mock_client)
    return SimpleNamespace(sub=sub, row=row, clock=clock, requests=requests, outcomes=outcomes,
        key=secret_bytes, secret=secret, clients=clients)


def _verify_delivery(key, body, headers, now, *, tolerance=300):
    """Независимая проверка bytes и свежести получателем, без sender sign()."""
    timestamp = int(headers["webhook-timestamp"])
    signed = (headers["webhook-id"] + "." + str(timestamp) + ".").encode("ascii") + body
    expected = "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
    if not hmac.compare_digest(expected, headers["webhook-signature"]):
        raise ValueError("signature mismatch")
    if abs(int(now.timestamp()) - timestamp) > tolerance:
        raise ValueError("stale or future timestamp")
    return json.loads(body)


async def test_delayed_delivery_uses_attempt_clock_and_preserves_event(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    original_data = dict(d.row.data)
    assert await space_events._send(None, d.sub, d.row) == 204
    request, = d.requests
    assert request.headers["webhook-timestamp"] == str(int(d.clock.value.timestamp()))
    event = _verify_delivery(d.key, request.content, request.headers, d.clock.value)
    assert event["id"] == request.headers["webhook-id"] == str(_EVENT_ID)
    assert event["time"] == "2026-08-20T09:30:00Z"
    assert event["data"] == original_data == d.row.data
    assert d.row.occurred_at == _WHEN and d.row.event_id == _EVENT_ID
    assert "Проверка байтов".encode() in request.content
    assert "authorization" not in request.headers  # URL-доставка не получает Core/SSO токен.


async def test_explicit_delivery_now_is_deterministic_and_timezone_independent(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    attempt = (_WHEN + timedelta(hours=8)).astimezone(timezone(timedelta(hours=3)))
    await space_events._send(None, d.sub, d.row, now=attempt)
    request, = d.requests
    assert request.headers["webhook-timestamp"] == str(int(attempt.timestamp()))
    _verify_delivery(d.key, request.content, request.headers, attempt)


async def test_retry_signatures_change_but_payload_id_and_occurrence_do_not(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    attempts = [_WHEN + delay for delay in (timedelta(minutes=5), timedelta(minutes=15),
                timedelta(minutes=35), timedelta(hours=6, minutes=35))]
    for attempt in attempts:
        assert await space_events._send(None, d.sub, d.row, now=attempt) == 204
        _verify_delivery(d.key, d.requests[-1].content, d.requests[-1].headers, attempt)
    assert len({r.content for r in d.requests}) == 1
    assert {r.headers["webhook-id"] for r in d.requests} == {str(_EVENT_ID)}
    assert len({r.headers["webhook-timestamp"] for r in d.requests}) == len(attempts)
    assert len({r.headers["webhook-signature"] for r in d.requests}) == len(attempts)
    assert d.row.occurred_at == _WHEN and d.row.event_id == _EVENT_ID


async def test_valid_mac_with_old_event_timestamp_fails_freshness_negative_control(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    await space_events._send(None, d.sub, d.row)
    request, = d.requests
    headers = dict(request.headers)
    # Прежний sender: HMAC корректен, отказывает только проверка свежести.
    old = int(d.row.occurred_at.timestamp())
    headers["webhook-timestamp"] = str(old)
    headers["webhook-signature"] = sign(d.secret, str(d.row.event_id), old, request.content.decode("utf-8"))
    assert _verify_delivery(d.key, request.content, headers, _WHEN)["id"] == str(_EVENT_ID)
    with pytest.raises(ValueError, match="stale or future"):
        _verify_delivery(d.key, request.content, headers, d.clock.value)
    # Захваченная корректная попытка не остаётся свежей бесконечно.
    with pytest.raises(ValueError, match="stale or future"):
        _verify_delivery(d.key, request.content, request.headers, d.clock.value + timedelta(seconds=301))
    # Подмена метки без новой подписи не превращает replay в retry.
    headers["webhook-timestamp"] = str(int(d.clock.value.timestamp()))
    with pytest.raises(ValueError, match="signature mismatch"):
        _verify_delivery(d.key, request.content, headers, d.clock.value)


async def test_signature_verifies_wire_bytes_not_reserialized_json(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    await space_events._send(None, d.sub, d.row)
    request, = d.requests
    modified = json.dumps(json.loads(request.content), ensure_ascii=True, indent=2).encode()
    assert json.loads(modified) == json.loads(request.content)
    with pytest.raises(ValueError, match="signature mismatch"):
        _verify_delivery(d.key, modified, request.headers, d.clock.value)
    with pytest.raises(ValueError, match="signature mismatch"):
        _verify_delivery(b"different-subscriber-key", request.content, request.headers, d.clock.value)


async def test_app_delivery_retains_company_mapping_events_scope_and_body(signed_delivery, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from app.services import space_events
    d = signed_delivery
    d.sub.target_kind, d.sub.app_code, d.sub.path = "app", "support", "/api/v1/eco/events"
    target = AsyncMock(return_value=(SimpleNamespace(config={"internalUrl": "http://support:3003"}),
                                    SimpleNamespace(external_company_id="subscriber-company"), "projection-token-unused"))
    token = Mock(return_value="synthetic-events-service-token")
    monkeypatch.setattr(space_events, "_target", target)
    monkeypatch.setattr(space_events.sso, "sign_service_token", token)
    for attempt in (d.clock.value, d.clock.value + timedelta(hours=6)):
        await space_events._send(None, d.sub, d.row, now=attempt)
        request = d.requests[-1]
        event = _verify_delivery(d.key, request.content, request.headers, attempt)
        assert str(request.url) == "http://support:3003/api/v1/eco/events"
        assert request.headers["authorization"] == "Bearer synthetic-events-service-token"
        assert event["data"]["companyId"] == "subscriber-company"
        target.assert_awaited_with(None, d.row.company_id, "support")
        token.assert_called_with(aud="support", scope="events")
    assert d.requests[0].content == d.requests[1].content
    assert d.row.data["companyId"] == "core-company"


@pytest.mark.parametrize("failure", ["mapping", "token"])
async def test_app_auth_or_mapping_failure_never_falls_back_to_url(signed_delivery, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services import space_events
    from app.services.space_projection import ProjectionError
    d = signed_delivery
    d.sub.target_kind, d.sub.app_code = "app", "support"
    target = AsyncMock(return_value=(SimpleNamespace(config={}), SimpleNamespace(external_company_id="mapped"), "unused"))
    if failure == "mapping":
        target.side_effect = ProjectionError("No synthetic company mapping")
    monkeypatch.setattr(space_events, "_target", target)
    monkeypatch.setattr(space_events.sso, "sign_service_token", lambda **kwargs: None)
    with pytest.raises(RuntimeError):
        await space_events._send(None, d.sub, d.row)
    assert not d.requests


def _result(items):
    from types import SimpleNamespace
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: items))


def _delivery_db(rows, subs):
    from unittest.mock import AsyncMock
    return AsyncMock(execute=AsyncMock(return_value=_result(rows)),
                     get=AsyncMock(side_effect=lambda model, key: subs.get(key)))


async def test_retry_scheduler_uses_fresh_attempt_time_and_keeps_transaction_owned_by_caller(signed_delivery):
    from app.services import space_events
    d = signed_delivery
    d.outcomes[:] = [503, 204]
    db = _delivery_db([d.row], {d.sub.id: d.sub})
    first = d.clock.value
    assert await space_events.deliver_pending(db, first) == 0
    assert d.row.status == "pending" and d.row.attempts == 1
    assert d.row.next_attempt_at == first + timedelta(minutes=5)
    assert d.sub.failure_streak == 1 and d.sub.last_status == 503
    # Батч начался раньше фактической отправки: не подписываем scheduler now.
    d.clock.value = d.row.next_attempt_at + timedelta(minutes=6)
    assert await space_events.deliver_pending(db, d.row.next_attempt_at) == 1
    assert d.row.status == "done" and d.row.attempts == 2
    assert d.sub.failure_streak == 0 and d.sub.failing_since is None
    for request, at in zip(d.requests, (first, d.clock.value)):
        _verify_delivery(d.key, request.content, request.headers, at)
    assert d.requests[0].content == d.requests[1].content
    for method in (db.commit, db.rollback, db.flush):
        method.assert_not_awaited()


async def test_successful_subscriber_not_repeated_when_another_retries(signed_delivery):
    from copy import copy
    from app.services import space_events
    d = signed_delivery
    other = copy(d.sub); other.id = uuid.uuid4(); other.url = "https://other.example.test/hook"
    retry = copy(d.row); retry.subscription_id = other.id
    d.outcomes[:] = [204, 503, 204]
    db = _delivery_db([d.row, retry], {d.sub.id: d.sub, other.id: other})
    assert await space_events.deliver_pending(db, d.clock.value) == 1
    assert d.row.status == "done" and retry.status == "pending"
    db.execute.return_value = _result([retry])  # Строки следующей выборки pending.
    d.clock.value += timedelta(minutes=5)
    assert await space_events.deliver_pending(db, d.clock.value) == 1
    assert [str(request.url) for request in d.requests] == [d.sub.url, other.url, other.url]
    assert d.row.attempts == 1 and retry.attempts == 2
    assert {request.headers["webhook-id"] for request in d.requests} == {str(_EVENT_ID)}


@pytest.mark.parametrize("status,attempts", [(503, 1), (307, 1), (500, 11)])
async def test_retry_deadletter_and_redirect_remain_existing_policy(signed_delivery, status, attempts):
    from app.services import space_events
    d = signed_delivery
    d.outcomes[:] = [status]
    d.row.attempts = attempts
    db = _delivery_db([d.row], {d.sub.id: d.sub})
    assert await space_events.deliver_pending(db, d.clock.value) == 0
    assert d.row.attempts == attempts + 1
    assert d.row.last_error == f"HTTP {status}"
    if d.row.attempts == space_events.MAX_ATTEMPTS:
        assert d.row.status == "failed"
    else:
        assert d.row.status == "pending"
        assert d.row.next_attempt_at == d.clock.value + _backoff(d.row.attempts)
    assert len(d.requests) == 1
    assert d.clients[0].follow_redirects is False
    _verify_delivery(d.key, d.requests[0].content, d.requests[0].headers, d.clock.value)


@pytest.mark.parametrize("disabled,expired", [(True, False), (False, True)])
async def test_cancelled_or_expired_event_never_sends_or_spends_attempt(signed_delivery, disabled, expired):
    from app.services import space_events
    d = signed_delivery
    d.sub.enabled = not disabled
    if expired:
        d.clock.value = _WHEN + timedelta(days=d.sub.stop_day_count, seconds=1)
    db = _delivery_db([d.row], {d.sub.id: d.sub})
    assert await space_events.deliver_pending(db, d.clock.value) == 0
    assert d.row.status == ("expired" if expired else "cancelled")
    assert d.row.attempts == 0 and not d.requests
    db.commit.assert_not_awaited()


async def test_publish_fanout_keeps_same_event_id_company_and_caller_transaction():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from app.services import space_events
    company = uuid.uuid4()
    subs = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    db = AsyncMock(execute=AsyncMock(return_value=_result(subs)), add=Mock())
    data = {"id": "synthetic-document"}
    assert await space_events.publish(db, company, "doc.registered", "doc", data, occurred_at=_WHEN) == 2
    rows = [call.args[0] for call in db.add.call_args_list]
    assert len({row.event_id for row in rows}) == 1
    assert {row.subscription_id for row in rows} == {sub.id for sub in subs}
    assert all(row.company_id == company and row.occurred_at == _WHEN and row.data == data for row in rows)
    for method in (db.commit, db.rollback, db.flush):
        method.assert_not_awaited()


async def test_transport_exception_keeps_retry_and_transaction_policy(signed_delivery):
    import httpx
    from app.services import space_events
    d = signed_delivery
    d.outcomes[:] = [httpx.ConnectError("synthetic connection failure")]
    db = _delivery_db([d.row], {d.sub.id: d.sub})
    assert await space_events.deliver_pending(db, d.clock.value) == 0
    assert d.row.status == "pending" and d.row.attempts == 1
    assert d.row.next_attempt_at == d.clock.value + timedelta(minutes=5)
    assert d.row.last_error == "synthetic connection failure"
    assert d.sub.last_status is None and d.sub.failure_streak == 1
    db.commit.assert_not_awaited()
    _verify_delivery(d.key, d.requests[0].content, d.requests[0].headers, d.clock.value)
