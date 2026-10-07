"""Защита пространства от враждебных действий снаружи (МАГ 07.10.2026).

Что ловим — каждое отдельным видом в журнале безопасности (`security_events`):

* `trap` — обращение к ловушке: путь, который ищут сканеры и которого у нас нет
  (`/.env`, `/.git`, `wp-*`, `phpmyadmin`, «выгрузить всё» в API). Честный клиент туда
  не ходит никогда, поэтому адрес сразу блокируется на час.
* `bad_ua` — инструмент взлома в User-Agent (sqlmap, nuclei, nikto…): блок на час.
* `probe` — шквал 404/401/403 с одного адреса: перебор адресов API или чужих токенов.
  От 40 в минуту — запись и тревога, от 120 — блок.
* `login_failed` — подбор пароля к учётной записи: 5 неудач за 15 минут по одному email.
* `mass_read` — выкачка данных своим же пользователем: больше 1500 запросов к API за
  минуту по одному токену. Не блокируем — бывает законная массовая работа, — но тревога.
* `rate_limited` — упор в лимит публичных ручек (`rate_limit.py`), как и раньше.

Тревога — письмо и чат «Секретаря» суперадминистраторам и сообщение в Telegram (бот
алертов инфраструктуры, через прокси). Повтор одного эпизода (вид + адрес) склеивается:
запись — раз в 10 минут, тревога — раз в час. Иначе атака превратила бы наш журнал и
почту в поток, то есть в атаку нашими же руками.

Счётчики — в памяти процесса (как `rate_limit.py`, Redis в стеке нет): при нескольких
воркерах пороги умножаются на их число. Блокировки — в базе, чтобы их видели все
воркеры и экран «Безопасность»; процесс перечитывает их раз в 30 секунд.

Адрес клиента — первый в `X-Forwarded-For`: кромка Traefik доверяет заголовку только от
rproxy (с 07.10.2026), до этого весь трафик выглядел адресом rproxy.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Request

logger = logging.getLogger("clearledger.security")

# Пути, которых у нас нет и которые ищут сканеры. Снаружи стека nginx отдаёт их сюда
# (`/api/security/trap`), в API — ловушки-приманки под видом «удобных» ручек.
TRAP_RE = re.compile(
    r"(^|/)(\.env|\.git|\.svn|\.hg|\.aws|\.ssh|\.DS_Store|wp-[a-z]+|wordpress|xmlrpc\.php|phpmyadmin|pma|"
    r"cgi-bin|actuator|server-status|\.well-known/security\.txt\.bak|config\.(json|php|yml)|"
    r"backup|dump|db\.sql)|\.(php|asp|aspx|jsp|sql|bak)$", re.I)
# Приманки в API: «удобные» ручки, которых у нас нет. Точное имя, а не префикс — чтобы
# не задеть настоящие (`/api/meetings/config` и т.п.).
API_TRAP_RE = re.compile(
    r"^/api/(admin/export[\w-]*|export/all|v1/users|debug|graphql|swagger[\w./-]*|openapi\.json|\.env|config)/?$", re.I)
BAD_UA_RE = re.compile(
    r"sqlmap|nikto|nuclei|zgrab|masscan|nmap|dirbuster|gobuster|ffuf|wpscan|acunetix|nessus|openvas|"
    r"feroxbuster|whatweb|wfuzz|hydra|jaeles|arachni|httpx-toolkit|katana", re.I)

PROBE_WINDOW, PROBE_ALERT, PROBE_BLOCK = 60, 40, 120
LOGIN_WINDOW, LOGIN_ALERT = 900, 5
READ_WINDOW, READ_ALERT = 60, 1500
BLOCK_SECONDS = 3600
EVENT_EVERY, ALERT_EVERY = 600, 3600

_probe: dict[str, deque[float]] = defaultdict(deque)
_login: dict[str, deque[float]] = defaultdict(deque)
_reads: dict[str, deque[float]] = defaultdict(deque)
_said: dict[str, float] = {}
_alerted: dict[str, float] = {}
_blocks: dict[str, float] = {}
_blocks_at = 0.0
_MAX = 20_000

KIND_LABEL = {
    "trap": "обращение к ловушке (сканер ищет уязвимости)",
    "bad_ua": "инструмент взлома в заголовке браузера",
    "probe": "шквал отказов 404/401/403 — перебор адресов API или токенов",
    "login_failed": "подбор пароля к учётной записи",
    "mass_read": "массовая выкачка данных пользователем",
    "rate_limited": "упор в лимит публичных ручек",
}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded.strip():
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "-")[:64]


def _window(store: dict[str, deque[float]], key: str, now: float, span: int) -> deque[float]:
    hits = store[key]
    while hits and now - hits[0] > span:
        hits.popleft()
    if len(store) > _MAX:
        for k in [k for k, v in store.items() if not v][: len(store) - _MAX + 1]:
            store.pop(k, None)
    return hits


def is_trap(path: str) -> bool:
    if path.startswith("/api/"):
        return bool(API_TRAP_RE.match(path))
    return bool(TRAP_RE.search(path))


def is_bad_ua(ua: str | None) -> bool:
    return bool(ua and BAD_UA_RE.search(ua))


async def blocked(ip: str) -> bool:
    """Адрес под блокировкой. Список — из базы, перечитывается раз в 30 секунд."""
    global _blocks, _blocks_at
    now = time.monotonic()
    if now - _blocks_at > 30:
        _blocks_at = now
        try:
            from sqlalchemy import select
            from app.database import async_session_factory
            from app.models import SecurityBlock
            async with async_session_factory() as db:
                rows = (await db.execute(select(SecurityBlock.ip, SecurityBlock.until).where(
                    SecurityBlock.until > datetime.now(timezone.utc),
                    SecurityBlock.lifted_at.is_(None)))).all()
            _blocks = {ip_: until.timestamp() for ip_, until in rows}
        except Exception:  # noqa: BLE001 — сбой чтения не открывает и не закрывает сайт
            logger.warning("Список блокировок не прочитан", exc_info=True)
    until = _blocks.get(ip)
    return until is not None and until > time.time()


async def record(kind: str, request: Request | None = None, *, ip: str | None = None, path: str = "",
                 hits: int = 1, detail: str | None = None, block: bool = False) -> None:
    """Записать эпизод, при необходимости заблокировать адрес и поднять тревогу."""
    ip = ip or (client_ip(request) if request else "-")
    path = (path or (request.url.path if request else ""))[:200]
    ua = (request.headers.get("user-agent") or "")[:300] if request else None
    key = f"{kind}|{ip}"
    now = time.monotonic()
    if now - _said.get(key, -1e9) < EVENT_EVERY:
        return
    _said[key] = now
    try:
        from app.database import async_session_factory
        from app.models import SecurityBlock, SecurityEvent
        async with async_session_factory() as db:
            db.add(SecurityEvent(kind=kind, scope="guard", ip=ip, path=path, user_agent=ua or None,
                                 hits=hits, detail=(detail or "")[:1000] or None))
            if block and ip not in _blocks:
                until = datetime.now(timezone.utc) + timedelta(seconds=BLOCK_SECONDS)
                db.add(SecurityBlock(ip=ip, until=until, reason=f"{kind}: {path}"[:300]))
                _blocks[ip] = until.timestamp()
            await db.commit()
    except Exception:  # noqa: BLE001 — журнал не должен ронять ответ
        logger.warning("Эпизод не записан: %s %s", kind, ip, exc_info=True)
    if now - _alerted.get(key, -1e9) >= ALERT_EVERY:
        _alerted[key] = now
        text = (f"Безопасность: {KIND_LABEL.get(kind, kind)}\nАдрес: {ip}\nПуть: {path or '—'}"
                f"{f'\nПодробно: {detail}' if detail else ''}{f'\nБраузер: {ua}' if ua else ''}"
                f"{f'\nАдрес заблокирован на {BLOCK_SECONDS // 60} мин.' if block else ''}")
        asyncio.create_task(_alert(text))


async def _alert(text: str) -> None:
    """Тревога суперадминистраторам: письмо, чат «Секретаря», Telegram. Каждый канал сам по себе."""
    from app.config import get_settings
    settings = get_settings()
    host = settings.app_public_url.rstrip("/")
    full = f"{text}\nПространство: {host}\nЖурнал: {host}/admin/eco/security"
    try:
        from sqlalchemy import select
        from app.database import async_session_factory
        from app.models import User
        from app.services import email_service, notify
        async with async_session_factory() as db:
            admins = (await db.execute(select(User).where(User.is_superadmin.is_(True),
                                                          User.mail_only.is_(False)))).scalars().all()
            emails = [u.email for u in admins if u.email]
            if emails:
                await email_service.send_notice(emails, "Тревога безопасности пространства", full)
            for u in admins:
                if u.company_id is not None:
                    try:
                        await notify.notify_person(db, u.company_id, u, full)
                    except Exception:  # noqa: BLE001
                        logger.warning("Тревога в чат не ушла: %s", u.id, exc_info=True)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Тревога по почте и в чат не ушла", exc_info=True)
    if settings.security_tg_token and settings.security_tg_chat:
        try:
            import httpx
            async with httpx.AsyncClient(proxy=settings.security_tg_proxy or None, timeout=15) as c:
                await c.post(f"https://api.telegram.org/bot{settings.security_tg_token}/sendMessage",
                             json={"chat_id": settings.security_tg_chat, "text": full})
        except Exception:  # noqa: BLE001
            logger.warning("Тревога в Telegram не ушла", exc_info=True)


def forget_block(ip: str) -> None:
    """Снятая блокировка — убрать из кэша этого процесса сразу, остальные перечитают."""
    _blocks.pop(ip, None)


def note_response(request: Request, status: int) -> tuple[str, int] | None:
    """Учесть ответ: шквал отказов с адреса и объём чтения по токену. Возвращает эпизод."""
    now = time.monotonic()
    ip = client_ip(request)
    if status in (401, 403, 404) and request.url.path.startswith("/api/"):
        hits = _window(_probe, ip, now, PROBE_WINDOW)
        hits.append(now)
        if len(hits) >= PROBE_BLOCK:
            return "probe_block", len(hits)
        if len(hits) >= PROBE_ALERT:
            return "probe", len(hits)
    auth = request.headers.get("authorization")
    if auth and request.method == "GET":
        key = hashlib.sha256(auth.encode()).hexdigest()[:16]
        hits = _window(_reads, key, now, READ_WINDOW)
        hits.append(now)
        if len(hits) >= READ_ALERT:
            return "mass_read", len(hits)
    return None


def note_login_failed(email: str, ip: str) -> int:
    """Неудачный вход по email; возвращает число неудач за окно."""
    now = time.monotonic()
    hits = _window(_login, email.lower()[:200], now, LOGIN_WINDOW)
    hits.append(now)
    return len(hits)


if __name__ == "__main__":  # самопроверка распознавания
    assert is_trap("/.env") and is_trap("/wp-login.php") and is_trap("/api/admin/export-all")
    assert is_trap("/blog/wp-includes/wlwmanifest.xml") and is_trap("/index.php")
    assert not is_trap("/api/sites/1/docs") and not is_trap("/projects") and not is_trap("/assets/index-x.js")
    assert not is_trap("/api/meetings/config") and not is_trap("/api/admin/backups") and is_trap("/api/config")
    assert is_bad_ua("sqlmap/1.7") and not is_bad_ua("Mozilla/5.0 Chrome/128")
    print("ok")
