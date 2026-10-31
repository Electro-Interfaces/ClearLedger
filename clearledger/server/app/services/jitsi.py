"""Подпись Jitsi-JWT (RS256 / ASAP) для видеоконференций TradeLedger.

meet.dataworker.ru работает с per-issuer JWT: TradeLedger подписывает организаторский
токен СВОИМ приватным ключом (iss=ledger, kid=ledger/1), prosody проверяет публичным
ключом с keyserver по kid (`asap_key_server/<sha256_hex(kid)>.pem`). Приватный ключ —
env `JITSI_SIGNING_KEY` (PEM в base64), НЕ в git; публичный лежит на keyserver; `ledger`
должен быть в `JWT_ACCEPTED_ISSUERS` Jitsi-стека.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote

import jwt

from app.config import get_settings

settings = get_settings()


def _private_key() -> str | None:
    b64 = settings.jitsi_signing_key
    if not b64:
        return None
    return base64.b64decode(b64).decode("utf-8")


def new_room() -> str:
    """Случайная неугадываемая комната."""
    return f"ledger-{secrets.token_hex(8)}"


def room_for(subject: str) -> str:
    """Постоянная комната предмета: `event:<uuid>`, `doc:<uuid>`.

    Имя считается от предмета, а не выдаётся случайно на каждое нажатие. Иначе
    в собственную комнату не вернуться: организатор, закрывший вкладку, заводил
    новую, а участники оставались ждать в прежней. Считается на приватном ключе
    пространства — угадать имя чужой комнаты по номеру встречи нельзя.
    """
    key = _private_key()
    if not key:
        return new_room()
    return "ledger-" + hmac.new(key.encode(), subject.encode(),
                                hashlib.sha256).hexdigest()[:16]


def event_room(ev) -> str:
    """Комната встречи календаря. У серии она одна на все повторения.

    Повторения получают ссылку головы серии (`run_meeting_series`), а вход
    считал комнату от номера самого повторения: гости по ссылке из приглашения
    попадали в одну комнату, ведущий — в другую (РусГидро, серия «Интеграция»,
    13.10.2026). Еженедельная планёрка — одно место, как и её ссылка.
    """
    return room_for(f"event:{ev.series_id or ev.id}")


async def meeting_hosts(db, ev) -> set:
    """Ведущие встречи: отмеченные участники, а не отмечен никто — организатор."""
    from sqlalchemy import select

    from app.models import CalendarAttendee

    отмечены = set((await db.execute(select(CalendarAttendee.user_id).where(
        CalendarAttendee.event_id == ev.id, CalendarAttendee.is_host.is_(True)))).scalars())
    return отмечены or {ev.organizer_id}


async def share_series_url(db, ev) -> None:
    """Раздать ссылку комнаты повторениям серии, у которых ссылки ещё нет.

    Голова получает комнату при первом входе, а повторения к этому моменту уже
    созданы без неё — и в «Конференциях» не появляются. Чужие ссылки (Zoom,
    вписанные руками) не трогаем.
    """
    from app.services import calendar_protocol

    await calendar_protocol.share_series_url(db, ev)


def sign_token(room: str, display_name: str, *, moderator: bool = True, hours: int = 4, ttl_seconds: int | None = None) -> str | None:
    """Подписать RS256 JWT организатора. None, если ключ подписи не задан."""
    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": settings.jitsi_issuer,
        # Это токен для самого Jitsi (prosody), а не наш handoff: aud задаёт ВНЕШНИЙ
        # сервис и переименованию под код продукта не подлежит.
        "aud": "jitsi",
        "sub": settings.jitsi_xmpp_domain,  # внутренний XMPP-домен, не публичный URL
        "room": room,
        "iat": now,
        "nbf": now - 10,
        "exp": now + (ttl_seconds if ttl_seconds is not None else hours * 3600),
        "context": {"user": {"name": display_name or "Пользователь", "moderator": moderator}},
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.jitsi_kid})


def with_subject(url: str | None, subject: str | None) -> str | None:
    """Гостевая ссылка с темой: гость до прихода ведущего видел на входе номер
    комнаты «Ledger A 66 C…» (QA 27.10.2026). Фрагмент `#config.subject` комнату
    не меняет — сохранённая ссылка встречи остаётся голой, по ней её узнают
    календарь и журнал. Чужие ссылки (Zoom, Teams) не трогаем."""
    if not url or not subject or not subject.strip() or "#" in url             or f"//{settings.jitsi_domain}/" not in url:
        return url
    return url + "#config.subject=" + quote(json.dumps(subject.strip()[:120], ensure_ascii=False))


def meeting_urls(room: str, display_name: str, hours: int = 4,
                 moderator: bool = True, subject: str | None = None) -> dict:
    """Ссылка входа (с токеном) + гостевая (без токена) на ту же комнату.

    `moderator=False` — вход обычным участником: в чужой конференции
    распоряжается тот, кто её собрал, и раздавать права ведущего каждому
    вошедшему нельзя (решение МАГа 10.09.2026).

    `subject` — тема в заголовке комнаты вместо «Ledger F 8637 E 8 B…». Едет
    только в ссылке входа: тему комнате ставит ведущий, остальные видят её уже
    выставленной, а гостевая ссылка остаётся голым адресом комнаты — по нему
    её узнают календарь и журнал.
    """
    token = sign_token(room, display_name, moderator=moderator, hours=hours)
    base = f"https://{settings.jitsi_domain}/{quote(room)}"
    вход = f"{base}?jwt={token}" if token else base
    if subject and subject.strip():
        # Значение параметра Jitsi разбирает как JSON — отсюда кавычки.
        вход += "#config.subject=" + quote(json.dumps(subject.strip()[:120],
                                                      ensure_ascii=False))
    return {
        "room": room,
        "moderator_url": вход,
        "guest_url": base,
    }
