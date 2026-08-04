"""Превью ссылки в чате: заголовок, описание и домен.

Ссылка в переписке — это чаще всего «посмотри вот это», и голый URL заставляет
открывать вкладку, чтобы понять, о чём речь. Превью отвечает на вопрос сразу.

Опасность здесь не в разметке, а в том, что сервер ходит по адресу, который
задал пользователь: без ограничений это готовый сканер внутренней сети
(SSRF) — из контейнера видны база, Matrix, соседние стеки и метаданные
облака. Поэтому:

* только http/https и только публичные адреса — приватные, loopback, link-local
  и метаданные отсекаются ПОСЛЕ резолва имени, а не по строке;
* редиректы проходим сами, не более двух и проверяя адрес на каждом шаге —
  штатный follow_redirects увёл бы с публичного домена внутрь сети одним
  заголовком Location;
* жёсткие таймаут и лимит чтения — страница качается не целиком, а первыми
  64 КБ, где и живут og-теги;
* результат кешируется в памяти процесса: одна и та же ссылка в чате
  разворачивается десятками людей.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urlparse, urljoin

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 6.0
MAX_BYTES = 64 * 1024
CACHE_TTL = 3600.0
CACHE_MAX = 500

_cache: dict[str, tuple[float, dict | None]] = {}

_META_RE = re.compile(
    rb"""<meta[^>]+(?:property|name)\s*=\s*["']([^"']+)["'][^>]*content\s*=\s*["']([^"']*)["']"""
    rb"""|<meta[^>]+content\s*=\s*["']([^"']*)["'][^>]*(?:property|name)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _public_host(host: str) -> bool:
    """Имя резолвится в публичный адрес? Приватная сеть — не наше дело."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _decode(raw: bytes, charset: str | None) -> str:
    for enc in (charset, "utf-8", "windows-1251"):
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="ignore")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _parse(raw: bytes, base_url: str, charset: str | None) -> dict:
    text = _decode(raw, charset)
    data = text.encode("utf-8", errors="ignore")
    meta: dict[str, str] = {}
    for m in _META_RE.finditer(data):
        key = (m.group(1) or m.group(4) or b"").decode("utf-8", "ignore").lower()
        val = (m.group(2) or m.group(3) or b"").decode("utf-8", "ignore")
        if key and key not in meta:
            meta[key] = html.unescape(val).strip()

    title = meta.get("og:title") or meta.get("twitter:title") or ""
    if not title:
        t = _TITLE_RE.search(data)
        if t:
            title = html.unescape(t.group(1).decode("utf-8", "ignore")).strip()
    desc = meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or ""
    image = meta.get("og:image") or meta.get("twitter:image") or ""
    if image:
        image = urljoin(base_url, image)
        # Картинку сервер не проксирует, её будет грузить браузер — значит
        # адрес должен быть публичным и по https, иначе не показываем вовсе.
        if not image.startswith("https://"):
            image = ""

    return {
        "url": base_url,
        "site": urlparse(base_url).hostname or "",
        "title": title[:200],
        "description": desc[:400],
        "image": image[:500],
    }


async def fetch_preview(url: str) -> dict | None:
    """Карточка ссылки или None, если адрес недопустим либо страница молчит."""
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not await asyncio.get_running_loop().run_in_executor(None, _public_host, parsed.hostname):
        logger.info("[link-preview] адрес отклонён: %s", parsed.hostname)
        return None

    result: dict | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False,
                                     headers={"User-Agent": "ElsyPlus-LinkPreview/1.0"}) as client:
            target = url
            # Редиректы проходим САМИ, не более двух и проверяя адрес на каждом
            # шаге: httpx с follow_redirects увёл бы с публичного домена внутрь
            # сети одним заголовком Location. Без этого не открывается половина
            # ссылок — http→https и короткие адреса это норма.
            for _ in range(3):
                async with client.stream("GET", target) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        nxt = resp.headers.get("location")
                        if not nxt:
                            break
                        nxt = urljoin(target, nxt)
                        host = urlparse(nxt).hostname
                        if (urlparse(nxt).scheme not in ("http", "https") or not host
                                or not await asyncio.get_running_loop().run_in_executor(
                                    None, _public_host, host)):
                            logger.info("[link-preview] редирект отклонён: %s", nxt)
                            break
                        target = nxt
                        continue
                    ctype = resp.headers.get("content-type", "")
                    if resp.status_code >= 400 or "html" not in ctype.lower():
                        break
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= MAX_BYTES:
                            break
                    charset = None
                    if "charset=" in ctype:
                        charset = ctype.split("charset=")[-1].split(";")[0].strip()
                    result = _parse(b"".join(chunks), str(resp.url), charset)
                    if not result["title"] and not result["description"]:
                        result = None
                    break
    except Exception as exc:  # noqa: BLE001 — превью не должно ронять чат
        logger.info("[link-preview] %s: %s", url, exc)
        result = None

    if len(_cache) > CACHE_MAX:
        _cache.clear()
    _cache[url] = (now, result)
    return result
