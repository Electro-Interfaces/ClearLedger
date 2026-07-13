/**
 * Раздел «Магазин» — товароучёт сопутки/общепита (профиль fuel, компания ГИГ).
 *
 * Полная целевая карта раздела задаётся data-driven в `@/config/storeCatalog`
 * (STORE_VIEWS): 22 под-экрана в 5 группах — Аналитика, Данные, Товары, Движение,
 * Честный Знак. Часть — заглушки (status='planned'), наполняются по мере данных.
 *
 * Под-навигация (меню с под-разделами) рисуется гармошкой WorkspaceModeSidebar
 * из STORE_MENU — здесь только КОНТЕНТ активного под-раздела (без своего меню-столбца,
 * иначе меню задвоится).
 */

import { useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { StoreOverviewPanel } from './StoreOverviewPanel'
import { StoreSalesPanel } from './StoreSalesPanel'
import { StoreNomenclaturePanel } from './StoreNomenclaturePanel'
import { StoreSkuPanel, type SkuMode } from './StoreSkuPanel'
import { StoreStockPanel } from './StoreStockPanel'
import { StoreInventoryPanel } from './StoreInventoryPanel'
import { StoreWriteoffPanel } from './StoreWriteoffPanel'
import { StoreTransferPanel } from './StoreTransferPanel'
import { StoreRevaluationPanel } from './StoreRevaluationPanel'
import { StoreReceiptsPanel, StoreSuppliersPanel, StoreCategoriesPanel, StoreBarcodesPanel, StoreRecipesPanel } from './StoreReportPanels'
import { StoreCateringPanel } from './StoreCateringPanel'
import { StorePricingPanel } from './StorePricingPanel'
import { StoreAssortmentPanel } from './StoreAssortmentPanel'
import { StoreMrcPanel } from './StoreMrcPanel'
import { StoreShiftsPanel } from './StoreShiftsPanel'
import { BpExportPanel } from './BpExportPanel'
import { STORE_KEYS, STORE_DEFAULT_KEY, getStoreView, type StoreStatus, type StoreView } from '@/config/storeCatalog'

// Под-экраны, работающие на реестре SKU (/api/store/skus).
const SKU_MODES: Record<string, SkuMode> = {
  gtin: 'marked',
}

// Под-экраны на отчётных эндпоинтах (/api/store/{report}).
const REPORT_PANELS: Record<string, typeof StoreReceiptsPanel> = {
  receipts: StoreReceiptsPanel, suppliers: StoreSuppliersPanel,
  categories: StoreCategoriesPanel,
  barcodes: StoreBarcodesPanel, recipes: StoreRecipesPanel,
}

const STATUS_STYLE: Record<StoreStatus, { label: string; cls: string }> = {
  ready:   { label: 'основа готова', cls: 'border-emerald-400/40 text-emerald-300/80' },
  wip:     { label: 'в работе',      cls: 'border-amber-400/40 text-amber-300/80' },
  planned: { label: 'заложено',      cls: 'border-zinc-600 text-zinc-400' },
}

function StatusBadge({ status }: { status: StoreStatus }) {
  const s = STATUS_STYLE[status]
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${s.cls}`}>
      {s.label}
    </span>
  )
}

function ViewScaffold({ view }: { view: StoreView }) {
  const Icon = view.icon
  return (
    <div className="max-w-4xl">
      <div className="flex items-start gap-3 mb-1.5">
        <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary shrink-0">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold">{view.title}</h3>
            <StatusBadge status={view.status} />
          </div>
          <p className="text-sm text-muted-foreground mt-0.5 leading-relaxed">{view.subtitle}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
        {view.blocks.map((b) => (
          <div key={b.name} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-sm font-medium">{b.name}</div>
            <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{b.desc}</div>
            {b.source && (
              <div className="text-[10px] text-muted-foreground/60 mt-1.5 font-mono break-all">{b.source}</div>
            )}
          </div>
        ))}
      </div>

      {view.status === 'planned' && (
        <div className="mt-4 rounded-lg border border-dashed border-amber-400/30 bg-amber-400/5 p-3 text-xs text-amber-200/70 leading-relaxed">
          ⚠ Экран ещё не подключён к данным. Документы движения (перемещения, инвентаризации,
          списания, переоценка) в ЦБ ЭЛСИ.АЗК <b>есть</b> (probe подтвердил — тысячи записей по 208),
          коннектор их пока не читает: нужен выделённый fetch + нормализация. См.
          <code className="mx-1">STORE_MOVEMENT_BLUEPRINT.md</code>.
        </div>
      )}
    </div>
  )
}

export function StorePanel() {
  const [sub] = useWorkspaceSubView(STORE_DEFAULT_KEY, STORE_KEYS)
  const { period } = useFilters()
  const { companyId, company } = useCompany()

  // Магазин (сопутка/общепит) — витрина топливного профиля (ГИГ). У energy-компаний
  // (РусГидро) магазина нет — раздел появится после подключения интернет-магазина.
  if (company.profileId !== 'fuel') {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md text-center">
          <p className="text-sm font-medium text-foreground/80 mb-2">Раздел в разработке</p>
          <p className="text-sm text-muted-foreground">
            «Магазин» для {company.shortName || company.name} появится после подключения
            интернет-магазина.
          </p>
        </div>
      </div>
    )
  }

  // «Обзор» — executive-дашборд; SKU-экраны — реестр товаров; прочие — scaffold.
  if (sub === 'overview') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreOverviewPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'sales') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreSalesPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'nomenclature') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreNomenclaturePanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'stock') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreStockPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'inventory') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreInventoryPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'writeoffs') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreWriteoffPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'transfers') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreTransferPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'revaluation') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreRevaluationPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'menu') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreCateringPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'pricing') {
    return (
      <div className="h-full overflow-y-auto">
        <StorePricingPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'assortment') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreAssortmentPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'mrc') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreMrcPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'shifts') {
    return (
      <div className="h-full overflow-y-auto">
        <StoreShiftsPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (sub === 'export') {
    return (
      <div className="h-full overflow-y-auto">
        <BpExportPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  const skuMode = SKU_MODES[sub]
  if (skuMode) {
    return (
      <div className="h-full overflow-y-auto">
        <StoreSkuPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} mode={skuMode} />
      </div>
    )
  }
  const Report = REPORT_PANELS[sub]
  if (Report) {
    return (
      <div className="h-full overflow-y-auto">
        <Report companyId={companyId} dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }

  const view = getStoreView(sub) ?? getStoreView(STORE_DEFAULT_KEY)!
  return (
    <div className="h-full overflow-y-auto p-6">
      <ViewScaffold view={view} />
    </div>
  )
}
