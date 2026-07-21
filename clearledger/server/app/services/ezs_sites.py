"""Банк ЗУ — площадки под установку ЭЗС (девелоперский пайплайн).

Учёт МЕСТ, где сеть строится, на стадиях: prospect (в проработке/согласовании)
→ in_work (в работе) → archive (в архиве). Источник — сводный Excel «Банк
данных ЗУ» (3 листа = стадии, ~55 колонок про недвижимость и техприсоединение).

Ключевые поля кладём в колонки (фильтры/агрегаты), полный исходный ряд — в raw
JSONB (ничего не теряем). Импорт «сводного» файла — REPLACE-ALL по компании:
файл и есть источник истины, дедуп-ключа у площадок нет.

Экономические поля в файле разнородны («800 т.р.», «9р.», «по запросу») —
парсим best-effort, при неудаче NULL; агрегаты по деньгам подписываем «по
распознанным».
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite

# Лист Excel → стадия пайплайна.
SHEET_STAGE = {
    "зу в работе": "in_work",
    "зу (архив)": "archive",
    "зу архив": "archive",
    "согласованные": "prospect",
}
STAGE_LABELS = {"prospect": "В проработке", "in_work": "В работе", "archive": "В архиве"}
STAGE_ORDER = ["prospect", "in_work", "archive"]


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


# Заголовок (нормализованный) → поле модели. Порядок ВАЖЕН: специфичные —
# раньше общих («статус согласования» до «статус»).
def _match_field(h: str) -> str | None:
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("received_date", ("дата поступления", "дата прихода")),
        ("ownership", ("статус зу", "собственность/аренда")),
        ("tu_status", ("статус согласования",)),
        ("status_raw", ("статус",)),
        ("place_kind", ("признак",)),
        ("install_place", ("место установки",)),
        ("full_address", ("полный адрес",)),
        ("region", ("регион",)),
        ("city", ("город",)),
        ("route", ("трасса",)),
        ("coords_raw", ("координат",)),
        ("map_url", ("ссылка на карт",)),
        ("owner", ("собственник",)),
        ("brand", ("бренд",)),
        ("area_m2", ("площадь",)),
        ("free_power_kwt", ("свободная мощность",)),
        ("rent_cost_month", ("стоимость аренды",)),
        ("connection_cost", ("итого затраты на подключ",)),
        ("planned_power_kwt", ("мощность эзс к установке",)),
        ("planned_ezs_count", ("кол-во эзс",)),
        ("ports_gbt", ("порты эзс - gbt", "порты эзс gbt")),
        ("ports_ccs", ("порты эзс - ccs", "порты эзс ccs")),
        ("ports_chademo", ("порты эзс - chademo", "порты эзс chademo")),
        ("ports_type", ("порты эзс - type", "порты эзс type")),
        ("supplier", ("поставщик",)),
        ("contractor", ("подрядчик",)),
        ("tech_conn_type", ("тип технологического присоед",)),
        ("dop_service", ("доп.сервис", "доп сервис")),
        ("comment", ("комментарий",)),
        ("address", ("адрес",)),   # после «полный адрес»
    ]
    for field, keys in checks:
        if any(h.startswith(k) or k in h for k in keys):
            return field
    return None


def _num(v: Any) -> float | None:
    """Число из разнородной строки: «800 т.р.»→800000, «9р.»→9, «по запросу»→None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace("\xa0", " ")
    if not s or s in ("-", "—", "по запросу", "н/д", "нет данных", "нет"):
        return None
    mult = 1.0
    if "млн" in s:
        mult = 1e6
    elif "т.р" in s or "тыс" in s or "т руб" in s:
        mult = 1e3
    m = re.search(r"[-+]?\d[\d ]*(?:[.,]\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", "").replace(",", ".")) * mult
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    n = _num(v)
    return int(round(n)) if n is not None else None


def _coords(v: Any) -> tuple[float | None, float | None]:
    """(lat, lon) из «56.83, 60.59» / «59.57 150.80». DMS/мусор → (None, None)."""
    if v is None:
        return (None, None)
    nums = re.findall(r"[-+]?\d{1,3}[.,]\d{3,}", str(v))
    if len(nums) >= 2:
        try:
            lat = float(nums[0].replace(",", ".")); lon = float(nums[1].replace(",", "."))
        except ValueError:
            return (None, None)
        if 40 <= lat <= 82 and 18 <= lon <= 190:   # правдоподобный охват РФ
            return (lat, lon)
    return (None, None)


def _s(v: Any, limit: int | None = None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:limit] if limit else s


async def import_sites_xlsx(db: AsyncSession, company_id, content: bytes, dry_run: bool) -> dict[str, Any]:
    """Импорт сводного «Банк данных ЗУ» (3 листа → стадии). REPLACE-ALL по компании."""
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parsed: list[EzsSite] = []
    report: dict[str, Any] = {"dryRun": dry_run, "sheets": [], "total": 0, "withCoords": 0, "unknownSheets": []}

    for sn in wb.sheetnames:
        ws = wb[sn]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        stage = SHEET_STAGE.get(_norm(sn))
        if stage is None:
            report["unknownSheets"].append(sn)
            continue
        # заголовок — первая строка с ≥5 распознанными колонками
        header_idx, colmap = None, {}
        for ri, row in enumerate(rows[:5]):
            cm = {}
            for ci, cell in enumerate(row):
                f = _match_field(_norm(cell))
                if f and f not in cm.values():
                    cm[ci] = f
            if len(cm) >= 5:
                header_idx, colmap = ri, cm
                break
        if header_idx is None:
            report["sheets"].append({"sheet": sn, "stage": stage, "rows": 0, "note": "заголовок не найден"})
            continue
        headers = {ci: (str(rows[header_idx][ci]).strip() if rows[header_idx][ci] else f"col{ci}")
                   for ci in range(len(rows[header_idx]))}

        cnt = 0
        for ri, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            vals: dict[str, Any] = {}
            raw: dict[str, str] = {}
            for ci, cell in enumerate(row):
                if cell is None or str(cell).strip() == "":
                    continue
                raw[headers.get(ci, f"col{ci}")] = str(cell).strip()
                f = colmap.get(ci)
                if f:
                    vals[f] = cell
            # строка «пустая по сути» (только служебное «Требует проверки») — пропускаем
            meaningful = {k for k in vals if k not in ("status_raw",)}
            if not meaningful and not raw.get("Регион"):
                continue
            lat, lon = _coords(vals.get("coords_raw"))
            site = EzsSite(
                company_id=company_id, stage=stage, source_sheet=sn, row_no=ri,
                status_raw=_s(vals.get("status_raw"), 80),
                received_date=_iso_date(vals.get("received_date")),
                region=_s(vals.get("region"), 160), city=_s(vals.get("city"), 160),
                address=_s(vals.get("address")), full_address=_s(vals.get("full_address")),
                place_kind=_s(vals.get("place_kind"), 20), install_place=_s(vals.get("install_place"), 300),
                route=_s(vals.get("route"), 80), lat=lat, lon=lon,
                coords_raw=_s(vals.get("coords_raw"), 120), map_url=_s(vals.get("map_url")),
                owner=_s(vals.get("owner"), 400), brand=_s(vals.get("brand"), 160),
                area_m2=_num(vals.get("area_m2")), ownership=_s(vals.get("ownership"), 60),
                free_power_kwt=_s(vals.get("free_power_kwt"), 80),
                connection_cost=_num(vals.get("connection_cost")),
                rent_cost_month=_num(vals.get("rent_cost_month")),
                planned_power_kwt=_num(vals.get("planned_power_kwt")),
                planned_ezs_count=_int(vals.get("planned_ezs_count")),
                ports_gbt=_s(vals.get("ports_gbt"), 40), ports_ccs=_s(vals.get("ports_ccs"), 40),
                ports_chademo=_s(vals.get("ports_chademo"), 40), ports_type=_s(vals.get("ports_type"), 40),
                supplier=_s(vals.get("supplier"), 300), contractor=_s(vals.get("contractor"), 400),
                tu_status=_s(vals.get("tu_status")), tech_conn_type=_s(vals.get("tech_conn_type"), 300),
                dop_service=_s(vals.get("dop_service"), 300), comment=_s(vals.get("comment")),
                raw=raw,
            )
            parsed.append(site)
            if lat is not None:
                report["withCoords"] += 1
            cnt += 1
        report["sheets"].append({"sheet": sn, "stage": stage, "rows": cnt})
    wb.close()

    report["total"] = len(parsed)
    if not dry_run:
        await db.execute(delete(EzsSite).where(EzsSite.company_id == company_id))
        db.add_all(parsed)
        await db.commit()
    return report


def _iso_date(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # openpyxl отдаёт datetime для дат-ячеек
    return s[:10]


async def list_sites(
    db: AsyncSession, company_id, *, stage: str | None = None, region: str | None = None,
    search: str | None = None, page: int = 1, page_size: int = 100,
) -> dict[str, Any]:
    S = EzsSite
    conds = [S.company_id == company_id]
    if stage:
        conds.append(S.stage == stage)
    if region:
        conds.append(S.region == region)
    if search:
        like = f"%{search.lower()}%"
        conds.append(func.lower(func.coalesce(S.full_address, "") + " " + func.coalesce(S.city, "")
                                 + " " + func.coalesce(S.owner, "") + " " + func.coalesce(S.install_place, "")).like(like))
    total = int((await db.execute(select(func.count()).select_from(S).where(*conds))).scalar_one() or 0)
    rows = (await db.execute(
        select(S).where(*conds).order_by(S.region.nulls_last(), S.city.nulls_last(), S.id)
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "page": page, "pageSize": page_size, "items": [_site_out(s) for s in rows]}


def _site_out(s: EzsSite) -> dict[str, Any]:
    return {
        "id": str(s.id), "stage": s.stage, "stageLabel": STAGE_LABELS.get(s.stage, s.stage),
        "statusRaw": s.status_raw, "receivedDate": s.received_date,
        "region": s.region, "city": s.city, "address": s.address, "fullAddress": s.full_address,
        "placeKind": s.place_kind, "installPlace": s.install_place, "route": s.route,
        "lat": s.lat, "lon": s.lon, "mapUrl": s.map_url,
        "owner": s.owner, "brand": s.brand, "areaM2": s.area_m2, "ownership": s.ownership,
        "freePowerKwt": s.free_power_kwt,
        "connectionCost": float(s.connection_cost) if s.connection_cost is not None else None,
        "rentCostMonth": float(s.rent_cost_month) if s.rent_cost_month is not None else None,
        "plannedPowerKwt": s.planned_power_kwt, "plannedEzsCount": s.planned_ezs_count,
        "portsGbt": s.ports_gbt, "portsCcs": s.ports_ccs, "portsChademo": s.ports_chademo, "portsType": s.ports_type,
        "supplier": s.supplier, "contractor": s.contractor, "tuStatus": s.tu_status,
        "techConnType": s.tech_conn_type, "dopService": s.dop_service, "comment": s.comment,
    }


async def site_detail(db: AsyncSession, company_id, site_id) -> dict[str, Any] | None:
    s = (await db.execute(
        select(EzsSite).where(EzsSite.company_id == company_id, EzsSite.id == site_id)
    )).scalar_one_or_none()
    if s is None:
        return None
    out = _site_out(s)
    out["raw"] = s.raw or {}       # все 55 исходных колонок для карточки
    out["sourceSheet"] = s.source_sheet
    return out


async def sites_overview(db: AsyncSession, company_id) -> dict[str, Any]:
    S = EzsSite
    base = S.company_id == company_id
    total = int((await db.execute(select(func.count()).select_from(S).where(base))).scalar_one() or 0)
    by_stage = {r.stage: int(r.n) for r in (await db.execute(
        select(S.stage, func.count().label("n")).where(base).group_by(S.stage))).all()}
    reg_expr = func.coalesce(S.region, "— не указан")
    regions = (await db.execute(
        select(reg_expr.label("region"), func.count().label("n"))
        .where(base).group_by(reg_expr).order_by(func.count().desc()).limit(15))).all()
    agg = (await db.execute(select(
        func.count().filter(S.lat.is_not(None)).label("with_coords"),
        func.coalesce(func.sum(S.planned_ezs_count), 0).label("ezs"),
        func.coalesce(func.sum(S.planned_power_kwt), 0).label("power"),
        func.count().filter(S.connection_cost.is_not(None)).label("with_cost"),
        func.coalesce(func.sum(S.connection_cost), 0).label("cost_sum"),
    ).where(base))).one()
    return {
        "total": total,
        "byStage": [{"stage": st, "label": STAGE_LABELS[st], "count": by_stage.get(st, 0)} for st in STAGE_ORDER],
        "byRegion": [{"region": r[0], "count": int(r[1])} for r in regions],
        "withCoords": int(agg.with_coords or 0),
        "plannedEzs": int(agg.ezs or 0),
        "plannedPowerKwt": round(float(agg.power or 0), 1),
        "withKnownCost": int(agg.with_cost or 0),
        "connectionCostSum": round(float(agg.cost_sum or 0), 2),
    }
