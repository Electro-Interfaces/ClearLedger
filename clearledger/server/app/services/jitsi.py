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


async def share_series_url(db, ev) -> None:
    """Раздать ссылку комнаты повторениям серии, у которых ссылки ещё нет.

    Голова получает комнату при первом входе, а повторения к этому моменту уже
    созданы без неё — и в «Конференциях» не появляются. Чужие ссылки (Zoom,
    вписанные руками) не трогаем.
    """
    from sqlalchemy import or_, update

    from app.models import CalendarEvent

    корень = ev.series_id or ev.id
    await db.execute(update(CalendarEvent).where(
        or_(CalendarEvent.id == корень, CalendarEvent.series_id == корень),
        CalendarEvent.conference_url.is_(None),
        CalendarEvent.status != "cancelled").values(conference_url=ev.conference_url))


def sign_token(room: str, display_name: str, *, moderator: bool = True, hours: int = 4) -> str | None:
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
        "exp": now + hours * 3600,
        "context": {"user": {"name": display_name or "Пользователь", "moderator": moderator}},
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": settings.jitsi_kid})


def meeting_urls(room: str, display_name: str, hours: int = 4,
                 moderator: bool = True) -> dict:
    """Ссылка входа (с токеном) + гостевая (без токена) на ту же комнату.

    `moderator=False` — вход обычным участником: в чужой конференции
    распоряжается тот, кто её собрал, и раздавать права ведущего каждому
    вошедшему нельзя (решение МАГа 10.09.2026).
    """
    token = sign_token(room, display_name, moderator=moderator, hours=hours)
    base = f"https://{settings.jitsi_domain}/{quote(room)}"
    return {
        "room": room,
        "moderator_url": f"{base}?jwt={token}" if token else base,
        "guest_url": base,
    }
