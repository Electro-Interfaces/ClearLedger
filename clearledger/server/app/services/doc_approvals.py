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
    CompanyRole, Department, DocApproval, DocCard, DocEvent,
    DocSignatureEvidence, DocVersion, User, UserCompany,
)

# Из чего резолвится согласующий. Незнакомый способ отбрасывается санитайзером:
# иначе в справочнике копится мусор, за которым ничего не стоит.
ACTOR_KINDS = ("user", "role", "department", "head_of", "position", "external",
               "partner")
# `external` — человек вне пространства: подрядчик, арендодатель, инспектор. У
# него нет учётки и членства, поэтому в визе он опознаётся почтой (`actor_ref`),
# а `assignee_id` остаётся пустым. Право он получает не на документ, а на один
# шаг — ссылкой с обязательным сроком (`DocShareLink`, purpose="approve").
#
# `partner` — не человек, а ЧУЖАЯ СИСТЕМА: учётная система контрагента, шлюз
# оператора, служба заказчика. Отличие от `external` в способе опознания: там
# одноразовая ссылка человеку на почту, здесь — именной ключ доступа
# (`SpaceInboundKey`), по которому партнёр ходит к нам сам. `assignee_id` так же
# пуст: партнёр — участник процесса, но не участник пространства, и заводить ему
# учётку значило бы дать доступ ко всему остальному.
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
        condition = _clean_condition(raw.get("when"))
        if condition is not None:
            step["when"] = condition
        out.append(step)
    return out


# Условие шага. Одно сравнение, а не выражение: маршрут читают делопроизводители,
# и «если сумма больше 100 000» они проверят глазами, а вложенные скобки — нет.
# Понадобится ветвление сложнее — это будет другой разговор, с деревом решений.
CONDITION_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "set", "unset")
# Свойства карточки, доступные условию наравне с реквизитами вида. Остальное —
# из `attrs`: там живут поля, заданные схемой вида документа.
CONDITION_CARD_FIELDS = (
    "family", "kind_code", "direction", "confidentiality", "counterparty_id",
    "object_id", "subject_ref", "organization_id", "department_id",
)


def _clean_condition(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field") or "").strip()[:40]
    op = str(raw.get("op") or "eq").strip()
    if not field or op not in CONDITION_OPS:
        return None
    out: dict[str, Any] = {"field": field, "op": op}
    if op in ("set", "unset"):
        return out
    value = raw.get("value")
    if op == "in":
        if not isinstance(value, list) or not value:
            return None
        out["value"] = [v for v in value[:50]
                        if isinstance(v, (str, int, float, bool))]
        return out if out["value"] else None
    if not isinstance(value, (str, int, float, bool)):
        return None
    out["value"] = value
    return out


def _condition_value(doc: DocCard, field: str) -> Any:
    if field in CONDITION_CARD_FIELDS:
        value = getattr(doc, field, None)
        return None if value is None else str(value)
    return (doc.attrs or {}).get(field)


def step_applies(step: dict, doc: DocCard) -> bool:
    """Нужен ли шаг этому документу.

    Шаг без условия нужен всегда — маршруты, написанные до появления условий,
    обязаны вести себя ровно как раньше.

    Несравнимое значение (в числовом сравнении лежит текст) считаем «условие не
    выполнено», а не ошибкой: маршрут не должен падать из-за того, что человек
    оставил реквизит пустым. Цена ошибки разная — лишний согласующий заметен и
    поправим, пропущенный молча не заметен никем.
    """
    condition = step.get("when")
    if not condition:
        return True
    value = _condition_value(doc, condition["field"])
    op = condition["op"]
    if op == "set":
        return value not in (None, "")
    if op == "unset":
        return value in (None, "")
    expected = condition.get("value")
    if op == "in":
        return any(str(value) == str(item) for item in expected)
    if op in ("eq", "ne"):
        same = str(value) == str(expected)
        return same if op == "eq" else not same
    try:
        left, right = float(value), float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    return left <= right


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

    def add_external(ref: str) -> None:
        """Внешний согласующий: человека в базе нет, есть адрес, на который
        уйдёт ссылка. Дедупликация по адресу, а не по идентификатору."""
        key = ref.strip().lower()
        if key and not any(k == "external" and r.strip().lower() == key
                           for k, r, _ in out):
            out.append(("external", ref.strip(), None))

    for a in actors:
        by, ref = a.get("by"), a.get("ref")
        if by == "external":
            # Адрес проверяем грубо: пустое и не похожее на почту отсекаем, но
            # доставку проверит почтовый сервер, а не мы.
            if isinstance(ref, str) and "@" in ref and len(ref) <= 320:
                add_external(ref)
            continue
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
                UserCompany.department_id == dep_id).order_by(UserCompany.user_id))).scalars().all()
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
                UserCompany.role_id == role_id).order_by(UserCompany.user_id))).scalars().all()
            for uid in rows:
                add("role", ref, uid)
        elif by == "position":
            rows = (await db.execute(select(UserCompany.user_id).where(
                UserCompany.company_id == cid,
                UserCompany.position == ref).order_by(UserCompany.user_id))).scalars().all()
            for uid in rows:
                add("position", ref, uid)
        elif by == "partner":
            # Ключ проверяем на месте: отозванный партнёр не должен появляться в
            # круге вообще. Иначе шаг откроется на того, кто уже не может к нам
            # прийти, и маршрут встанет молча — без единого признака, почему.
            from app.models import SpaceInboundKey

            try:
                key_id = uuid.UUID(ref)
            except (ValueError, TypeError):
                continue
            key = (await db.execute(select(SpaceInboundKey).where(
                SpaceInboundKey.id == key_id,
                SpaceInboundKey.company_id == cid,
                SpaceInboundKey.revoked_at.is_(None)))).scalar_one_or_none()
            if key is not None and not any(
                    k == "partner" and r == ref for k, r, _ in out):
                out.append(("partner", ref, None))
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


async def _document_snapshot(db: AsyncSession, doc: DocCard,
                             route: list[dict] | None = None) -> tuple[dict, str]:
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
            "object_id": doc.object_id,
            "confidentiality": doc.confidentiality,
            "responsible_id": str(doc.responsible_id) if doc.responsible_id else None,
            "signatory_id": str(doc.signatory_id) if doc.signatory_id else None,
            "due_at": doc.due_at.isoformat() if doc.due_at else None,
            "case_id": str(doc.case_id) if doc.case_id else None,
            "storage_until": doc.storage_until.isoformat() if doc.storage_until else None,
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
    if route is not None:
        snapshot["approval_route"] = [{
            "step_no": index,
            "code": step["code"],
            "name": step["name"],
            "step_kind": "sign" if step.get("step_kind") == "sign" else "approve",
            "mode": step["mode"],
            "quorum": step["quorum"],
            "required": step["required"],
        } for index, step in enumerate(route, start=1)]
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


async def preview_route(db: AsyncSession, cid: uuid.UUID, doc: DocCard, route: list[dict],
                        *, resolved=None):
    steps = [step for step in clean_route(route) if step_applies(step, doc)]
    problems = [] if steps else ["По условиям документа нет шагов согласования"]
    rows = []
    for number, step in enumerate(steps, start=1):
        actors = (resolved[number - 1] if resolved is not None
                  else await resolve_actors(db, cid, step["actors"]))
        if not actors:
            problems.append(f"На шаге «{step['name']}» некому согласовывать")
        if step["quorum"].isdigit() and int(step["quorum"]) > len(actors):
            problems.append(f"На шаге «{step['name']}» кворум больше числа согласующих")
        people = []
        for actor_kind, ref, uid in actors:
            person = await db.get(User, uid) if uid else None
            people.append({"id": str(uid) if uid else None, "kind": actor_kind,
                           "name": (person.name or person.email) if person else ref})
        rows.append({"number": number, "name": step["name"],
                     "mode": step["mode"], "quorum": step["quorum"],
                     "step_kind": step.get("step_kind", "approve"),
                     "sla_hours": step.get("sla_hours"), "people": people})
    token = hashlib.sha256(json.dumps(
        {"route": steps, "steps": rows}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"steps": rows, "problems": problems, "route_token": token}


async def start(db: AsyncSession, cid: uuid.UUID, doc: DocCard, route: list[dict],
                actor: User | None, *, expected_route_token: str | None = None) -> dict[str, Any]:
    """Запустить круг согласования по маршруту вида.

    Живой круг один: повторный запуск открывает следующий, прошлые остаются в
    истории. Иначе на вопрос «сколько кругов прошёл договор» ответить нечем.

    `actor` пуст, когда круг запустил узел маршрута процесса. Заводить ради этого
    техническую учётку не стали: в следе документа честнее видеть «Процесс», чем
    человекообразного пользователя, которого не существует.
    """
    steps = clean_route(route)
    if not steps:
        return {"error": "у вида документа не задан маршрут согласования"}
    # Условия отбираются ДО нумерации шагов: номер должен идти подряд по тому
    # маршруту, который документ реально прошёл, иначе в листе согласования
    # появятся дыры, а снимок круга перестанет совпадать с историей.
    steps = [step for step in steps if step_applies(step, doc)]
    if not steps:
        return {"error": "по условиям маршрута не осталось ни одного шага"}

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

    if expected_route_token is not None:
        preview = await preview_route(db, cid, doc, steps,
                                      resolved=[people for _, _, people in prepared])
        if preview["route_token"] != expected_route_token:
            return {"error": "Состав согласующих изменился. Обновите предпросмотр маршрута",
                    "conflict": True}

    round_no = (doc.approval_round or 0) + 1
    now = datetime.now(timezone.utc)
    snapshot, snapshot_hash = await _document_snapshot(db, doc, steps)
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
    db.add(DocEvent(doc_id=doc.id, kind="approval",
                    user_id=actor.id if actor else None,
                    actor_name=(actor.name or actor.email) if actor else "Процесс",
                    to_value=f"круг {round_no}",
                    note=f"согласующих: {created}; пакет: {snapshot_hash[:12]}"))
    await db.flush()
    return {
        "round": round_no, "approvals": created, "steps": len(steps),
        "snapshot_sha256": snapshot_hash,
    }


async def lock_round(db: AsyncSession, cid: uuid.UUID, doc_id: uuid.UUID,
                     round_no: int) -> list[DocApproval]:
    if round_no <= 0:
        return []
    return list((await db.execute(select(DocApproval).where(
        DocApproval.company_id == cid,
        DocApproval.doc_id == doc_id,
        DocApproval.round == round_no,
    ).order_by(DocApproval.id).execution_options(
        populate_existing=True).with_for_update())).scalars().all())


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


def step_kind(row: DocApproval) -> str:
    route = (row.document_snapshot or {}).get("approval_route") or []
    for step in route:
        if (step.get("step_no") == row.step_no
                or step.get("code") == row.step_code):
            return "sign" if step.get("step_kind") == "sign" else "approve"
    return "approve"


async def decide(db: AsyncSession, cid: uuid.UUID, doc: DocCard, row: DocApproval,
                 actor: User, approved: bool, comment: str | None,
                 round_rows: list[DocApproval] | None = None) -> dict[str, Any]:
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
    if approved and step_kind(row) == "sign":
        db.add(DocSignatureEvidence(
            company_id=cid,
            doc_id=doc.id,
            approval_id=row.id,
            method=("external_link" if row.actor_kind == "external"
                    else "internal_approval"),
            provider="Track",
            signer_id=actor.id,
            signer_name=actor.name or actor.email,
            represented_signer_id=(row.assignee_id
                                   if row.assignee_id != actor.id else None),
            snapshot_sha256=row.snapshot_sha256 or "0" * 64,
            document_snapshot=row.document_snapshot or {},
            verification_status="verified",
            verified_at=row.decided_at,
            evidence={
                "step_code": row.step_code,
                "step_name": row.step_name,
                "decision": "approved",
                # Чем опознали подписанта. Для внешнего участника это ссылка со
                # сроком, а не сеанс, и называть это сеансом нельзя: в споре
                # разница между ними и есть весь вопрос.
                "identity_source": ("external_link" if row.actor_kind == "external"
                                    else "authenticated_session"),
            },
            signed_at=row.decided_at,
        ))
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
        pend = [item for item in round_rows or []
                if item.status in ("pending", "waiting")]
        if round_rows is None:
            pend = (await db.execute(select(DocApproval).where(
                DocApproval.doc_id == doc.id, DocApproval.round == row.round,
                DocApproval.status.in_(("pending", "waiting"))))).scalars().all()
        for p in pend:
            p.status = "skipped"
        doc.approval_status = "rejected"
        # Исход круга ждёт узел маршрута, если круг запустил он. Отметка ставится
        # здесь, внутри закрывающей транзакции: доставка пойдёт фоном, но потерять
        # исход нельзя — второй раз визы никто собирать не станет.
        from app.services import approval_requests  # локально: обратный импорт

        await approval_requests.mark_outcome(db, doc.id, "rejected")
        # Подписчикам шины — тем же движением и в той же транзакции. Точка
        # выбрана не рядом с отметкой процесса случайно: здесь уже доказано, что
        # мы внутри закрывающей транзакции круга.
        from app.services import space_events  # локально: обратный импорт

        await space_events.publish(
            db, doc.company_id, "doc.rejected", str(doc.id),
            space_events.doc_data(doc, actor, round=row.round,
                                  step=row.step_name or None,
                                  comment=row.comment))
        await db.flush()
        return {"status": "rejected", "returned": True}

    rows = round_rows
    if rows is None:
        rows = (await db.execute(select(DocApproval).where(
            DocApproval.doc_id == doc.id,
            DocApproval.round == row.round).order_by(
                DocApproval.step_no, DocApproval.created_at, DocApproval.id))).scalars().all()
    else:
        rows = sorted(rows, key=lambda item: (
            item.step_no, item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.id))
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
        from app.services import approval_requests  # локально: обратный импорт

        await approval_requests.mark_outcome(db, doc.id, "approved")
        from app.services import space_events  # локально: обратный импорт

        await space_events.publish(
            db, doc.company_id, "doc.approval.completed", str(doc.id),
            space_events.doc_data(doc, actor, round=row.round,
                                  outcome="approved"))
    await db.flush()
    return {"status": doc.approval_status, "left": len(left)}


async def cancel(db: AsyncSession, doc: DocCard, actor: User,
                 reason: str, round_rows: list[DocApproval] | None = None) -> dict[str, Any]:
    """Остановить живой круг с явной причиной, не стирая его историю."""
    rows = [row for row in round_rows or []
            if row.status in ("pending", "waiting")]
    if round_rows is None:
        rows = (await db.execute(select(DocApproval).where(
            DocApproval.doc_id == doc.id,
            DocApproval.round == doc.approval_round,
            DocApproval.status.in_(("pending", "waiting")),
        ))).scalars().all()
    for row in rows:
        row.status = "skipped"
    doc.approval_status = "none"
    from app.services import approval_requests  # локально: обратный импорт

    # Отменённый круг — тоже исход: процесс, ждущий виз, иначе стоял бы вечно.
    await approval_requests.mark_outcome(db, doc.id, "cancelled")
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
            "step_kind": step_kind(group[0]),
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
