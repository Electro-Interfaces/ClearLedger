"""
Web Push чата: доставка сообщения, когда вкладка закрыта.

VAPID-ключи генерируются при первом обращении и живут в БД (`chat_push_keys`) —
смена ключей протухает все подписки браузеров, поэтому пара стабильна на весь
стек. Отправка — в фоне со своей сессией (как notify.dispatch_async): падение
push-сервиса не должно ломать отправку сообщения.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatParticipant, ChatPushKeys, ChatPushSubscription

logger = logging.getLogger("clearledger.webpush")

# Живые фоновые задачи: см. комментарий у create_task ниже.
_tasks: set = set()

_VAPID_CLAIM_SUB = "mailto:noreply@dataworker.ru"


async def get_or_create_keys(db: AsyncSession) -> ChatPushKeys:
    """Пара VAPID этого стека; создаётся один раз."""
    keys = await db.get(ChatPushKeys, 1)
    if keys is not None:
        return keys
    pk = ec.generate_private_key(ec.SECP256R1())
    pem = pk.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = pk.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_b64 = base64.urlsafe_b64encode(pub).rstrip(b"=").decode()
    keys = ChatPushKeys(id=1, private_pem=pem, public_key=public_b64)
    db.add(keys)
    await db.commit()
    logger.info("Сгенерирована пара VAPID для Web Push")
    return keys


def _send_one(private_pem: str, sub: dict, payload: str) -> None:
    """Синхронная отправка одной подписке (pywebpush) — зовётся из потока."""
    from pywebpush import webpush  # ленивый импорт: тянет cryptography-цепочку
    webpush(
        subscription_info=sub,
        data=payload,
        vapid_private_key=private_pem,
        vapid_claims={"sub": _VAPID_CLAIM_SUB},
        timeout=10,
    )


def push_room_async(room_id: uuid.UUID, title: str, body: str,
                    exclude_user_id: uuid.UUID) -> None:
    """Разослать push участникам комнаты в фоне: не онлайн, не «без звука», не автор.

    Fire-and-forget со своей сессией: транзакцию вызывающего не держим, ошибки —
    только в лог. Протухшие подписки (404/410 от push-сервиса) удаляются.
    """
    async def _run() -> None:
        from app.database import async_session_factory
        from app.services.chat_ws import manager
        try:
            async with async_session_factory() as db:
                keys = await get_or_create_keys(db)
                now = datetime.now(timezone.utc)
                rows = (await db.execute(select(
                    ChatParticipant.user_id, ChatParticipant.muted_until,
                ).where(ChatParticipant.room_id == room_id))).all()
                targets = [uid for uid, mu in rows
                           if uid != exclude_user_id
                           and not (mu is not None and mu > now)
                           and not manager.is_online(str(uid))]
                if not targets:
                    return
                subs = (await db.execute(select(ChatPushSubscription).where(
                    ChatPushSubscription.user_id.in_(targets)))).scalars().all()
                if not subs:
                    return
                full = json.dumps({"title": title, "body": body, "roomId": str(room_id)},
                                  ensure_ascii=False)
                # Устройство, которому текст показывать нельзя (общий стол, чужие руки
                # у заблокированного экрана), получает только факт сообщения.
                quiet = json.dumps({"title": title, "body": "Новое сообщение",
                                    "roomId": str(room_id)}, ensure_ascii=False)
                stale: list[ChatPushSubscription] = []
                for s in subs:
                    payload = full if s.show_preview else quiet
                    info = {"endpoint": s.endpoint,
                            "keys": {"p256dh": s.p256dh, "auth": s.auth}}
                    try:
                        await asyncio.to_thread(_send_one, keys.private_pem, info, payload)
                    except Exception as e:  # noqa: BLE001 — сторонний push-сервис
                        code = getattr(getattr(e, "response", None), "status_code", None)
                        if code in (404, 410):
                            stale.append(s)   # браузер отписался — чистим
                        else:
                            logger.warning("Push не ушёл (%s): %s", s.endpoint[:60], e)
                for s in stale:
                    await db.delete(s)
                if stale:
                    await db.commit()
        except Exception as e:  # noqa: BLE001 — push не важнее сообщения
            logger.warning("Рассылка push сорвалась: %s", e)

    try:
        # Ссылку держим в модуле: голый create_task() сборщик мусора вправе убрать
        # до того, как задача доработает — тихая потеря уведомления.
        task = asyncio.get_running_loop().create_task(_run())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        pass  # нет цикла (тесты) — просто не шлём
