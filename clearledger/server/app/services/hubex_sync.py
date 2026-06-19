"""
Синхронизация HubEx FSM в Postgres — для Сервисного центра (netservice).

В отличие от hubex_service.get_asset_tasks (поштучно, для окна станции), здесь —
СЕТЕВОЙ синк: все заявки аккаунта тянем постранично (заголовок Range), upsert в
hubex_tasks (raw + промо), резолв asset_id → наша точка/регион; плюс справочники
(статусы/типы/виды работ/критичность/объекты/подрядчики). Аналитика читает БД, а
не дёргает API на каждый запрос.

ВАЖНО про API HubEx:
- Ответы коллекций — dict {hubex_id: obj}; id лежит в КЛЮЧЕ словаря (в объектах
  заявок/статусов/типов поля id нет). Поэтому везде берём ключ как hubex_id.
- Range 1-based и инклюзивный: запрос items=0-499 → Content-Range items=1-499/TOTAL
  (499 элементов). Пагинация двигается по B из Content-Range с перекрытием в 1
  элемент (upsert идемпотентен) — гарантирует отсутствие пропусков на стыке.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    HubexAsset,
    HubexRef,
    HubexTask,
    ServiceLocation,
    SupportSyncCursor,
)
from app.services import hubex_service

PAGE = 500
_PAGE_GUARD = 200  # backstop на число страниц
_CR_RE = re.compile(r"items[ =](\d+)-(\d+)/(\d+|\*)")
_TASK_PROMO = (
    "number", "raw", "task_type", "work_type", "work_type_erp_id", "status",
    "status_color", "stage", "criticality", "criticality_color", "asset_id",
    "asset_name", "contractor_company", "contractor_id", "assignee",
    "assignee_is_tech", "location_id", "region_id", "ts_created", "ts_requested",
    "ts_assigned", "ts_deadline", "ts_completed", "ts_closed", "is_overdue",
    "is_rated", "child_count", "last_modified", "synced_at",
)


def _dt(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _pairs(data: Any) -> list[tuple[str | None, dict]]:
    """Ответ HubEx → [(hubex_id_из_ключа, obj)]. list → ключи None."""
    if isinstance(data, dict):
        return [(str(k), v) for k, v in data.items() if isinstance(v, dict)]
    return [(None, v) for v in (data or []) if isinstance(v, dict)]


def _norm_task(key: str | None, t: dict, asset_map: dict[int, tuple]) -> dict[str, Any]:
    st = t.get("taskStatus") or {}
    stage = t.get("taskStage") or {}
    cr = t.get("actualCriticality") or {}
    tt = t.get("taskType") or {}
    wt = t.get("workType") or {}
    asset = t.get("asset") or {}
    contractor = t.get("company") or {}
    assignee = t.get("assignedTo") or {}
    ts = t.get("timesheet") or {}
    name = " ".join(x for x in (assignee.get("lastName"), assignee.get("firstName")) if x).strip()
    asset_id = asset.get("id")
    loc_id, region_id = asset_map.get(asset_id, (None, None)) if asset_id is not None else (None, None)
    ts_deadline = _dt(ts.get("deadline"))
    ts_closed = _dt(ts.get("closed"))
    is_overdue = bool(ts_deadline and not ts_closed and ts_deadline < datetime.now())
    return {
        "id": uuid.uuid4(),
        "hubex_id": str(t.get("id") or key or t.get("number")),
        "number": t.get("number"),
        "raw": t,
        "task_type": tt.get("name"),
        "work_type": wt.get("name"),
        "work_type_erp_id": str(wt.get("erpID")) if wt.get("erpID") is not None else None,
        "status": st.get("name"),
        "status_color": st.get("color"),
        "stage": stage.get("name"),
        "criticality": cr.get("name"),
        "criticality_color": cr.get("color"),
        "asset_id": asset_id,
        "asset_name": asset.get("name"),
        "contractor_company": contractor.get("name"),
        "contractor_id": contractor.get("id"),
        "assignee": name or None,
        "assignee_is_tech": assignee.get("isTechnician"),
        "location_id": loc_id,
        "region_id": region_id,
        "ts_created": _dt(ts.get("created")),
        "ts_requested": _dt(ts.get("requested")),
        "ts_assigned": _dt(ts.get("assigned")),
        "ts_deadline": ts_deadline,
        "ts_completed": _dt(ts.get("completed")),
        "ts_closed": ts_closed,
        "is_overdue": is_overdue,
        "is_rated": t.get("isRated"),
        "child_count": t.get("childCount"),
        "last_modified": _dt(t.get("lastModified")),
        "synced_at": datetime.now(),
    }


async def _asset_map(db: AsyncSession, company_id: uuid.UUID) -> dict[int, tuple]:
    """asset_id (HubEx) → (location_id, region_id) по extra_metadata.hubexAssetId."""
    rows = await db.execute(
        select(ServiceLocation.id, ServiceLocation.region_id, ServiceLocation.extra_metadata)
        .where(ServiceLocation.company_id == company_id)
    )
    out: dict[int, tuple] = {}
    for sid, rid, meta in rows.all():
        aid = (meta or {}).get("hubexAssetId")
        if aid in (None, ""):
            continue
        try:
            out[int(aid)] = (sid, rid)
        except (ValueError, TypeError):
            continue
    return out


async def _fetch_page(client: httpx.AsyncClient, token: str, path: str, frm: int, count: int):
    """Возвращает (data, a, b, total) — границы из Content-Range (1-based, инкл.)."""
    s = get_settings()
    r = await client.get(
        f"{s.hubex_base_url}{path}",
        headers={**hubex_service._headers(token), "Range": f"items={frm}-{frm + count - 1}"},
    )
    if r.status_code not in (200, 206):
        r.raise_for_status()
    a = b = total = None
    m = _CR_RE.search(r.headers.get("Content-Range", ""))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        total = None if m.group(3) == "*" else int(m.group(3))
    return r.json(), a, b, total


async def sync_tasks(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Полный идемпотентный синк всех заявок аккаунта в hubex_tasks (upsert)."""
    if not hubex_service.is_configured():
        return {"configured": False, "upserted": 0, "total": 0}
    token = await hubex_service._access_token()
    asset_map = await _asset_map(db, company_id)
    upserted = 0
    total = None
    frm = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(_PAGE_GUARD):
            data, _a, b, page_total = await _fetch_page(client, token, "/WORK/Tasks", frm, PAGE)
            if page_total is not None:
                total = page_total
            pairs = _pairs(data)
            if not pairs:
                break
            rows = [_norm_task(k, o, asset_map) for k, o in pairs]
            await _upsert_tasks(db, company_id, rows)
            upserted += len(rows)
            if b is None:  # нет Content-Range — двигаемся по факту
                if len(pairs) < PAGE:
                    break
                frm += len(pairs)
            else:
                if total is not None and b >= total:
                    break
                frm = b  # перекрытие в 1 элемент на стыке (upsert идемпотентен)
    await _bump_cursor(db, company_id, "tasks")
    await db.commit()
    return {"configured": True, "upserted": upserted, "total": total or upserted}


async def _upsert_tasks(db: AsyncSession, company_id: uuid.UUID, rows: list[dict]) -> None:
    if not rows:
        return
    # Дедуп внутри батча по hubex_id (перекрытие страниц может дать дубль в одном INSERT).
    uniq: dict[str, dict] = {}
    for r in rows:
        r["company_id"] = company_id
        uniq[r["hubex_id"]] = r
    stmt = pg_insert(HubexTask).values(list(uniq.values()))
    upd = {c: stmt.excluded[c] for c in _TASK_PROMO}
    stmt = stmt.on_conflict_do_update(
        index_elements=[HubexTask.company_id, HubexTask.hubex_id], set_=upd
    )
    await db.execute(stmt)


async def _upsert_refs(db: AsyncSession, company_id: uuid.UUID, ref_kind: str,
                       pairs: list[tuple[str | None, dict]], pick: Callable) -> int:
    """pick(key, obj) → (hubex_id, name, color, erp_id). Upsert в hubex_refs."""
    uniq: dict[str, dict] = {}
    for key, obj in pairs:
        hid, name, color, erp = pick(key, obj)
        if hid in (None, ""):
            continue
        uniq[str(hid)] = {
            "id": uuid.uuid4(), "company_id": company_id, "ref_kind": ref_kind,
            "hubex_id": str(hid), "name": name, "color": color, "erp_id": erp,
            "raw": obj, "synced_at": datetime.now(),
        }
    if not uniq:
        return 0
    stmt = pg_insert(HubexRef).values(list(uniq.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=[HubexRef.company_id, HubexRef.ref_kind, HubexRef.hubex_id],
        set_={c: stmt.excluded[c] for c in ("name", "color", "erp_id", "raw", "synced_at")},
    )
    await db.execute(stmt)
    return len(uniq)


async def sync_refs(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Синк справочников HubEx (статусы/типы/виды работ/критичность/подрядчики) + объекты."""
    if not hubex_service.is_configured():
        return {"configured": False}
    token = await hubex_service._access_token()
    counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        async def grab(path: str) -> list[tuple[str | None, dict]]:
            data, _a, _b, _t = await _fetch_page(client, token, path, 0, 1000)
            return _pairs(data)

        # id справочников лежит в КЛЮЧЕ словаря → берём key (или fallback на поле).
        counts["status"] = await _upsert_refs(
            db, company_id, "status", await grab("/WORK/TaskStatuses"),
            lambda k, o: (k or o.get("id"), o.get("name"), o.get("color"), None))
        counts["task_type"] = await _upsert_refs(
            db, company_id, "task_type", await grab("/WORK/TaskTypes"),
            lambda k, o: (k or o.get("id"), o.get("name"), None, None))
        counts["work_type"] = await _upsert_refs(
            db, company_id, "work_type", await grab("/WORK/WorkTypes"),
            lambda k, o: (k or o.get("id"), o.get("name"), None,
                          str(o.get("erpID")) if o.get("erpID") is not None else None))
        counts["criticality"] = await _upsert_refs(
            db, company_id, "criticality", await grab("/SLA/Criticalities"),
            lambda k, o: (k or o.get("id") or o.get("name"), o.get("name"), o.get("color"), None))
        counts["company"] = await _upsert_refs(
            db, company_id, "company", await grab("/ES/Companies"),
            lambda k, o: (k or o.get("id"), o.get("name"), None, None))
        counts["assets"] = await _upsert_assets(db, company_id, await grab("/ES/Assets"))
    await _bump_cursor(db, company_id, "refs")
    await db.commit()
    return {"configured": True, "counts": counts}


async def _upsert_assets(db: AsyncSession, company_id: uuid.UUID,
                         pairs: list[tuple[str | None, dict]]) -> int:
    rows_loc = await db.execute(
        select(ServiceLocation.id, ServiceLocation.extra_metadata)
        .where(ServiceLocation.company_id == company_id)
    )
    by_asset: dict[str, str] = {}
    for sid, meta in rows_loc.all():
        aid = (meta or {}).get("hubexAssetId")
        if aid not in (None, ""):
            by_asset[str(aid)] = sid

    def _nm(v: Any) -> Any:
        return v.get("name") if isinstance(v, dict) else v

    uniq: dict[str, dict] = {}
    for key, it in pairs:
        hid = it.get("id") or key
        if hid in (None, ""):
            continue
        uniq[str(hid)] = {
            "id": uuid.uuid4(), "company_id": company_id, "hubex_id": str(hid),
            "name": it.get("name"), "raw": it,
            "location_id": by_asset.get(str(hid)),
            "serial_number": it.get("serialNumber"),
            "manufacturer": _nm(it.get("manufacturer")),
            "model": _nm(it.get("model")),
            "synced_at": datetime.now(),
        }
    if not uniq:
        return 0
    stmt = pg_insert(HubexAsset).values(list(uniq.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=[HubexAsset.company_id, HubexAsset.hubex_id],
        set_={c: stmt.excluded[c] for c in
              ("name", "raw", "location_id", "serial_number", "manufacturer", "model", "synced_at")},
    )
    await db.execute(stmt)
    return len(uniq)


async def _bump_cursor(db: AsyncSession, company_id: uuid.UUID, doc_kind: str) -> None:
    now = datetime.now()
    stmt = pg_insert(SupportSyncCursor).values(
        id=uuid.uuid4(), company_id=company_id, source_type="hubex_fsm",
        doc_kind=doc_kind, last_modified=now, last_run_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SupportSyncCursor.company_id, SupportSyncCursor.source_type,
                        SupportSyncCursor.doc_kind],
        set_={"last_run_at": now},
    )
    await db.execute(stmt)


async def sync_all(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Полный синк: справочники (включая объекты) → заявки."""
    refs = await sync_refs(db, company_id)
    tasks = await sync_tasks(db, company_id)
    return {"refs": refs, "tasks": tasks}
