"""Модель данных станций ЭЗС для раздела «Нормализация» (energy).

Тот же контракт, что AnalyticsService.charge_model (слои L1→L4, звёздная схема
факт+измерения, качество нормализации) — но по объектам (ServiceLocation,
type='ev_charging'), а не по сессиям. Позволяет переиспользовать фронт-витрину.
По всему датасету компании (без периода).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Channel, ChargeSession, Region, ServiceLocation, StationContractSettlement,
)


async def stations_linkage(db: AsyncSession, company_id) -> dict[str, Any]:
    """Связь каналов по станции (конформная размерность) для «Нормализации».

    Станция-объект (service_locations, ev_charging) — общий хаб; каждый канал-факт
    ссылается на него своим ключом. Показываем покрытие и разрывы:
      • сессии    → по № (station_code ↔ объект.№);
      • оплаты    → по FK (location_id);
      • справочник→ обогащение паспортом (типизированные колонки).
    Ключ конформной размерности — станция № (number).
    """
    L = ServiceLocation
    objs = (await db.execute(select(L).where(
        L.company_id == company_id, L.type == "ev_charging"))).scalars().all()
    obj_ids = {o.id for o in objs}
    # «В сети» = боевые станции: без тестовых (is_test) и без выведенных из эксплуатации
    # (operational_status='decommissioned'). Объекты остаются в каталоге, но не в KPI сети.
    n_test = sum(1 for o in objs if o.is_test)
    n_decomm = sum(1 for o in objs if (o.operational_status or "") == "decommissioned")
    n_network = sum(1 for o in objs
                    if not o.is_test and (o.operational_status or "") != "decommissioned")
    obj_numbers: set[str] = set()
    for o in objs:
        n = o.station_number or (o.extra_metadata or {}).get("number")
        if n is not None and str(n).strip():
            obj_numbers.add(str(n).strip())
    enriched = sum(1 for o in objs if o.serial_number is not None)

    # Сессии → материализованная связь по location_id (FK на объект); резолв по №.
    sess_codes = {str(x).strip() for x in (await db.execute(
        select(distinct(ChargeSession.station_code)).where(
            ChargeSession.company_id == company_id))).scalars() if x}
    sess_linked = {str(x).strip() for x in (await db.execute(
        select(distinct(ChargeSession.station_code)).where(
            ChargeSession.company_id == company_id, ChargeSession.location_id.is_not(None)))).scalars() if x}
    sess_orphans = sess_codes - sess_linked
    sess_total = int((await db.execute(select(func.count()).select_from(ChargeSession).where(
        ChargeSession.company_id == company_id))).scalar() or 0)
    sess_rec_linked = int((await db.execute(select(func.count()).select_from(ChargeSession).where(
        ChargeSession.company_id == company_id, ChargeSession.location_id.is_not(None)))).scalar() or 0)

    # Оплаты → по FK location_id
    set_locs = {str(x) for x in (await db.execute(
        select(distinct(StationContractSettlement.location_id)).where(
            StationContractSettlement.company_id == company_id))).scalars() if x}
    set_total = int((await db.execute(select(func.count()).select_from(StationContractSettlement).where(
        StationContractSettlement.company_id == company_id))).scalar() or 0)
    set_linked = set_locs & obj_ids

    def pct(a: int, b: int) -> float:
        return round(a / b * 100, 1) if b else 0.0

    def orphan_examples(codes: set[str], limit: int = 8) -> list[str]:
        return sorted(codes)[:limit]

    channels = [
        {"name": "Зарядные сессии ЭЗС", "template": "charge_sessions",
         "key": "location_id (FK) · резолв по №", "materialized": sess_rec_linked > 0,
         "stations": len(sess_codes), "linked": len(sess_linked), "linked_pct": pct(len(sess_linked), len(sess_codes)),
         "records": sess_total, "records_linked": sess_rec_linked, "records_pct": pct(sess_rec_linked, sess_total),
         "orphans": len(sess_orphans), "orphan_examples": orphan_examples(sess_orphans)},
        {"name": "Договоры и оплаты ЭЗС", "template": "reestr_contracts_payments",
         "key": "location_id (FK)", "materialized": True,
         "stations": len(set_locs), "linked": len(set_linked), "linked_pct": pct(len(set_linked), len(set_locs)),
         "records": set_total, "records_linked": set_total, "records_pct": 100.0 if set_total else 0.0,
         "orphans": len(set_locs - obj_ids), "orphan_examples": []},
        {"name": "Справочник станций ЭЗС", "template": "stations",
         "key": "ext_id/serial → объект", "materialized": True,
         "stations": len(objs), "linked": enriched, "linked_pct": pct(enriched, len(objs)),
         "records": enriched, "records_linked": enriched, "records_pct": 100.0,
         "orphans": len(objs) - enriched, "orphan_examples": []},
    ]

    return {
        "key_label": "станция № (number)",
        "objects": n_network,           # ЭЗС в сети (боевые: без тест/выведенных) — для KPI
        "objects_total": len(objs),     # всего объектов в каталоге
        "objects_test": n_test,
        "objects_decommissioned": n_decomm,
        "objects_enriched": enriched,
        "objects_without_sessions": len(obj_numbers - sess_codes),
        "channels": channels,
    }


async def stations_model(db: AsyncSession, company_id) -> dict[str, Any]:
    L = ServiceLocation
    where = (L.company_id == company_id, L.type == "ev_charging")

    agg = (await db.execute(select(
        func.count().label("rows"),
        func.coalesce(func.sum(L.power_kwt), 0).label("power"),
        func.coalesce(func.sum(L.connectors_count), 0).label("connectors"),
        func.coalesce(func.avg(L.rating), 0).label("rating"),
        func.coalesce(func.avg(L.success_pct), 0).label("success"),
        func.coalesce(func.sum(case((L.is_test.is_(True), 1), else_=0)), 0).label("tests"),
        # заполнение полей паспорта (COUNT игнорирует NULL → доля непустых)
        func.count(L.code).label("f_code"),
        func.count(L.name).label("f_name"),
        func.count(L.serial_number).label("f_serial"),
        func.count(L.station_number).label("f_number"),
        func.count(L.region_id).label("f_region"),
        func.count(L.city).label("f_city"),
        func.count(L.address).label("f_address"),
        func.count(L.latitude).label("f_lat"),
        func.count(L.longitude).label("f_lng"),
        func.count(L.power_kwt).label("f_power"),
        func.count(L.connectors_count).label("f_conn"),
        func.count(L.connector_types).label("f_conn_types"),
        func.count(L.owner).label("f_owner"),
        func.count(L.brand).label("f_brand"),
        func.count(L.model).label("f_model"),
        func.count(L.ocpp_protocol).label("f_ocpp"),
        func.count(L.firmware).label("f_firmware"),
        func.count(L.stage).label("f_stage"),
        func.count(L.hubex_asset_id).label("f_hubex"),
        func.count(L.rating).label("f_rating"),
        func.count(L.success_pct).label("f_success"),
        # кардинальность измерений
        func.count(distinct(L.region_id)).label("d_region"),
        func.count(distinct(L.owner)).label("d_owner"),
        func.count(distinct(L.brand)).label("d_brand"),
        func.count(distinct(L.model)).label("d_model"),
        func.count(distinct(L.connector_types)).label("d_conn_types"),
        func.count(distinct(L.stage)).label("d_stage"),
        func.count(distinct(L.operational_status)).label("d_oper"),
        func.count(distinct(L.ocpp_protocol)).label("d_ocpp"),
        func.count(distinct(L.city)).label("d_city"),
    ).where(*where))).one()

    rows = int(agg.rows or 0)

    # L1 RAW: загруженные справочники (xlsx) — по каналам шаблона stations.
    ch_cfgs = (await db.execute(select(Channel.config).where(
        Channel.company_id == company_id, Channel.template_id == "stations"))).scalars().all()
    file_ids = {(c or {}).get("uploadFileId") or (c or {}).get("upload_file_id") for c in ch_cfgs}
    file_ids.discard(None)
    l1_files = len(file_ids)

    if rows == 0:
        return {"rows": 0, "l1_files": l1_files, "layers": [], "fact": None,
                "dimensions": [], "quality": None}

    def pct(n) -> float:
        return round(int(n or 0) / rows * 100, 1) if rows else 0.0

    power = float(agg.power or 0); connectors = int(agg.connectors or 0)
    rating = float(agg.rating or 0); success = float(agg.success or 0)
    tests = int(agg.tests or 0)

    async def members(col, limit: int) -> list[dict[str, Any]]:
        r = (await db.execute(
            select(col.label("m"), func.count().label("cnt"))
            .where(*where, col.is_not(None)).group_by(col).order_by(func.count().desc()).limit(limit)
        )).all()
        return [{"label": str(x.m), "count": int(x.cnt)} for x in r]

    # регион — топ по имени (join на regions)
    reg = (await db.execute(
        select(Region.name.label("m"), func.count().label("cnt"))
        .select_from(L).join(Region, L.region_id == Region.id)
        .where(*where).group_by(Region.name).order_by(func.count().desc()).limit(8)
    )).all()
    m_region = [{"label": str(x.m), "count": int(x.cnt)} for x in reg]
    m_owner = await members(L.owner, 8)
    m_brand = await members(L.brand, 12)
    m_model = await members(L.model, 8)
    m_conn_types = await members(L.connector_types, 12)
    m_stage = await members(L.stage, 8)
    m_oper = await members(L.operational_status, 8)
    m_ocpp = await members(L.ocpp_protocol, 8)

    # мощность — бэнды (вычисляемое измерение)
    band = case(
        (L.power_kwt >= 150, "≥150 кВт (DC-ультра)"),
        (L.power_kwt >= 50, "50–150 кВт (DC-быстрая)"),
        (L.power_kwt >= 22, "22–50 кВт"),
        (L.power_kwt > 0, "<22 кВт (AC)"),
        else_="— не указана",
    )
    br = (await db.execute(
        select(band.label("m"), func.count().label("cnt")).where(*where)
        .group_by(band).order_by(func.count().desc())
    )).all()
    m_band = [{"label": str(x.m), "count": int(x.cnt)} for x in br]

    layers = [
        {"key": "l1", "code": "L1 · RAW", "title": "Сырьё",
         "desc": "Справочник станций ЭЗС (xlsx, лист «Станции») «как есть» — до разбора паспорта.",
         "records": l1_files, "unit": "справочников", "tone": "raw",
         **({"status": "direct"} if l1_files == 0 else {})},
        {"key": "l2", "code": "L2 · CLEAN", "title": "Нормализованная база (объекты)",
         "desc": "Станции: паспорт в типизированные колонки (координаты/мощность/коннекторы/бренд/OCPP/HubEx), "
                 "регион канонизирован и связан с regions (region_id), статус/стадия разобраны; дедуп по «ID станции».",
         "records": rows, "unit": "станций", "tone": "clean"},
        {"key": "l3", "code": "L3 · EXPORT", "title": "Витрины / срезы (OLAP)",
         "desc": "Агрегаты: измерения (регион/владелец/бренд/мощность) × меры — под сводные, карту, дашборды.",
         "records": None, "unit": "куб", "tone": "export"},
        {"key": "l4", "code": "L4 · 1C_REF", "title": "Связь с 1С",
         "desc": "Сопоставление объектов с НСИ 1С (склады/подразделения). Пока не подключено.",
         "records": 0, "unit": "", "tone": "ref", "status": "planned"},
    ]

    fact = {
        "table": "service_locations",
        "name": "Станция ЭЗС",
        "grain": "1 строка = 1 станция (объект type=ev_charging)",
        "rows": rows,
        "period": {"from": None, "to": None},
        "measures": [
            {"key": "count", "label": "Станции", "value": rows, "unit": "шт", "agg": "COUNT"},
            {"key": "power_kwt", "label": "Суммарная мощность", "value": round(power, 1), "unit": "кВт", "agg": "SUM"},
            {"key": "connectors", "label": "Коннекторов", "value": connectors, "unit": "шт", "agg": "SUM"},
            {"key": "owners", "label": "Владельцев (ЮЛ)", "value": int(agg.d_owner or 0), "unit": "шт", "agg": "DISTINCT"},
            {"key": "regions", "label": "Регионов", "value": int(agg.d_region or 0), "unit": "шт", "agg": "DISTINCT"},
            {"key": "rating", "label": "Ср. оценка", "value": round(rating, 2), "unit": "балл", "agg": "AVG"},
            {"key": "test_pct", "label": "Тест-станции", "value": pct(tests), "unit": "%", "agg": "AVG"},
        ],
    }

    dimensions = [
        {"key": "region", "label": "Регион", "field": "region_id → regions",
         "cardinality": int(agg.d_region or 0), "fill_pct": pct(agg.f_region), "canonical": True, "members": m_region},
        {"key": "owner", "label": "Владелец (ЮЛ)", "field": "owner",
         "cardinality": int(agg.d_owner or 0), "fill_pct": pct(agg.f_owner), "canonical": False, "members": m_owner},
        {"key": "brand", "label": "Бренд / производитель", "field": "brand",
         "cardinality": int(agg.d_brand or 0), "fill_pct": pct(agg.f_brand), "canonical": False, "members": m_brand},
        {"key": "model", "label": "Модель", "field": "model",
         "cardinality": int(agg.d_model or 0), "fill_pct": pct(agg.f_model), "canonical": False, "members": m_model},
        {"key": "power", "label": "Мощность (бэнд)", "field": "power_kwt",
         "cardinality": len(m_band), "fill_pct": pct(agg.f_power), "canonical": True, "members": m_band},
        {"key": "connector_types", "label": "Типы коннекторов", "field": "connector_types",
         "cardinality": int(agg.d_conn_types or 0), "fill_pct": pct(agg.f_conn_types), "canonical": False, "members": m_conn_types},
        {"key": "stage", "label": "Стадия", "field": "stage",
         "cardinality": int(agg.d_stage or 0), "fill_pct": pct(agg.f_stage), "canonical": False, "members": m_stage},
        {"key": "operational_status", "label": "Операционный статус", "field": "operational_status",
         "cardinality": int(agg.d_oper or 0), "fill_pct": 100.0, "canonical": True, "members": m_oper},
        {"key": "ocpp", "label": "Протокол OCPP", "field": "ocpp_protocol",
         "cardinality": int(agg.d_ocpp or 0), "fill_pct": pct(agg.f_ocpp), "canonical": False, "members": m_ocpp},
        {"key": "geo", "label": "Гео (координаты)", "field": "latitude / longitude",
         "cardinality": int(agg.d_city or 0), "fill_pct": pct(agg.f_lat), "canonical": False,
         "grain": "регион → город → станция (точка на карте)", "members": []},
    ]

    quality_fields = [
        {"field": "code", "label": "ID / № станции", "role": "ключ (дедуп)", "fill_pct": pct(agg.f_code)},
        {"field": "name", "label": "Название", "role": "атрибут", "fill_pct": pct(agg.f_name)},
        {"field": "serial_number", "label": "Серийный № (HubEx)", "role": "атрибут", "fill_pct": pct(agg.f_serial)},
        {"field": "region_id", "label": "Регион", "role": "измерение (канон.)", "fill_pct": pct(agg.f_region)},
        {"field": "city", "label": "Город", "role": "атрибут", "fill_pct": pct(agg.f_city)},
        {"field": "address", "label": "Адрес", "role": "атрибут", "fill_pct": pct(agg.f_address)},
        {"field": "latitude", "label": "Широта", "role": "гео", "fill_pct": pct(agg.f_lat)},
        {"field": "longitude", "label": "Долгота", "role": "гео", "fill_pct": pct(agg.f_lng)},
        {"field": "power_kwt", "label": "Мощность, кВт", "role": "мера · измерение", "fill_pct": pct(agg.f_power)},
        {"field": "connectors_count", "label": "Кол-во коннекторов", "role": "мера", "fill_pct": pct(agg.f_conn)},
        {"field": "connector_types", "label": "Типы коннекторов", "role": "измерение", "fill_pct": pct(agg.f_conn_types)},
        {"field": "owner", "label": "Владелец (ЮЛ)", "role": "измерение", "fill_pct": pct(agg.f_owner)},
        {"field": "brand", "label": "Бренд", "role": "измерение", "fill_pct": pct(agg.f_brand)},
        {"field": "model", "label": "Модель", "role": "измерение", "fill_pct": pct(agg.f_model)},
        {"field": "ocpp_protocol", "label": "Протокол OCPP", "role": "атрибут", "fill_pct": pct(agg.f_ocpp)},
        {"field": "hubex_asset_id", "label": "HubEx asset_id", "role": "связка HubEx", "fill_pct": pct(agg.f_hubex)},
        {"field": "success_pct", "label": "Успешность, %", "role": "мера (наблюдаемая)", "fill_pct": pct(agg.f_success)},
    ]

    canonicalization = [
        {"name": "Регион", "from": "наименование региона из справочника", "to": "канонический регион + region_id (regions)",
         "members": int(agg.d_region or 0), "coverage_pct": pct(agg.f_region)},
        {"name": "Операционный статус", "from": "«Статус (dev)» из справочника", "to": "working / not_working / on_repair / maintenance",
         "members": int(agg.d_oper or 0), "coverage_pct": 100.0},
        {"name": "Стадия", "from": "«Стадия» из справочника", "to": "статус точки (active / planned / closed)",
         "members": int(agg.d_stage or 0), "coverage_pct": pct(agg.f_stage)},
        {"name": "Мощность → бэнд", "from": "мощность, кВт", "to": "бэнд (AC / DC-быстрая / DC-ультра)",
         "members": len(m_band), "coverage_pct": pct(agg.f_power)},
        {"name": "Координаты", "from": "широта / долгота", "to": "точка на карте (гео-измерение)",
         "members": None, "coverage_pct": pct(agg.f_lat)},
        {"name": "Тест-флаг", "from": "«⚠ Тест?» из справочника", "to": "is_test (исключение из витрин)",
         "members": 2, "coverage_pct": 100.0},
        {"name": "Дедупликация", "from": "ID станции", "to": "стабильный ServiceLocation.id (ezs-<hash>)",
         "members": rows, "coverage_pct": 100.0},
    ]

    return {
        "rows": rows, "l1_files": l1_files,
        "layers": layers, "fact": fact, "dimensions": dimensions,
        "quality": {"fields": quality_fields, "canonicalization": canonicalization},
    }
