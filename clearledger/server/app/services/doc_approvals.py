"""Согласование документа: маршрут, круги, визы.

Почему свой движок, а не маршрут задачи. У задачи одна текущая стадия и один
исполнитель, а виза бывает параллельной: договор одновременно смотрят юрист и
финансист. Несколько одновременных состояний одной карточки стадией не
выражаются, поэтому здесь строки на каждого согласующего.

Что сознательно не берём: условные переходы («свыше миллиона — плюс финдиректор»)
и вычисляемые маршруты. Это уже скриптуемый процесс, а продукт держится
декларативных шаблонов. Разная цепочка по сумме описывается двумя видами
документа, и человек выбирает вид при заведении.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CompanyRole, Department, DocApproval, DocCard, DocEvent, DocVersion, User,
    UserCompany,
)

# Из чего резолвится согласующий. Незнакомый способ отбрасывается санитайзером:
# иначе в справочнике копится мусор, за которым ничего не стоит.
ACTOR_KINDS = ("user", "role", "department", "head_of", "position")
MODES = ("serial", "parallel")
BUSINESS_TIMEZONE = ZoneInfo("Europe/Moscow")


def clean_route(route: Any) -> list[dict]:
    """Оставить в маршруте только то, что движок понимает.

    Тот же приём, что у маршрута задачи: белый список ключей и дедупликация
    шагов. Без него первая же правка формы принесёт в базу поля, которые никто
    не читает, но все боятся удалить.
    """
    out: list[dict] = []
    if not isinstance(route, list):
        return out
    for raw in route:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()[:40]
        name = str(raw.get("name") or "").strip()[:120]
        if not code or not name or any(s["code"] == code for s in out):
            continue
        actors: list[dict] = []
        for a in (raw.get("actors") or []):
            if not isinstance(a, dict):
                continue
            by = str(a.get("by") or "").strip()
            ref = str(a.get("ref") or "").strip()[:120]
            if by in ACTOR_KINDS and ref:
                actors.append({"by": by, "ref": ref})
        if not actors:
            continue
        mode = str(raw.get("mode") or "serial")
        quorum = str(raw.get("quorum") or "all")[:10]
        sla = raw.get("sla_hours")
        step: dict[str, Any] = {
            "code": code, "name": name,
            "mode": mode if mode in MODES else "serial",
            "quorum": quorum if (quorum in ("all", "any") or quorum.isdigit()) else "all",
            "actors": actors,
            "required": bool(raw.get("required", True)),
        }
        if isinstance(sla, int) and 0 < sla <= 8760:
            step["sla_hours"] = sla
        if raw.get("step_kind") == "sign":
            step["step_kind"] = "sign"
        out.append(step)
    return out


async def resolve_actors(db: AsyncSession, cid: uuid.UUID,
                         actors: list[dict]) -> list[tuple[str, str, uuid.UUID]]:
    """Развернуть описание согласующих в конкретных людей.

    Возвращает тройки (способ, ссылка, человек). Снимок делается один раз, при
    запуске: если человек завтра сменит отдел, виза останется на нём, а не
    исчезнет вместе с его должностью.
    """
    out: list[tuple[str, str, uuid.UUID]] = []
    seen: set[uuid.UUID] = set()

    def add(kind: str, ref: str, uid: uuid.UUID | None) -> None:
        if uid and uid not in seen:
            seen.add(uid)
            out.append((kind, ref, uid))

    for a in actors:
        by, ref = a.get("by"), a.get("ref")
        if by == "user":
            try:
                uid = uuid.UUID(ref)
            except (ValueError, TypeError):
                continue
            if await db.get(UserCompany, (uid, cid)) is not None:
                add("user", ref, uid)
        elif by == "head_of":
            try:
                dep = await db.get(Department, uuid.UUID(ref))
            except (ValueError, TypeError):
                dep = None
            if dep is not None:
                add("head_of", ref, dep.head_user_id)
        elif by == "department":
            try:
                dep_id = uuid.UUID(ref)
            except (ValueError, TypeError):
                continue
            rows = (await db.execute(select(UserCompany.user_id).where(
                UserCompany.company_id == cid,
                UserCompany.department_id == dep_id))).scalars().all()
            for uid in rows:
                add("department", ref, uid)
        elif by == "role":
            try:
                role_id = uuid.UUID(ref)
            except (ValueError, TypeError):
                continue
            role = await db.get(CompanyRole, role_id)
            if role is None or role.company_id != cid:
                continue
            rows = (await db.execute(select(UserCompany.user_id).where(
                UserCompany.company_id == cid,
                UserCompany.role_id == role_id))).scalars().all()
            for uid in rows:
                add("role", ref, uid)
        elif by == "position":
            rows = (await db.execute(select(UserCompany.user_id).where(
                UserCompany.company_id == cid,
                UserCompany.position == ref))).scalars().all()
            for uid in rows:
                add("position", ref, uid)
    return out


async def active_deputy_for(db: AsyncSession, cid: uuid.UUID,
                            user_id: uuid.UUID, on_date=None) -> list[uuid.UUID]:
    """Кто сегодня замещает этого человека.

    Виза за другого запрещена, но отпуск не должен останавливать документ.
    Заместитель ставит визу ОТ СВОЕГО ИМЕНИ на основании замещения, и в листе
    видно обоих: за кого и кто фактически.
    """
    from app.models import UserSubstitution

    day = on_date or datetime.now(BUSINESS_TIMEZONE).date()
    rows = (await db.execute(select(UserSubstitution.deputy_id).where(
        UserSubstitution.company_id == cid,
        UserSubstitution.user_id == user_id,
        UserSubstitution.is_active.is_(True),
        UserSubstitution.starts_on <= day,
        UserSubstitution.ends_on >= day))).scalars().all()
    return list(rows)


async def active_principals_for(db: AsyncSession, cid: uuid.UUID,
                                deputy_id: uuid.UUID, on_date=None) -> list[uuid.UUID]:
    """Кого этот человек сегодня официально замещает."""
    from app.models import UserSubstitution

    day = on_date or datetime.now(BUSINESS_TIMEZONE).date()
    rows = (await db.execute(select(UserSubstitution.user_id).where(
        UserSubstitution.company_id == cid,
        UserSubstitution.deputy_id == deputy_id,
        UserSubstitution.is_active.is_(True),
        UserSubstitution.starts_on <= day,
        UserSubstitution.ends_on >= day))).scalars().all()
    return list(rows)


async def may_decide(db: AsyncSession, cid: uuid.UUID, row: DocApproval,
                     actor: User) -> bool:
    """Вправе ли этот человек поставить визу: сам адресат или его заместитель."""
    if row.assignee_id == actor.id:
        return True
    if row.assignee_id is None:
        return False
    return actor.id in await active_deputy_for(db, cid, row.assignee_id)


async def _document_snapshot(db: AsyncSession, doc: DocCard) -> tuple[dict, str]:
    """Зафиксировать реквизиты и точный набор файлов текущего документа."""
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id,
        DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None),
    ).order_by(DocVersion.role, DocVersion.revision, DocVersion.id))).scalars().all()
    snapshot = {
        "card": {
            "id": str(doc.id),
            "kind_id": str(doc.kind_id),
            "title": doc.title,
            "summary": doc.summary,
            "reg_number": doc.reg_number,
            "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
            "organization_id": str(doc.organization_id) if doc.organization_id else None,
            "counterparty_id": str(doc.counterparty_id) if doc.counterparty_id else None,
            "counterparty_name": doc.counterparty_name,
            "external_number": doc.external_number,
            "external_date": doc.external_date.isoformat() if doc.external_date else None,
            "responsible_id": str(doc.responsible_id) if doc.responsible_id else None,
            "signatory_id": str(doc.signatory_id) if doc.signatory_id else None,
            "attrs": doc.attrs or {},
            "current_revision": doc.current_revision,
        },
        "files": [{
            "id": str(v.id),
            "file_id": str(v.file_id),
            "role": v.role,
            "revision": v.revision,
            "file_name": v.file_name,
            "size_bytes": v.size_bytes,
            "sha256": v.sha256,
        } for v in versions],
    }
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return snapshot, hashlib.sha256(canonical).hexdigest()


def _activate(rows: list[DocApproval], now: datetime) -> int:
    """Открыть шаг: параллельный целиком, последовательный по одному человеку."""
    waiting = [row for row in rows if row.status == "waiting"]
    if not waiting:
        return 0
    selected = waiting if rows[0].mode == "parallel" else waiting[:1]
    for row in selected:
        row.status = "pending"
        row.activated_at = now
        row.activation_estimated = False
        row.due_at = now + timedelta(hours=row.sla_hours) if row.sla_hours else None
    return len(selected)


async def start(db: AsyncSession, cid: uuid.UUID, doc: DocCard, route: list[dict],
                actor: User) -> dict[str, Any]:
    """Запустить круг согласования по маршруту вида.

    Живой круг один: повторный запуск открывает следующий, прошлые остаются в
    истории. Иначе на вопрос «сколько кругов прошёл договор» ответить нечем.
    """
    steps = clean_route(route)
    if not steps:
        return {"error": "у вида документа не задан маршрут согласования"}

    prepared: list[tuple[int, dict, list[tuple[str, str, uuid.UUID]]]] = []
    for i, step in enumerate(steps, start=1):
        people = await resolve_actors(db, cid, step["actors"])
        if not people:
            # Пустой шаг — не молчаливый пропуск: маршрут ссылается на роль или
            # отдел, в котором никого нет, и человек должен об этом узнать.
            return {"error": f"на шаге «{step['name']}» некому согласовывать"}
        if step["quorum"].isdigit() and int(step["quorum"]) > len(people):
            return {"error": f"на шаге «{step['name']}» кворум больше числа согласующих"}
        prepared.append((i, step, people))

    round_no = (doc.approval_round or 0) + 1
    now = datetime.now(timezone.utc)
    snapshot, snapshot_hash = await _document_snapshot(db, doc)
    created = 0
    first_step: list[DocApproval] = []
    for i, step, people in prepared:
        for kind, ref, uid in people:
            row = DocApproval(
                company_id=cid, doc_id=doc.id, round=round_no, step_no=i,
                step_code=step["code"], step_name=step["name"], mode=step["mode"],
                quorum=step["quorum"], actor_kind=kind, actor_ref=ref,
                assignee_id=uid, required=step["required"], status="waiting",
                sla_hours=step.get("sla_hours"), document_snapshot=snapshot,
                snapshot_sha256=snapshot_hash)
            db.add(row)
            if i == 1:
                first_step.append(row)
            created += 1

    _activate(first_step, now)

    doc.approval_round = round_no
    doc.approval_status = "pending"
    db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                    actor_name=actor.name or actor.email,
                    to_value=f"круг {round_no}",
                    note=f"согласующих: {created}; пакет: {snapshot_hash[:12]}"))
    await db.flush()
    return {
        "round": round_no, "approvals": created, "steps": len(steps),
        "snapshot_sha256": snapshot_hash,
    }


def step_passed(rows: list[DocApproval]) -> bool:
    """Пройден ли шаг по своему кворуму."""
    if not rows:
        return True
    quorum = rows[0].quorum
    participants = [row for row in rows if row.required] or rows
    approved = sum(1 for r in participants if r.status == "approved")
    if quorum == "any":
        return approved >= 1
    if quorum.isdigit():
        return approved >= int(quorum)
    return all(r.status == "approved" for r in participants)


async def decide(db: AsyncSession, cid: uuid.UUID, doc: DocCard, row: DocApproval,
                 actor: User, approved: bool, comment: str | None) -> dict[str, Any]:
    """Поставить визу или вернуть документ с замечанием.

    Отказ обязан нести причину: без неё автор не понимает, что править, и круг
    запускается заново вслепую.
    """
    if row.status != "pending":
        return {"error": "виза уже поставлена"}
    if not approved and not (comment or "").strip():
        return {"error": "при отказе нужна причина"}

    row.status = "approved" if approved else "rejected"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = actor.id
    row.comment = (comment or "").strip() or None
    await db.flush()

    # Кто фактически расписался. Если это заместитель, лист согласования обязан
    # показывать обоих: иначе через полгода непонятно, чья это виза.
    who = actor.name or actor.email
    if row.assignee_id and row.assignee_id != actor.id:
        boss = await db.get(User, row.assignee_id)
        if boss is not None:
            who = f"{who} (замещает {boss.name or boss.email})"
    db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                    actor_name=who,
                    from_value=row.step_name,
                    to_value="согласовано" if approved else "отказано",
                    note=row.comment))

    if not approved:
        # Отказ гасит текущий круг целиком: возвращать документ по одному шагу,
        # пока остальные ещё смотрят, значит согласовывать уже неактуальное.
        pend = (await db.execute(select(DocApproval).where(
            DocApproval.doc_id == doc.id, DocApproval.round == row.round,
            DocApproval.status.in_(("pending", "waiting"))))).scalars().all()
        for p in pend:
            p.status = "skipped"
        doc.approval_status = "rejected"
        await db.flush()
        return {"status": "rejected", "returned": True}

    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == doc.id,
        DocApproval.round == row.round).order_by(
            DocApproval.step_no, DocApproval.created_at, DocApproval.id))).scalars().all()
    current = [item for item in rows if item.step_no == row.step_no]
    if step_passed(current):
        for item in current:
            if item.status in ("pending", "waiting"):
                item.status = "skipped"
        next_no = next((item.step_no for item in rows if item.step_no > row.step_no), None)
        if next_no is None:
            doc.approval_status = "approved"
        else:
            _activate([item for item in rows if item.step_no == next_no],
                      datetime.now(timezone.utc))
    elif row.mode == "serial":
        _activate(current, datetime.now(timezone.utc))

    left = [item for item in rows if item.status == "pending"]
    if doc.approval_status == "approved":
        doc.approval_status = "approved"
        db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                        actor_name=actor.name or actor.email,
                        to_value="круг пройден"))
    await db.flush()
    return {"status": doc.approval_status, "left": len(left)}


async def cancel(db: AsyncSession, doc: DocCard, actor: User,
                 reason: str) -> dict[str, Any]:
    """Остановить живой круг с явной причиной, не стирая его историю."""
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == doc.id,
        DocApproval.round == doc.approval_round,
        DocApproval.status.in_(("pending", "waiting")),
    ))).scalars().all()
    for row in rows:
        row.status = "skipped"
    doc.approval_status = "none"
    db.add(DocEvent(
        doc_id=doc.id, kind="approval", user_id=actor.id,
        actor_name=actor.name or actor.email, to_value="круг отменён", note=reason,
    ))
    await db.flush()
    return {"cancelled": len(rows), "round": doc.approval_round}


def progress(rows: list[DocApproval]) -> list[dict[str, Any]]:
    """Состояние по шагам: сколько решили и кто молчит.

    Именно этого не хватает в гибридах рынка: при параллельном визировании видно
    «идёт согласование», но не видно, кого ждут.
    """
    by_step: dict[int, list[DocApproval]] = {}
    for r in rows:
        by_step.setdefault(r.step_no, []).append(r)
    out: list[dict[str, Any]] = []
    for step_no in sorted(by_step):
        group = by_step[step_no]
        out.append({
            "step_no": step_no,
            "name": group[0].step_name,
            "mode": group[0].mode,
            "quorum": group[0].quorum,
            "decided": sum(1 for r in group if r.status in ("approved", "rejected")),
            "total": len(group),
            "passed": step_passed(group),
            "active": any(r.status == "pending" for r in group),
            "waiting": [str(r.assignee_id) for r in group if r.status == "pending"],
            "queued": [str(r.assignee_id) for r in group if r.status == "waiting"],
            "rejected": any(r.status == "rejected" for r in group),
        })
    return out
