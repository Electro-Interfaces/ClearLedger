"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
import uuid
from datetime import date

import os

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_module_access, get_current_user
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import User
from app.services.goods_dashboard import GoodsDashboardService

# Каталог выгрузки пакетов БП — ТОЛЬКО из окружения сервера (не из клиентского
# Query — закрыта directory-injection: раньше любой аутентиф. пользователь мог
# писать в произвольный путь ФС сервера).
BP_EXPORT_DIR = os.environ.get("TL_BP_EXPORT_DIR", r"C:\TL_BP_Export")


async def _require_store_module(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """GAP-1: RBAC-гейт всего раздела «Магазин». Без него любой член компании с
    урезанной ролью читал данные магазина и (что критично) мог эмитить пакет в
    каталог обмена с живой бухгалтерией. Проверяем модуль 'store' для компании,
    выбранной в UI (X-Company-Id), — как analytics-режимы через assert_company_module."""
    cid = await scope_company_id(user, db)   # membership + резолв X-Company-Id
    await check_module_access(user, cid, db, "store")


# capture_company_header кладёт X-Company-Id (выбранная компания) в contextvar;
# scope_company_id ниже резолвит её вместо жёсткой user.company_id (переключение
# компании в UI теперь влияет и на «Магазин»). _require_store_module — RBAC-гейт.
router = APIRouter(prefix="/store", tags=["Магазин"],
                   dependencies=[Depends(capture_company_header),
                                 Depends(_require_store_module)])


@router.get("/overview")
async def store_overview(
    date_from: str = Query(..., description="ISO дата начала периода"),
    date_to: str = Query(..., description="ISO дата конца периода"),
    stations: str | None = Query(None, description="коды АЗС через запятую (опц.)"),
    compare: bool = Query(False, description="сравнить с предыдущим периодом (Δ%)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """KPI обзора магазина за период (продажи сопутки/общепита)."""
    cid: uuid.UUID = await scope_company_id(user, db)
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).compute(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st, compare,
    )


@router.get("/skus")
async def store_skus(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр SKU с маржой и ABC (питает Ассортимент / Цены-маржа / Номенклатуру)."""
    cid: uuid.UUID = await scope_company_id(user, db)
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).sku_analytics(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/sales")
async def store_sales(
    date_from: str = Query(...),
    date_to: str = Query(...),
    group_by: str = Query("sku", description="sku|category|kind|marking|vat|day|payment"),
    category: str = Query("all", description="all|soputka|obshepit"),
    marked: str = Query("all", description="all|marked|plain"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Анализ продаж с гибкой группировкой и фильтрами (инструмент менеджера)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sales_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        group_by=group_by, category=category, marked=marked, q=q, stations=st,
    )


@router.get("/nomenclature")
async def store_nomenclature(
    date_from: str = Query(...),
    date_to: str = Query(...),
    kind: str = Query("all"),
    marked: str = Query("all"),
    weighed: str = Query("all"),
    has_sales: str = Query("all"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полный справочник номенклатуры + обогащение продажами/ШК + фильтры (мастер-НСИ)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).nomenclature_catalog(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        kind=kind, marked=marked, weighed=weighed, has_sales=has_sales, q=q, stations=st,
    )


@router.get("/stock")
async def store_stock(
    warehouse: str | None = Query(None, description="код склада (по умолч. — с макс. SKU, обычно 208)"),
    q: str = Query(""),
    marked: str = Query("all", description="all|marked|plain"),
    only_negative: bool = Query(False, description="только отрицательные остатки"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Достоверный остаток товара (снимок регистров ЦБ ТоварыНаАЗК+Партии), не оценка."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).stock_onhand(
        warehouse=warehouse, q=q, marked=marked, only_negative=only_negative,
    )


def _od(s: str | None):
    return date.fromisoformat(s) if s else None


@router.get("/inventory")
async def store_inventory(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    only_dev: bool = Query(False, description="только документы с отклонениями"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр инвентаризаций ЦБ + недостачи/излишки (shrinkage) с drill-down по строкам."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).inventory(
        warehouse=warehouse, only_dev=only_dev, date_from=_od(date_from), date_to=_od(date_to),
    )


@router.get("/writeoffs")
async def store_writeoffs(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    reason: str | None = Query(None, description="фильтр по причине"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр списаний ЦБ (СписаниеТоваров) + причины + топ списанных SKU."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).writeoffs(
        warehouse=warehouse, reason=reason, date_from=_od(date_from), date_to=_od(date_to),
    )


@router.get("/transfers")
async def store_transfers(
    direction: str | None = Query(None, description="фильтр по направлению"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр перемещений ЦБ (ПеремещениеТоваров) откуда→куда + направления."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).transfers(
        direction=direction, date_from=_od(date_from), date_to=_od(date_to))


@router.get("/revaluation")
async def store_revaluation(
    reason: str | None = Query(None, description="фильтр направления (Подорожание/Удешевление/Смешанная)"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая цена, Δ%, влияние."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).revaluation(
        reason=reason, date_from=_od(date_from), date_to=_od(date_to))


@router.get("/catering")
async def store_catering(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Инжиниринг меню общепита: блюда + фудкост/маржа + класс меню + состав ТТК + динамика."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).catering_menu(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/pricing")
async def store_pricing(
    date_from: str = Query(...),
    date_to: str = Query(...),
    category: str = Query("all", description="all|soputka|obshepit"),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Цены и маржа: сегмент (сопутка/общепит/всё) + группы + реестр SKU."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).pricing_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to), category=category, stations=st,
    )


@router.get("/assortment")
async def store_assortment(
    date_from: str = Query(...),
    date_to: str = Query(...),
    category: str = Query("all", description="all|soputka|obshepit"),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ассортимент: ABC×XYZ + оборачиваемость/запасы + GMROI + дефицит/неликвиды + action-list."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).assortment_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to), category=category, stations=st,
    )


@router.get("/sku/{guid}")
async def store_sku_detail(
    guid: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Детализация товара (модалка): метрики + история цен + продажи + закупки + остаток."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sku_detail(
        guid, date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/sku-card/{guid}")
async def store_sku_card(
    guid: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полная карточка номенклатуры (товаровед): паспорт + ШК + цена/остаток +
    продажи + поставщики + движение + рецептура ТТК + МРЦ."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sku_card(
        guid, date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


def _stations(stations: str | None) -> list[str] | None:
    return [s.strip() for s in stations.split(",") if s.strip()] if stations else None


# ── Слой политик: план продаж + план-факт-светофор (О-1) ──
# Регистрируются ДО catch-all /{report}, иначе /plan перехватится как отчёт.

class _PlanItem(BaseModel):
    scope_kind: str = "total"       # total | category | station
    scope_key: str = "*"            # имя категории / код АЗС / '*'
    metric: str = "revenue"         # revenue | qty
    plan_value: float = 0


class _PlanSave(BaseModel):
    period: str                     # 'YYYY-MM'
    items: list[_PlanItem] = []


@router.get("/plan")
async def store_get_plan(
    period: str = Query(..., description="Месяц плана 'YYYY-MM'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """План продаж магазина на месяц (сырьё для формы редактирования)."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).get_plans(period)


@router.put("/plan")
async def store_save_plan(
    body: _PlanSave,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить план (ручной ввод руководителя). Значение ≤0 удаляет строку."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).save_plans(
        body.period, [i.model_dump() for i in body.items],
    )


@router.get("/plan-facts")
async def store_plan_facts(
    period: str = Query(..., description="Месяц 'YYYY-MM'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """План-факт-светофор за месяц: карты факт/план/%/🟢🟡🔴 + спарклайн."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).plan_facts(period)


# ── МРЦ табака: регуляторный контроль «продажа выше МРЦ» (О-3) ──

class _MrcRow(BaseModel):
    barcode: str | None = None
    article: str | None = None
    name: str | None = None
    mrc: float | str | None = None


class _MrcImport(BaseModel):
    rows: list[_MrcRow] = []


@router.get("/mrc")
async def store_mrc(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Контроль МРЦ табака: розница vs МРЦ (нарушения) + табак без МРЦ."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).mrc_control()


@router.post("/mrc/import")
async def store_mrc_import(
    body: _MrcImport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Импорт справочника МРЦ (CSV → строки). Матч по штрихкоду/артикулу."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).import_mrc(
        [r.model_dump() for r in body.rows],
    )


@router.get("/shifts")
async def store_shifts(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смены как составной документ: продажи + приходы/инвентаризации/списания/возвраты за смену."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).shifts_composite(
        date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations),
    )


@router.get("/shift")
async def store_shift_detail(
    key: str = Query(..., description="shift_key (GUID смены или 'дата|станция')"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена-детализация (модалка): строки продаж + касса + приходы/инвентаризации/списания дня."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).shift_detail(key)


@router.get("/bp-package")
async def store_bp_package(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview пакета «смена→БП» (эмиттер Ledger): все типы документов + НСИ + хеш."""
    from app.services.bp_export import BpPackageEmitter
    try:
        return await BpPackageEmitter(db, await scope_company_id(user, db)).build_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сборка пакета: {e}")


@router.post("/bp-package/emit")
async def store_bp_package_emit(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить пакет в серверный каталог BP_EXPORT_DIR (клиент путь НЕ задаёт).
    Файл АЗС{код}_{дата}_смена-{номер}_{uuid}.json."""
    from app.services.bp_export import BpPackageEmitter
    try:
        return await BpPackageEmitter(db, await scope_company_id(user, db)).emit_to_dir(shift_key, BP_EXPORT_DIR)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Выгрузка в каталог: {e}")


@router.get("/bp-package/verify")
async def store_bp_package_verify(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сверка сопутки: самосогласованность пакета + готовность к загрузке (балансы,
    полнота НСИ, fail-fast НДС, хеш). Список проверок ok/детали."""
    from app.services.bp_export import BpPackageEmitter
    try:
        return await BpPackageEmitter(db, await scope_company_id(user, db)).verify_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сверка: {e}")


@router.get("/barcodes")
async def store_barcodes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Справочник штрихкодов — снимок НСИ. Периода/станций у сущности нет, поэтому
    и параметров нет (раньше требовались роутером и молча игнорировались)."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).barcodes()


@router.get("/{report}")
async def store_report(
    report: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёты раздела по периоду: receipts · suppliers · catering · categories · recipes.
    barcodes — отдельный маршрут выше (справочник вне периода)."""
    svc = GoodsDashboardService(db, await scope_company_id(user, db))
    method = {"receipts": svc.receipts, "suppliers": svc.suppliers,
              "catering": svc.catering, "categories": svc.categories,
              "recipes": svc.recipes}.get(report)
    if method is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Неизвестный отчёт: {report}")
    return await method(date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations))


# ─────────────────────────── Контроль дублей ────────────────────────────────
# Анализ дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ.
from app.services import dedup_service


@router.get("/dedup/summary")
async def dedup_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.summary(db, await scope_company_id(user, db))


@router.get("/dedup/groups")
async def dedup_groups(
    q: str | None = Query(None),
    include_assortment: bool = Query(False),
    only_live: bool = Query(False),
    price_desync: bool = Query(False),
    only_scope_208: bool = Query(True),
    status: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    return await dedup_service.groups(db, cid, q=q, include_assortment=include_assortment,
                                      only_live=only_live, status=status, price_desync=price_desync,
                                      only_scope_208=only_scope_208)


@router.post("/dedup/reload")
async def dedup_reload(
    file: UploadFile,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Обновить срез: загрузить свежий дамп 208 (probe-раннер) + склейка ЦБ."""
    cid = await scope_company_id(user, db)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Дамп слишком большой")
    text = raw.decode("utf-8", "replace")
    if "#CARDS" not in text:
        raise HTTPException(400, "Не похоже на дамп 208 (нет секции #CARDS)")
    return await dedup_service.load_dump(db, cid, text)


@router.get("/dedup/bridge")
async def dedup_bridge(
    kind: str = Query("on_marked", pattern="^(on_marked|multi|price_split)$"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await dedup_service.bridge(db, await scope_company_id(user, db), kind=kind)


class DedupStatusBody(BaseModel):
    entityType: str            # group | card
    entityKey: str
    status: str | None = None
    canonGuid: str | None = None
    note: str | None = None


@router.post("/dedup/status")
async def dedup_set_status(
    body: DedupStatusBody,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if body.entityType not in ("group", "card"):
        raise HTTPException(400, "entityType: group|card")
    cid = await scope_company_id(user, db)
    row = await dedup_service.set_status(
        db, cid, entity_type=body.entityType, entity_key=body.entityKey,
        status=body.status, canon_guid=body.canonGuid, note=body.note, user=user.name or user.email)
    return {"status": row.status, "canonGuid": row.canon_guid, "note": row.note,
            "history": row.history}


@router.get("/dedup/export")
async def dedup_export(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.export_plan(db, await scope_company_id(user, db))


# ── корректировки по команде менеджера ───────────────────────────────────────
class CorrectBody(BaseModel):
    groupKeys: list[str]
    dryRun: bool = False


@router.post("/dedup/correct")
async def dedup_correct(
    body: CorrectBody,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Команда менеджера: создать задание перецепа кодов НС на канон по выбранным
    группам (нода 208 выполнит). dryRun=true — пробный прогон (план без записи)."""
    if not body.groupKeys:
        raise HTTPException(400, "Не выбраны группы")
    cid = await scope_company_id(user, db)
    return await dedup_service.create_repoint_job(
        db, cid, group_keys=body.groupKeys, dry_run=body.dryRun, user=user.name or user.email)


@router.post("/dedup/refresh")
async def dedup_refresh(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Команда менеджера: станция снимет свежий срез с локальной 1С и зальёт сюда
    (бэкенд в сеть станции не ходит — идём через очередь заданий)."""
    cid = await scope_company_id(user, db)
    return await dedup_service.create_refresh_job(db, cid, user=user.name or user.email)


@router.get("/dedup/jobs")
async def dedup_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.list_jobs(db, await scope_company_id(user, db))


@router.post("/dedup/jobs/{job_id}/cancel")
async def dedup_job_cancel(
    job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        jid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Невалидный ID")
    ok = await dedup_service.cancel_job(db, await scope_company_id(user, db), jid)
    if not ok:
        raise HTTPException(404, "Задание не найдено или уже выполнено")
    return {"ok": True}


@router.get("/dedup/merge-map")
async def dedup_merge_map(
    group_keys: str | None = Query(None, description="ключи групп через | (опц.)"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Карта слияния дубль→канон для .epf (ЗаменитьСсылки — запуск руками в тихое окно)."""
    keys = [k for k in group_keys.split("|") if k] if group_keys else None
    return await dedup_service.merge_map(db, await scope_company_id(user, db), group_keys=keys)
