"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services.goods_dashboard import GoodsDashboardService

router = APIRouter(prefix="/store", tags=["Магазин"])


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
    cid: uuid.UUID = user.company_id
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
    cid: uuid.UUID = user.company_id
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
    return await GoodsDashboardService(db, user.company_id).sales_analysis(
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
    return await GoodsDashboardService(db, user.company_id).nomenclature_catalog(
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
    return await GoodsDashboardService(db, user.company_id).stock_onhand(
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
    return await GoodsDashboardService(db, user.company_id).inventory(
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
    return await GoodsDashboardService(db, user.company_id).writeoffs(
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
    return await GoodsDashboardService(db, user.company_id).transfers(
        direction=direction, date_from=_od(date_from), date_to=_od(date_to))


@router.get("/revaluation")
async def store_revaluation(
    reason: str | None = Query(None, description="фильтр направления (Подорожание/Удешевление/Смешанная)"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая цена, Δ%, влияние."""
    return await GoodsDashboardService(db, user.company_id).revaluation(
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
    return await GoodsDashboardService(db, user.company_id).catering_menu(
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
    return await GoodsDashboardService(db, user.company_id).pricing_analysis(
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
    return await GoodsDashboardService(db, user.company_id).assortment_analysis(
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
    return await GoodsDashboardService(db, user.company_id).sku_detail(
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
    return await GoodsDashboardService(db, user.company_id).sku_card(
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
    return await GoodsDashboardService(db, user.company_id).get_plans(period)


@router.put("/plan")
async def store_save_plan(
    body: _PlanSave,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить план (ручной ввод руководителя). Значение ≤0 удаляет строку."""
    return await GoodsDashboardService(db, user.company_id).save_plans(
        body.period, [i.model_dump() for i in body.items],
    )


@router.get("/plan-facts")
async def store_plan_facts(
    period: str = Query(..., description="Месяц 'YYYY-MM'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """План-факт-светофор за месяц: карты факт/план/%/🟢🟡🔴 + спарклайн."""
    return await GoodsDashboardService(db, user.company_id).plan_facts(period)


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
    return await GoodsDashboardService(db, user.company_id).mrc_control()


@router.post("/mrc/import")
async def store_mrc_import(
    body: _MrcImport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Импорт справочника МРЦ (CSV → строки). Матч по штрихкоду/артикулу."""
    return await GoodsDashboardService(db, user.company_id).import_mrc(
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
    return await GoodsDashboardService(db, user.company_id).shifts_composite(
        date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations),
    )


@router.get("/shift")
async def store_shift_detail(
    key: str = Query(..., description="shift_key (GUID смены или 'дата|станция')"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена-детализация (модалка): строки продаж + касса + приходы/инвентаризации/списания дня."""
    return await GoodsDashboardService(db, user.company_id).shift_detail(key)


@router.get("/bp-package")
async def store_bp_package(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview пакета «смена→БП» (эмиттер Ledger): все типы документов + НСИ + хеш."""
    from app.services.bp_export import BpPackageEmitter
    return await BpPackageEmitter(db, user.company_id).build_shift_package(shift_key)


@router.post("/bp-package/emit")
async def store_bp_package_emit(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    directory: str = Query(r"C:\TL_BP_Export", description="каталог выгрузки"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить пакет в каталог (Ф3) — файл АЗС{код}_{дата}_смена-{номер}_{uuid}.json."""
    from app.services.bp_export import BpPackageEmitter
    return await BpPackageEmitter(db, user.company_id).emit_to_dir(shift_key, directory)


@router.get("/{report}")
async def store_report(
    report: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёты раздела: receipts · suppliers · catering · categories · barcodes · recipes."""
    svc = GoodsDashboardService(db, user.company_id)
    method = {"receipts": svc.receipts, "suppliers": svc.suppliers,
              "catering": svc.catering, "categories": svc.categories,
              "barcodes": svc.barcodes, "recipes": svc.recipes}.get(report)
    if method is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Неизвестный отчёт: {report}")
    return await method(date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations))
