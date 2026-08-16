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

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CompanyRole, Department, DocApproval, DocCard, DocEvent, User, UserCompany,
)

# Из чего резолвится согласующий. Незнакомый способ отбрасывается санитайзером:
# иначе в справочнике копится мусор, за которым ничего не стоит.
ACTOR_KINDS = ("user", "role", "department", "head_of", "position")
MODES = ("serial", "parallel")


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
                add("user", ref, uuid.UUID(ref))
            except (ValueError, TypeError):
                continue
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


async def start(db: AsyncSession, cid: uuid.UUID, doc: DocCard, route: list[dict],
                actor: User) -> dict[str, Any]:
    """Запустить круг согласования по маршруту вида.

    Живой круг один: повторный запуск открывает следующий, прошлые остаются в
    истории. Иначе на вопрос «сколько кругов прошёл договор» ответить нечем.
    """
    steps = clean_route(route)
    if not steps:
        return {"error": "у вида документа не задан маршрут согласования"}

    round_no = (doc.approval_round or 0) + 1
    now = datetime.now(timezone.utc)
    created = 0
    for i, step in enumerate(steps, start=1):
        people = await resolve_actors(db, cid, step["actors"])
        if not people:
            # Пустой шаг — не молчаливый пропуск: маршрут ссылается на роль или
            # отдел, в котором никого нет, и человек должен об этом узнать.
            return {"error": f"на шаге «{step['name']}» некому согласовывать"}
        due = now + timedelta(hours=step["sla_hours"]) if step.get("sla_hours") else None
        for kind, ref, uid in people:
            db.add(DocApproval(
                company_id=cid, doc_id=doc.id, round=round_no, step_no=i,
                step_code=step["code"], step_name=step["name"], mode=step["mode"],
                quorum=step["quorum"], actor_kind=kind, actor_ref=ref,
                assignee_id=uid, required=step["required"], due_at=due))
            created += 1

    doc.approval_round = round_no
    doc.approval_status = "pending"
    db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                    actor_name=actor.name or actor.email,
                    to_value=f"круг {round_no}", note=f"согласующих: {created}"))
    await db.flush()
    return {"round": round_no, "approvals": created, "steps": len(steps)}


def step_passed(rows: list[DocApproval]) -> bool:
    """Пройден ли шаг по своему кворуму."""
    if not rows:
        return True
    quorum = rows[0].quorum
    approved = sum(1 for r in rows if r.status == "approved")
    if quorum == "any":
        return approved >= 1
    if quorum.isdigit():
        return approved >= int(quorum)
    return all(r.status in ("approved", "skipped") for r in rows)


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

    db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                    actor_name=actor.name or actor.email,
                    from_value=row.step_name,
                    to_value="согласовано" if approved else "отказано",
                    note=row.comment))

    if not approved:
        # Отказ гасит текущий круг целиком: возвращать документ по одному шагу,
        # пока остальные ещё смотрят, значит согласовывать уже неактуальное.
        pend = (await db.execute(select(DocApproval).where(
            DocApproval.doc_id == doc.id, DocApproval.round == row.round,
            DocApproval.status == "pending"))).scalars().all()
        for p in pend:
            p.status = "skipped"
        doc.approval_status = "rejected"
        if doc.status == "registered":
            doc.status = "draft"
        await db.flush()
        return {"status": "rejected", "returned": True}

    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == doc.id,
        DocApproval.round == row.round))).scalars().all()
    left = [r for r in rows if r.status == "pending"]
    if not left:
        doc.approval_status = "approved"
        db.add(DocEvent(doc_id=doc.id, kind="approval", user_id=actor.id,
                        actor_name=actor.name or actor.email,
                        to_value="круг пройден"))
    await db.flush()
    return {"status": "approved", "left": len(left)}


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
            "decided": sum(1 for r in group if r.status != "pending"),
            "total": len(group),
            "passed": step_passed(group),
            "waiting": [str(r.assignee_id) for r in group if r.status == "pending"],
            "rejected": any(r.status == "rejected" for r in group),
        })
    return out
