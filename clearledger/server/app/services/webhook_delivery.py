"""External webhook destinations: one public-only admission and connect boundary.

Internal app delivery deliberately has a different registry/SSO owner. No ambient
proxy, URL credentials, global resolver patch or cross-attempt address cache.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit

import certifi
import httpcore
import httpx
import idna

MAX_DNS_ANSWERS = 64
MAX_RESPONSE_BYTES = 64 * 1024
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa", ".svc", ".cluster.local")
_MESSAGES = {
    "address": "URL webhook: адрес назначения не разрешён",
    "dns": "URL webhook: невозможно проверить адрес назначения",
    "timeout": "URL webhook: превышено время доставки",
    "response": "URL webhook: превышен допустимый размер ответа",
    "delivery": "URL webhook: не удалось доставить событие",
}


class WebhookDeliveryError(RuntimeError):
    def __init__(self, code: str = "delivery"):
        self.code = code if code in _MESSAGES else "delivery"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    authority: str
    path: bytes
    literal: bool


def _public_ip(value: str) -> str:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        raise WebhookDeliveryError("address") from None
    if (not addr.is_global or addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        raise WebhookDeliveryError("address")
    if isinstance(addr, ipaddress.IPv6Address):
        if (addr.scope_id or addr.is_site_local or addr.ipv4_mapped or addr.sixtofour
                or addr.teredo or any(addr in prefix for prefix in _NAT64)):
            raise WebhookDeliveryError("address")
    return str(addr)


def parse_url(raw: str | None) -> Target:
    """Lexical/canonical owner. DNS belongs to approve_url and each send attempt."""
    try:
        if (not isinstance(raw, str) or not raw or len(raw) > 500
                or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in raw)
                or "\\" in raw or "#" in raw):
            raise ValueError()
        parts = urlsplit(raw)
        if (parts.scheme not in ("http", "https") or not parts.netloc or not parts.hostname
                or "@" in parts.netloc or "%" in parts.netloc
                or parts.username is not None or parts.password is not None):
            raise ValueError()
        authority = parts.netloc
        suffix = authority[authority.index("]") + 1:] if authority.startswith("[") else (
            ":" + authority.rsplit(":", 1)[1] if ":" in authority else "")
        if suffix and (not suffix.startswith(":") or not re.fullmatch(r":[1-9][0-9]*", suffix)):
            raise ValueError()
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if port != (443 if parts.scheme == "https" else 80):
            raise ValueError()
        host = parts.hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            host = idna.encode(host.rstrip(".").lower(), std3_rules=True).decode("ascii")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if ("." not in host or len(host) > 253 or host.endswith(_SUFFIXES)
                        or all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part)
                               for part in host.split("."))):
                    raise ValueError()
                literal = False
            else:
                host, literal = _public_ip(host), True
        else:
            host, literal = _public_ip(host), True
        wire = httpx.URL(raw)
        if wire.raw_host.rstrip(b".").lower() != host.encode("ascii"):
            raise ValueError()
        canonical_authority = f"[{host}]" if ":" in host else host
        return Target(parts.scheme, host, port, canonical_authority, wire.raw_path, literal)
    except WebhookDeliveryError:
        raise
    except (ValueError, UnicodeError, httpx.InvalidURL, idna.IDNAError):
        raise WebhookDeliveryError("address") from None


async def _resolve(host: str, port: int):
    return await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)


async def _addresses(target: Target) -> tuple[str, ...]:
    if target.literal:
        return (_public_ip(target.host),)
    try:
        infos = await _resolve(target.host, target.port)
        if not infos or len(infos) > MAX_DNS_ANSWERS:
            raise ValueError()
        addresses = []
        for family, kind, protocol, _, address in infos:
            if (family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM
                    or protocol not in (0, socket.IPPROTO_TCP) or address[1] != target.port
                    or (family == socket.AF_INET6 and (len(address) != 4 or address[3] != 0))):
                raise ValueError()
            ip = _public_ip(address[0])
            if ipaddress.ip_address(ip).version != (4 if family == socket.AF_INET else 6):
                raise ValueError()
            if ip not in addresses:
                addresses.append(ip)
        return tuple(addresses)
    except WebhookDeliveryError:
        raise
    except (OSError, ValueError, TypeError, IndexError):
        raise WebhookDeliveryError("dns") from None


async def approve_url(raw: str | None, *, timeout: float = 10.0) -> Target:
    try:
        async with asyncio.timeout(min(timeout, 10.0)):
            target = parse_url(raw)
            await _addresses(target)
            return target
    except WebhookDeliveryError:
        raise
    except TimeoutError:
        raise WebhookDeliveryError("timeout") from None
    except Exception:
        raise WebhookDeliveryError("dns") from None


def _dial_backend():
    return httpcore.AnyIOBackend()


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, target: Target, addresses: tuple[str, ...], deadline: float):
        self.target = target
        self.addresses = tuple(_public_ip(ip) for ip in addresses)
        self.deadline = deadline
        self.delegate = _dial_backend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host != self.target.host or port != self.target.port or local_address is not None
                or socket_options):
            raise WebhookDeliveryError("address")
        for ip in self.addresses:
            remaining = self.deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise httpcore.ConnectTimeout()
            try:
                return await self.delegate.connect_tcp(ip, port,
                    timeout=min(remaining, timeout if timeout is not None else remaining, 3.0))
            except (httpcore.ConnectError, httpcore.ConnectTimeout):
                continue
        raise httpcore.ConnectError()

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


def _ssl_context():
    # Explicit CA source: no SSL_CERT_FILE/DIR or proxy environment authority.
    return ssl.create_default_context(cafile=certifi.where())


async def _close(resource, deadline):
    # A second expired deadline also bounds cleanup entered after cancellation.
    async with asyncio.timeout_at(deadline):
        await resource.aclose()


async def send(raw: str | None, *, body: bytes, headers: dict[str, str], timeout: float = 10.0) -> int:
    deadline = asyncio.get_running_loop().time() + min(timeout, 10.0)
    pool = response = None
    try:
        async with asyncio.timeout_at(deadline):
            target = parse_url(raw)
            allowed = {"content-type", "webhook-id", "webhook-timestamp", "webhook-signature"}
            if (not isinstance(body, bytes) or {key.lower() for key in headers} != allowed
                    or any("\r" in value or "\n" in value for value in headers.values())):
                raise WebhookDeliveryError()
            addresses = await _addresses(target)
            pool = httpcore.AsyncConnectionPool(ssl_context=_ssl_context(), proxy=None,
                max_connections=1, max_keepalive_connections=0, http1=True, http2=False, retries=0,
                network_backend=_PinnedBackend(target, addresses, deadline))
            wire_headers = [(key.encode("ascii"), value.encode("ascii")) for key, value in headers.items()]
            wire_headers += [(b"Host", target.authority.encode("ascii")),
                             (b"Content-Length", str(len(body)).encode("ascii"))]
            request = httpcore.Request(b"POST", httpcore.URL(scheme=target.scheme.encode("ascii"),
                host=target.host.encode("ascii"), port=target.port, target=target.path),
                headers=wire_headers, content=body,
                extensions={"timeout": {phase: timeout for phase in ("connect", "read", "write", "pool")}})
            try:
                response = await pool.handle_async_request(request)
                size = 0
                async for chunk in response.aiter_stream():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise WebhookDeliveryError("response")
                return response.status
            finally:
                try:
                    if response is not None:
                        await _close(response, deadline)
                finally:
                    await _close(pool, deadline)
    except WebhookDeliveryError:
        raise
    except TimeoutError:
        raise WebhookDeliveryError("timeout") from None
    except Exception:
        raise WebhookDeliveryError() from None
