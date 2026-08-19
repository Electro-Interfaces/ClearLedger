"""Согласование внешним участником: право на одну активность, а не на систему.

Фаза 6 плана (`ecosystem-deploy/audit-process-runtime.md`). Подрядчик, арендодатель
или инспектор не заведёт учётку ради одной визы в квартал — а виза нужна, и нужна
с доказательством. До этого выбор был между «завести человека в компании» (лишний
член пространства с правами на всё, что видит роль) и «согласовать на бумаге».

Здесь появляется третий путь: ссылка, дающая право поставить **одну** визу на
**одном** шаге. Не доступ к документу вообще, не членство, не роль.

Что удерживает это от превращения в дыру:

* **Срок обязателен** — он у `DocShareLink` уже был и не может быть пустым.
* **Одноразовость** — после решения ссылка мертва (`used_at`); пересланная кому-то
  ссылка не превращается во вторую подпись.
* **Отзыв мгновенный** — `revoked` проверяется при каждом обращении, а не при
  выпуске: отозванная ссылка перестаёт работать в ту же секунду.
* **След дословный** — адрес, время, user-agent и **текст**, под которым человек
  расписался. Через два года спор будет не о факте нажатия, а о том, с чем
  согласились, и наш пересказ на это не отвечает.

Юридический предел назван прямо, как и у показа документа: это простая
электронная подпись по 63-ФЗ, и она работает, когда порядок её использования
согласован сторонами в договоре.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocApproval, DocCard, DocShareLink, User

# Текст, под которым внешний участник ставит визу. Хранится в доказательстве
# целиком: он и есть предмет согласия.
APPROVE_TEXT = (
    "Подтверждаю, что ознакомился с документом в показанной редакции и согласовываю его. "
    "Действие равнозначно моей визе в листе согласования."
)
REJECT_TEXT = (
    "Подтверждаю, что ознакомился с документом в показанной редакции и отказываю в "
    "согласовании по указанной причине."
)

# Срок по умолчанию, если выпускающий его не назвал. Не «бесконечность»: ссылка
# без срока — это утечка, отложенная во времени.
DEFAULT_TTL_DAYS = 7
MAX_TTL_DAYS = 90


@dataclass
class ExternalActor:
    """Внешний участник в роли актора визы.

    Повторяет ровно те поля `User`, которые читает согласование, — и ничего
    больше. Учётки за этим объектом нет: `id` пуст, и это видно в следе.
    """

    name: str
    email: str | None = None
    id: uuid.UUID | None = None


class ExternalApprovalError(Exception):
    """Право не выдаётся или не действует — с причиной для человека."""


async def issue_link(db: AsyncSession, company_id: uuid.UUID, approval: DocApproval,
                     *, token_hash: str, token_prefix: str,
                     created_by: User | None = None,
                     ttl_days: int | None = None,
                     recipient_name: str | None = None) -> DocShareLink:
    """Выпустить ссылку на одну визу.

    Снимок редакций и карточки берётся тем же кодом, что и при показе документа:
    без него замена файла задним числом меняет содержание уже поставленной визы.
    """
    if approval.status != "pending":
        raise ExternalApprovalError("Эта виза уже поставлена или ещё не активна")
    if approval.actor_kind != "external":
        raise ExternalApprovalError("Шаг не предназначен для внешнего участника")

    days = min(max(int(ttl_days or DEFAULT_TTL_DAYS), 1), MAX_TTL_DAYS)
    doc = await db.get(DocCard, approval.doc_id)
    if doc is None or doc.company_id != company_id:
        raise ExternalApprovalError("Документ не найден")

    # Живая ссылка на этот шаг уже могла быть выпущена. Отзываем её сами: две
    # рабочие ссылки на одну визу — это спор о том, какая подпись настоящая.
    for old in (await db.execute(select(DocShareLink).where(
            DocShareLink.approval_id == approval.id,
            DocShareLink.revoked.is_(False),
            DocShareLink.used_at.is_(None)))).scalars().all():
        old.revoked = True

    link = DocShareLink(
        company_id=company_id,
        doc_id=doc.id,
        purpose="approve",
        approval_id=approval.id,
        token_hash=token_hash,
        token_prefix=token_prefix,
        recipient_name=recipient_name or approval.actor_ref,
        recipient_email=approval.actor_ref,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        created_by=created_by.id if created_by else None,
    )
    db.add(link)
    await db.flush()
    return link


def guard(link: DocShareLink) -> None:
    """Проверить, что правом ещё можно воспользоваться.

    Порядок проверок важен: сначала назначение, потом расход. Иначе на ссылку для
    просмотра пришёл бы ответ «уже использована», подсказывающий, что где-то есть
    и ссылка на подпись.
    """
    if link.purpose != "approve" or not link.approval_id:
        raise ExternalApprovalError("Ссылка не даёт права согласовывать")
    if link.used_at is not None:
        raise ExternalApprovalError("Ссылка уже использована")


async def decide(db: AsyncSession, link: DocShareLink, *, approved: bool,
                 signer_name: str, comment: str | None,
                 ip: str | None, user_agent: str | None) -> dict[str, Any]:
    """Поставить визу от имени внешнего участника и запечатать доказательство."""
    from app.services import doc_approvals

    guard(link)

    approval = await db.get(DocApproval, link.approval_id)
    if approval is None or approval.status != "pending":
        raise ExternalApprovalError("Виза уже поставлена")
    doc = await db.get(DocCard, link.doc_id)
    if doc is None:
        raise ExternalApprovalError("Документ не найден")

    name = (signer_name or "").strip()
    if not name:
        raise ExternalApprovalError("Укажите, кто согласовывает")
    if not approved and not (comment or "").strip():
        raise ExternalApprovalError("При отказе нужна причина")

    actor = ExternalActor(name=f"{name} (внешний участник)", email=approval.actor_ref)
    now = datetime.now(timezone.utc)

    # Доказательство пишем ДО решения: решение может закрыть круг и увести
    # документ дальше, а обстоятельства подписи относятся к этому моменту.
    link.used_at = now
    link.acknowledged_at = link.acknowledged_at or now
    link.acknowledged_by_name = name
    link.ack_evidence = {
        "at": now.isoformat(),
        "ip": ip,
        "user_agent": (user_agent or "")[:300],
        "name": name,
        "email": approval.actor_ref,
        "decision": "approved" if approved else "rejected",
        "comment": (comment or "").strip() or None,
        "text": APPROVE_TEXT if approved else REJECT_TEXT,
        "step": {"code": approval.step_code, "name": approval.step_name,
                 "round": approval.round},
        "files": link.version_snapshot,
        "card": link.card_snapshot,
    }

    result = await doc_approvals.decide(
        db, link.company_id, doc, approval, actor, approved,
        (comment or "").strip() or None)
    if result.get("error"):
        raise ExternalApprovalError(result["error"])
    return {"status": result.get("status"), "decided_at": now.isoformat()}
