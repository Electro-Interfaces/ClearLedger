"""ROOT-only local conformance. No public receiver, system DNS or real credentials."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest
import pytest_asyncio

if (os.environ.get("RUN_WEBHOOK_DELIVERY_BOUNDARY_TESTS") != "1"
        or os.environ.get("ROOT_APPROVED_WEBHOOK_DELIVERY_BOUNDARY") != "1"):
    pytest.skip("ROOT frozen webhook boundary runner required", allow_module_level=True)

import httpcore
from app.services import space_events, webhook_delivery as delivery
from app.routers import space_events_router as routes
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio(loop_scope="session")
PUBLIC = "1.1.1.1"
PUBLIC2 = "8.8.8.8"
HOST = "receiver.example.test"
HTTP_PORT = 33547
HTTPS_PORT = 33548
WHEN = datetime(2026, 10, 31, 9, tzinfo=timezone.utc)
EVENT = uuid.UUID("018f2c9e-7d21-7a53-9a10-0b6f2c4de001")


def headers():
    return {"Content-Type": "application/json", "webhook-id": str(EVENT),
            "webhook-timestamp": "1793437200", "webhook-signature": "v1,synthetic-wire-value"}


def answer(ip=PUBLIC, port=443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
            (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port))


@pytest.fixture(autouse=True)
def frozen_boundary(request):
    assert request.config._webhook_delivery_boundary.active


@pytest.mark.parametrize("url", [None, "", "ftp://receiver.example.test/", "http://localhost/", "http://postgres/",
    "http://support/", "http://metadata.google.internal/", "http://127.0.0.1/", "http://0.0.0.0/", "http://10.1.2.3/",
    "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/", "http://100.64.0.1/", "http://192.0.2.1/",
    "http://224.0.0.1/", "http://240.0.0.1/", "http://255.255.255.255/", "http://[::1]/", "http://[::]/",
    "http://[fe80::1%25eth0]/", "http://[fc00::1]/", "http://[fec0::1]/", "http://[ff02::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:8.8.8.8]/", "http://[2002:7f00:1::]/", "http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/",
    "http://[64:ff9b::a9fe:a9fe]/", "http://[64:ff9b:1::a9fe:a9fe]/", "http://[64:ff9b::808:808]/",
    "http://2130706433/", "http://0x7f000001/", "http://127.1/", "http://0177.0.0.1/", "http://0x7f.0.0.1/",
    "http://%31%32%37.0.0.1/", "http://127。0。0。1/", "https://user:DO-NOT-ECHO@receiver.example.test/",
    "https://receiver.example.test/#DO-NOT-ECHO", "https://receiver.example.test/#", "https://receiver.example.test:80/",
    "http://receiver.example.test:443/", "https://receiver.example.test:0/", "https://receiver.example.test:65536/",
    "https://receiver.example.test:+443/", "https://receiver.example.test:0443/", "https://receiver.example.test:/",
    "https://receiver.example.test\\@localhost/", "https://receiver.example.test/\nDO-NOT-ECHO",
    "https://receiver.example.test/\t", "http://support.default.svc.cluster.local/", "http://receiver.svc/",
    "http://xn--.test/", "http://bad_name.test/", "https://receiver.example.test/" + "x" * 500])
async def test_rejects_unsafe_or_ambiguous_urls_without_resolution(url, monkeypatch):
    resolver = AsyncMock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(delivery, "_resolve", resolver)
    with pytest.raises(delivery.WebhookDeliveryError) as error:
        delivery.parse_url(url)
    assert str(error.value) == "URL webhook: адрес назначения не разрешён"
    assert "DO-NOT-ECHO" not in str(error.value)
    resolver.assert_not_awaited()


@pytest.mark.parametrize("url,host,authority,path", [
    ("http://Receiver.Example.Test/hook?a=%2F", HOST, HOST, b"/hook?a=%2F"),
    ("https://receiver.example.test:443/hook", HOST, HOST, b"/hook"),
    ("https://Receiver.Example.Test./", HOST, HOST, b"/"),
    ("https://пример.рф/путь", "xn--e1afmkfd.xn--p1ai", "xn--e1afmkfd.xn--p1ai", b"/%D0%BF%D1%83%D1%82%D1%8C"),
    ("https://8.8.8.8/", PUBLIC2, PUBLIC2, b"/"),
    ("https://[2606:4700:4700::1111]/", "2606:4700:4700::1111", "[2606:4700:4700::1111]", b"/")])
async def test_canonical_url_host_and_wire_target(url, host, authority, path):
    value = delivery.parse_url(url)
    assert value.host == host and value.authority == authority and value.path == path
    assert value.port == (80 if url.startswith("http:") else 443)


@pytest.mark.parametrize("infos", [[], [answer(PUBLIC), answer("127.0.0.1")],
    [answer("10.0.0.1"), answer(PUBLIC)], [answer(PUBLIC), answer("::ffff:127.0.0.1")],
    [answer(PUBLIC), answer("100.64.0.1")], [answer(PUBLIC), answer("64:ff9b::a9fe:a9fe")],
    [answer(PUBLIC)] * 65, [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", (PUBLIC, 443))],
    [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (PUBLIC, 443))], [answer(PUBLIC, 80)],
    [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700::1111", 443, 0, 1))]])
async def test_full_dns_set_fails_closed_before_any_dial(infos, monkeypatch):
    resolver = AsyncMock(return_value=infos)
    factory = Mock(side_effect=AssertionError("must not construct transport"))
    monkeypatch.setattr(delivery, "_resolve", resolver)
    monkeypatch.setattr(delivery, "_dial_backend", factory)
    with pytest.raises(delivery.WebhookDeliveryError):
        await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers())
    resolver.assert_awaited_once_with(HOST, 443)
    factory.assert_not_called()


@pytest.mark.parametrize("error", [socket.gaierror("DO-NOT-ECHO"), RuntimeError("https://user:DO-NOT-ECHO@host/")])
async def test_dns_errors_are_safe_in_admission_and_send(error, monkeypatch):
    monkeypatch.setattr(delivery, "_resolve", AsyncMock(side_effect=error))
    for call in (lambda: delivery.approve_url(f"https://{HOST}/"),
                 lambda: delivery.send(f"https://{HOST}/", body=b"{}", headers=headers())):
        with pytest.raises(delivery.WebhookDeliveryError) as e:
            await call()
        assert "DO-NOT-ECHO" not in str(e.value) and "https://" not in str(e.value)


class RecordingStream(httpcore.AsyncMockStream):
    def __init__(self, response):
        super().__init__([response])
        self.writes, self.tls = [], []
    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)
    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, response=b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n", fail_first=False):
        self.calls, self.streams, self.response, self.fail_first = [], [], response, fail_first
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port, timeout, local_address, socket_options))
        if self.fail_first and len(self.calls) == 1:
            raise httpcore.ConnectError("DO-NOT-ECHO")
        stream = RecordingStream(self.response)
        self.streams.append(stream)
        return stream


def fake_network(monkeypatch, *, infos=None, response=None, fail_first=False):
    resolver = AsyncMock(return_value=infos if infos is not None else [answer()])
    backend = RecordingBackend(fail_first=fail_first, **({"response": response} if response is not None else {}))
    monkeypatch.setattr(delivery, "_resolve", resolver)
    monkeypatch.setattr(delivery, "_dial_backend", lambda: backend)
    return resolver, backend


def wire_request(stream):
    wire = b"".join(stream.writes)
    head, body = wire.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    return lines[0], {k.decode().lower(): v.strip().decode() for k, v in (line.split(b":", 1) for line in lines[1:])}, body


async def test_rebind_is_not_requeried_and_dial_is_numeric_with_original_tls_host(monkeypatch):
    resolver, backend = fake_network(monkeypatch)
    resolver.side_effect = [[answer()], [answer("127.0.0.1")]]
    assert await delivery.send(f"https://{HOST}/hook?x=1", body=b'{"wire":"bytes"}', headers=headers()) == 204
    resolver.assert_awaited_once_with(HOST, 443)
    assert [c[:2] for c in backend.calls] == [(PUBLIC, 443)]
    stream, = backend.streams
    line, got_headers, body = wire_request(stream)
    assert line == b"POST /hook?x=1 HTTP/1.1" and body == b'{"wire":"bytes"}'
    assert got_headers["host"] == HOST
    assert stream.tls == [(HOST, True, ssl.CERT_REQUIRED)] and stream._closed
    assert not ({"authorization", "proxy-authorization", "cookie"} & got_headers.keys())


async def test_public_fallback_never_uses_an_unvetted_address(monkeypatch):
    resolver, backend = fake_network(monkeypatch, infos=[answer(PUBLIC), answer(PUBLIC2)], fail_first=True)
    assert await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers()) == 204
    assert [c[:2] for c in backend.calls] == [(PUBLIC, 443), (PUBLIC2, 443)]
    assert resolver.await_count == 1


@pytest.mark.parametrize("url,host_header", [("https://пример.рф/", "xn--e1afmkfd.xn--p1ai"),
    ("https://[2606:4700:4700::1111]/", "[2606:4700:4700::1111]")])
async def test_idna_and_ipv6_keep_original_http_identity(url, host_header, monkeypatch):
    resolver, backend = fake_network(monkeypatch, infos=[answer("2606:4700:4700::1111")])
    assert await delivery.send(url, body=b"{}", headers=headers()) == 204
    _, h, _ = wire_request(backend.streams[0])
    assert h["host"] == host_header
    if ":" in host_header:
        resolver.assert_not_awaited()
    assert backend.streams[0].tls[0][0] == host_header.strip("[]")


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_redirect_never_adds_dns_or_a_second_connection(status, monkeypatch):
    response = f"HTTP/1.1 {status} Redirect\r\nLocation: http://127.0.0.1/DO-NOT-ECHO\r\nContent-Length: 0\r\n\r\n".encode()
    resolver, backend = fake_network(monkeypatch, response=response)
    assert await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers()) == status
    assert resolver.await_count == len(backend.calls) == 1


@pytest.mark.parametrize("extra", ["Authorization", "Proxy-Authorization", "Cookie"])
async def test_unexpected_authority_headers_are_rejected_before_dns(extra, monkeypatch):
    resolver, backend = fake_network(monkeypatch)
    with pytest.raises(delivery.WebhookDeliveryError):
        await delivery.send(f"https://{HOST}/", body=b"{}", headers={**headers(), extra: "DO-NOT-ECHO"})
    resolver.assert_not_awaited()
    assert not backend.calls


@pytest.mark.parametrize("size,accepted", [(65536, True), (65537, False)])
async def test_response_full_drain_has_an_exact_memory_cap(size, accepted, monkeypatch):
    response = f"HTTP/1.1 200 OK\r\nContent-Length: {size}\r\n\r\n".encode() + b"x" * size
    _, backend = fake_network(monkeypatch, response=response)
    if accepted:
        assert await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers()) == 200
    else:
        with pytest.raises(delivery.WebhookDeliveryError, match="размер"):
            await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers())
    assert backend.streams[0]._closed


async def test_timeout_bounds_resolution_and_cleanup(monkeypatch):
    async def slow_resolver(*args):
        await asyncio.sleep(60)
    monkeypatch.setattr(delivery, "_resolve", slow_resolver)
    started = asyncio.get_running_loop().time()
    with pytest.raises(delivery.WebhookDeliveryError, match="время"):
        await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers(), timeout=0.03)
    assert asyncio.get_running_loop().time() - started < 1


async def test_pool_close_is_part_of_total_deadline(monkeypatch):
    _, backend = fake_network(monkeypatch)
    original = httpcore.AsyncConnectionPool.aclose
    async def slow_close(pool):
        await asyncio.sleep(60)
        await original(pool)
    monkeypatch.setattr(httpcore.AsyncConnectionPool, "aclose", slow_close)
    started = asyncio.get_running_loop().time()
    with pytest.raises(delivery.WebhookDeliveryError, match="время"):
        await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers(), timeout=0.03)
    assert asyncio.get_running_loop().time() - started < 1
    assert backend.streams[0]._closed


async def test_default_ssl_context_keeps_verification_and_ignores_ambient_cert_file(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/does-not-exist/DO-NOT-ECHO.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/does-not-exist/DO-NOT-ECHO")
    ctx = delivery._ssl_context()
    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN


class HandlerDB:
    def __init__(self):
        self.items = []
        self.add = Mock(side_effect=self.items.append)
        self.flush = AsyncMock(side_effect=self.prepare)
        self.commit, self.rollback = AsyncMock(), AsyncMock()
    async def prepare(self):
        for item in self.items:
            item.id = uuid.uuid4()
            item.created_at = WHEN
            item.failure_streak = 0


@pytest.fixture
def handler(monkeypatch):
    company, actor = uuid.uuid4(), SimpleNamespace(id=uuid.uuid4(), name="Synthetic admin")
    db = HandlerDB()
    admin = AsyncMock(return_value=company)
    audit = AsyncMock()
    monkeypatch.setattr(routes, "_admin", admin)
    monkeypatch.setattr(routes, "_assert_label_free", AsyncMock())
    monkeypatch.setattr(routes, "log_audit", audit)
    monkeypatch.setenv("EVENTS_SECRET_KEY", "webhook-boundary-synthetic-encryption-key")
    sub = SimpleNamespace(id=uuid.uuid4(), label="Existing", target_kind="url", app_code=None, path="/hook",
        url="http://127.0.0.1/legacy", secret_enc="legacy", secret_hint="legacy", event_types=["doc.registered"],
        stop_day_count=30, enabled=True, last_delivery_at=None, last_status=None, last_error="old error",
        failure_streak=3, failing_since=WHEN, disabled_reason=None, disabled_at=None, created_at=WHEN)
    monkeypatch.setattr(routes, "_sub_or_404", AsyncMock(return_value=sub))
    return SimpleNamespace(**locals())


async def test_create_target_uses_same_dns_owner_before_any_persistence(handler, monkeypatch):
    h = handler
    resolver = AsyncMock(return_value=[answer("127.0.0.1")])
    monkeypatch.setattr(delivery, "_resolve", resolver)
    payload = routes.SubscriptionIn(company_id=str(h.company), label="Synthetic", target_kind="url",
        url=f"https://{HOST}/", event_types=["doc.registered"])
    with pytest.raises(HTTPException) as e:
        await routes.create_subscription(payload, h.db, h.actor)
    assert e.value.status_code == 400
    h.db.add.assert_not_called()
    h.db.flush.assert_not_awaited()
    h.audit.assert_not_awaited()
    h.admin.assert_awaited_once_with(str(h.company), h.actor, h.db)


async def test_create_public_target_uses_real_handler_and_valid_hmac_secret(handler, monkeypatch):
    h = handler
    resolver = AsyncMock(return_value=[answer()])
    monkeypatch.setattr(delivery, "_resolve", resolver)
    payload = routes.SubscriptionIn(company_id=str(h.company), label="Synthetic", target_kind="url",
        url=f"https://{HOST}/", event_types=["doc.registered"])
    out = await routes.create_subscription(payload, h.db, h.actor)
    assert out["url"] == payload.url and out["secret"].startswith("whsec_")
    assert len(base64.b64decode(out["secret"][6:])) == 24
    h.db.flush.assert_awaited_once()
    h.db.commit.assert_not_awaited()
    resolver.assert_awaited_once_with(HOST, 443)


@pytest.mark.parametrize("patch", [{"label": "Renamed"}, {"enabled": True},
    {"enabled": False, "url": "http://10.0.0.1/changed"},
    {"enabled": False, "url": " http://127.0.0.1/legacy "}])
async def test_label_enable_and_changed_target_cannot_bypass_validation(handler, patch):
    h = handler
    with pytest.raises(HTTPException) as e:
        await routes.update_subscription(str(h.sub.id), routes.SubscriptionPatch(company_id=str(h.company), **patch), h.db, h.actor)
    assert e.value.status_code == 400
    assert h.sub.enabled and h.sub.url == "http://127.0.0.1/legacy" and h.sub.label == "Existing"
    h.db.flush.assert_not_awaited()
    h.db.commit.assert_not_awaited()


@pytest.mark.parametrize("explicit_target", [False, True])
async def test_manual_true_to_false_unchanged_target_skips_dns_and_secret_mint(handler, monkeypatch, explicit_target):
    h = handler
    h.sub.secret_enc = None
    resolver = AsyncMock(side_effect=AssertionError("manual disable must not resolve"))
    mint = Mock(side_effect=AssertionError("manual disable must not mint"))
    monkeypatch.setattr(delivery, "_resolve", resolver)
    monkeypatch.setattr(routes, "_new_secret", mint)
    supplied = {"target_kind": h.sub.target_kind, "app_code": h.sub.app_code, "url": h.sub.url, "path": h.sub.path} if explicit_target else {}
    out = await routes.update_subscription(str(h.sub.id), routes.SubscriptionPatch(company_id=str(h.company), enabled=False, **supplied), h.db, h.actor)
    assert out["enabled"] is False and out["url"] == "http://127.0.0.1/legacy"
    assert h.sub.secret_enc is None and out["secret"] is None
    resolver.assert_not_awaited()
    mint.assert_not_called()
    h.db.flush.assert_awaited_once()
    h.db.commit.assert_not_awaited()


async def test_already_disabled_legacy_target_does_not_get_disable_exception(handler):
    h = handler
    h.sub.enabled = False
    with pytest.raises(HTTPException) as e:
        await routes.update_subscription(str(h.sub.id), routes.SubscriptionPatch(company_id=str(h.company), enabled=False), h.db, h.actor)
    assert e.value.status_code == 400
    h.db.flush.assert_not_awaited()


@pytest_asyncio.fixture(loop_scope="session")
async def receivers(tmp_path):
    """Owned loopback only. No policy flag permits private destinations in production."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic webhook CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
            encipher_only=None, decipher_only=None), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
        .sign(key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    cert = (x509.CertificateBuilder().subject_name(server_name).issuer_name(name).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=None, decipher_only=None), True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
        .sign(key, hashes.SHA256()))
    ca_path, cert_path, key_path = [tmp_path / f for f in ("ca.pem", "server.pem", "server-key.pem")]
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(server_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_path, key_path)
    sni, requests, tasks, client_sockets = [], [], set(), []
    server_ctx.set_servername_callback(lambda sock, name, ctx: sni.append(name))
    response = {"status": 204, "location": None, "stall": False, "keep_open": False}
    async def receive(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            raw_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
            lines = raw_head.split(b"\r\n")
            h = {k.decode().lower(): v.strip().decode() for k, v in (line.split(b":", 1) for line in lines[1:] if line)}
            body = await asyncio.wait_for(reader.readexactly(int(h.get("content-length", "0"))), 2)
            requests.append((lines[0], h, body))
            if response["stall"]:
                await asyncio.wait_for(reader.read(), 2)
                return
            location = f"Location: {response['location']}\r\n" if response["location"] else ""
            connection = "keep-alive" if response["keep_open"] else "close"
            writer.write(f"HTTP/1.1 {response['status']} Result\r\n{location}Content-Length: 0\r\nConnection: {connection}\r\n\r\n".encode())
            await writer.drain()
            if response["keep_open"]:
                await asyncio.wait_for(reader.read(), 2)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError):
                pass
            finally:
                tasks.discard(task)
    http = await asyncio.start_server(receive, "127.0.0.1", HTTP_PORT)
    https = await asyncio.start_server(receive, "127.0.0.1", HTTPS_PORT, ssl=server_ctx)
    try:
        yield SimpleNamespace(**locals())
    finally:
        http.close()
        https.close()
        await http.wait_closed()
        await https.wait_closed()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*list(tasks), return_exceptions=True), 3)


def map_local(monkeypatch, receivers, *, tls_trust=True):
    """Test-only dial adapter records the approved public IP, then uses owned localhost."""
    original = httpcore.AnyIOBackend()
    calls = []
    class LocalBackend(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            calls.append((host, port))
            assert host == PUBLIC and port in (80, 443)
            stream = await original.connect_tcp("127.0.0.1", HTTP_PORT if port == 80 else HTTPS_PORT, timeout=timeout)
            sock = stream.get_extra_info("socket")
            assert sock is not None and sock.fileno() >= 0
            receivers.client_sockets.append(sock)
            return stream
    monkeypatch.setattr(delivery, "_dial_backend", LocalBackend)
    resolver = AsyncMock(side_effect=lambda host, port: [answer(PUBLIC, port)])
    monkeypatch.setattr(delivery, "_resolve", resolver)
    if tls_trust:
        monkeypatch.setattr(delivery, "_ssl_context", lambda: ssl.create_default_context(cafile=receivers.ca_path))
    return resolver, calls


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_actual_receiver_verifies_signed_bytes_id_time_host_and_tls(receivers, monkeypatch, scheme):
    resolver, calls = map_local(monkeypatch, receivers)
    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-webhook-boundary-key")
    key = b"independent-receiver-key"
    secret = "whsec_" + base64.b64encode(key).decode()
    sub = SimpleNamespace(target_kind="url", url=f"{scheme}://{HOST}/hook", secret_enc=space_events.encrypt_secret(secret))
    row = SimpleNamespace(event_id=EVENT, type="doc.registered", subject="synthetic-document", occurred_at=WHEN,
                          data={"title": "Проверка байтов"})
    attempt = WHEN + timedelta(hours=6)
    assert await space_events._send(None, sub, row, now=attempt) == 204
    line, h, body = receivers.requests[0]
    assert line == b"POST /hook HTTP/1.1" and h["host"] == HOST
    assert h["webhook-id"] == str(EVENT) and h["webhook-timestamp"] == str(int(attempt.timestamp()))
    expected = base64.b64encode(hmac.new(key, (str(EVENT) + "." + h["webhook-timestamp"] + ".").encode() + body, hashlib.sha256).digest()).decode()
    assert h["webhook-signature"] == "v1," + expected
    value = json.loads(body)
    assert value["time"] == "2026-10-31T09:00:00Z" and value["id"] == str(EVENT)
    assert b"\\u041f" not in body and "Проверка байтов".encode() in body
    assert not ({"authorization", "proxy-authorization", "cookie"} & h.keys())
    assert calls == [(PUBLIC, 80 if scheme == "http" else 443)] and resolver.await_count == 1
    assert receivers.sni == ([HOST] if scheme == "https" else [])


@pytest.mark.parametrize("failure", ["wrong_name", "untrusted_ca"])
async def test_actual_tls_failure_sends_no_application_body(receivers, monkeypatch, failure):
    resolver, calls = map_local(monkeypatch, receivers, tls_trust=failure != "untrusted_ca")
    host = "wrong.example.test" if failure == "wrong_name" else HOST
    with pytest.raises(delivery.WebhookDeliveryError) as e:
        await delivery.send(f"https://{host}/DO-NOT-ECHO", body=b"DO-NOT-ECHO", headers=headers())
    assert not receivers.requests
    assert "DO-NOT-ECHO" not in str(e.value) and "certificate" not in str(e.value).lower()
    assert receivers.sni == [host] and calls == [(PUBLIC, 443)] and resolver.await_count == 1


async def test_actual_http_redirect_and_ambient_proxy_cannot_change_destination(receivers, monkeypatch):
    resolver, calls = map_local(monkeypatch, receivers)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9/DO-NOT-ECHO")
    receivers.response.update(status=307, location="http://127.0.0.1/DO-NOT-ECHO")
    assert await delivery.send(f"http://{HOST}/hook", body=b"{}", headers=headers()) == 307
    assert calls == [(PUBLIC, 80)] and resolver.await_count == 1 and len(receivers.requests) == 1


async def test_blocked_legacy_target_keeps_safe_retry_without_disable_or_delete(monkeypatch):
    sub = SimpleNamespace(id=uuid.uuid4(), enabled=True, target_kind="url", url="http://user:DO-NOT-ECHO@127.0.0.1/",
        secret_enc=None, stop_day_count=30, failure_streak=0,
        failing_since=None, last_status=None, last_error=None, last_delivery_at=None)
    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-boundary-key")
    sub.secret_enc = space_events.encrypt_secret("legacy-key")
    row = SimpleNamespace(event_id=EVENT, subscription_id=sub.id, company_id=uuid.uuid4(), type="doc.registered",
        subject="synthetic", data={}, occurred_at=WHEN, status="pending", attempts=0,
        next_attempt_at=WHEN, last_error=None, delivered_at=None)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))),
        get=AsyncMock(return_value=sub), delete=AsyncMock(), commit=AsyncMock(), flush=AsyncMock())
    assert await space_events.deliver_pending(db, WHEN + timedelta(hours=1)) == 0
    assert row.status == "pending" and row.attempts == 1 and sub.enabled
    assert row.last_error == sub.last_error == "URL webhook: адрес назначения не разрешён"
    assert "DO-NOT-ECHO" not in row.last_error and row.next_attempt_at == WHEN + timedelta(hours=1, minutes=5)
    for method in (db.delete, db.commit, db.flush):
        method.assert_not_awaited()


async def test_response_close_is_bounded_and_pool_still_closes_stream(monkeypatch):
    _, backend = fake_network(monkeypatch)
    original = httpcore.Response.aclose
    async def slow_close(response):
        await asyncio.sleep(60)
        await original(response)
    monkeypatch.setattr(httpcore.Response, "aclose", slow_close)
    started = asyncio.get_running_loop().time()
    with pytest.raises(delivery.WebhookDeliveryError, match="время"):
        await delivery.send(f"https://{HOST}/", body=b"{}", headers=headers(), timeout=0.03)
    assert asyncio.get_running_loop().time() - started < 1
    assert backend.streams[0]._closed


async def test_pinned_transitive_sdk_has_reviewed_public_backend_contract():
    import inspect
    import httpx
    assert httpcore.__version__ == "1.0.9" and httpx.__version__ == "0.28.1"
    assert "network_backend" in inspect.signature(httpcore.AsyncConnectionPool).parameters
    assert "server_hostname" in inspect.signature(httpcore.AsyncNetworkStream.start_tls).parameters


@pytest.mark.parametrize("phase", ["read", "response_close"])
async def test_actual_timeout_closes_native_client_fd_and_peer_task(receivers, monkeypatch, phase):
    resolver, calls = map_local(monkeypatch, receivers)
    if phase == "read":
        receivers.response["stall"] = True
    else:
        receivers.response["keep_open"] = True
        original = httpcore.Response.aclose
        async def slow_close(response):
            await asyncio.sleep(60)
            await original(response)
        monkeypatch.setattr(httpcore.Response, "aclose", slow_close)
    started = asyncio.get_running_loop().time()
    with pytest.raises(delivery.WebhookDeliveryError, match="время"):
        await delivery.send(f"http://{HOST}/", body=b"{}", headers=headers(), timeout=0.25)
    assert asyncio.get_running_loop().time() - started < 1
    assert len(receivers.requests) == 1 and calls == [(PUBLIC, 80)] and resolver.await_count == 1
    # Keep real socket objects alive: GC cannot substitute for explicit cleanup.
    assert len(receivers.client_sockets) == 1
    for _ in range(20):
        if all(sock.fileno() == -1 for sock in receivers.client_sockets) and not receivers.tasks:
            break
        await asyncio.sleep(0.01)
    assert all(sock.fileno() == -1 for sock in receivers.client_sockets)
    assert not receivers.tasks
