/**
 * Контекст рабочего стола — синхронизация между панелями.
 * Клик в RawPanel → selectedShift → CorePanel показывает детали.
 */

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

// `projects_analytics` — второй раздел продукта «Проекты»: работа и аналитика
// разведены по левой рельсе, пункты каждого живут во второй панели.
// `sales_sessions`/`sales_commerce` — то же для «Продаж»: `management` остался
// разделом «Сеть» (у топливного профиля — весь его «Продажи»), к нему добавились
// «Сессии» и «Коммерция» (решение МАГа 28.07.2026).
// `ops_equipment`/`ops_economy` — то же для «Эксплуатации»: `operations` остался
// разделом «Мониторинг» (у топливного профиля — его «Управленческий»).
// `store_stock`/`store_closing`/`store_catalog`/`store_marking` — разделы «Магазина»:
// склад, закрытие дня, карточка товара, маркировка. `store` остался кодом первого
// раздела («Торговля») — по нему идут старые ссылки и ключ доступа.
// `sales_goods` — «Товародвижение» «Топлива» (fuel): топливо как товар — маржа,
// приход, книга резервуаров. У ЭЗС такого раздела нет: там продают киловатт-часы,
// склада и приёмки не бывает.
export type CoreMode = 'normalize' | 'reconcile' | 'management' | 'sales_sessions' | 'sales_commerce' | 'sales_goods' | 'sales_help' | 'operations' | 'ops_equipment' | 'ops_economy' | 'projects' | 'projects_analytics' | 'store' | 'store_stock' | 'store_closing' | 'store_catalog' | 'store_marking' | 'corporate' | 'marketing' | 'financial' | 'accounting' | 'tax' | 'export'

const VALID_MODES: CoreMode[] = ['normalize', 'reconcile', 'management', 'sales_sessions', 'sales_commerce', 'sales_goods', 'sales_help', 'operations', 'ops_equipment', 'ops_economy', 'projects', 'projects_analytics', 'store', 'store_stock', 'store_closing', 'store_catalog', 'store_marking', 'corporate', 'marketing', 'financial', 'accounting', 'tax', 'export']
function readMode(sp: URLSearchParams): CoreMode {
  const m = sp.get('mode')
  return m && (VALID_MODES as string[]).includes(m) ? (m as CoreMode) : 'management'
}

/**
 * Под-вид панели рабочего стола (URL-параметр `sub`) — чтобы закладка запоминала
 * точный под-раздел («Финансовый · Дебиторка»). Валидируется по набору ключей
 * панели; невалидное значение (после смены режима) откатывается к дефолту.
 */
export function useWorkspaceSubView(defaultKey: string, validKeys?: string[]): [string, (v: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('sub')
  const value = raw && (!validKeys || validKeys.includes(raw)) ? raw : defaultKey
  const set = useCallback((v: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('sub', v)
      return next
    }, { replace: true })
  }, [setSearchParams])
  return [value, set]
}

interface ExportDocument {
  id: string
  type: 'receipt' | 'transfer' | 'assembly' | 'retail_sales'
  label: string
  sourceShift: number
  stationId: number
  status: 'draft' | 'confirmed' | 'exported'
  createdAt: string
}

interface WorkspaceContextType {
  /** Выбранная станция */
  selectedStationId: number | null
  /** Выбранная смена */
  selectedShiftNumber: number | null
  /** Активная вкладка (mobile) */
  activeTab: 'raw' | 'core' | 'export'

  /** Выбрать смену (из RawPanel) */
  selectShift: (stationId: number, shiftNumber: number) => void
  /** Сбросить выбор */
  clearSelection: () => void
  /** Переключить вкладку (mobile) */
  setActiveTab: (tab: 'raw' | 'core' | 'export') => void

  /** Режим центральной панели — конвейер слева направо */
  coreMode: CoreMode
  setCoreMode: (mode: CoreMode, sub?: string) => void
  /** Разделы, которыми ограничена оболочка: рабочая область открыта как отдельный
   *  продукт пространства (напр. «Финансы» на `/finance`), и переключаться можно
   *  только внутри его разделов. `null` — Учёт со всеми своими разделами. */
  lockedModes: CoreMode[] | null

  /** Результат последней сверки (для KPI в тулбаре) */
  lastReconcileResult: unknown | null
  setLastReconcileResult: (result: unknown | null) => void

  /** Документы для экспорта в 1С */
  exportDocs: ExportDocument[]
  /** Добавить документ в Export */
  addExportDoc: (doc: ExportDocument) => void
  /** Убрать документ из Export */
  removeExportDoc: (id: string) => void
  /** Пометить как выгруженный */
  markExported: (id: string) => void
}

const WorkspaceContext = createContext<WorkspaceContextType | null>(null)

/**
 * `lockModes` — рабочая область открыта как отдельный продукт пространства (свой маршрут
 * и плитка на столе), а не как раздел Учёта: доступны только эти разделы. Внутри набора
 * переключение обычное (`?mode=`), выйти за него нельзя — чужой режим из URL откатывается
 * к первому разделу продукта.
 */
export function WorkspaceProvider({ children, lockModes }: { children: ReactNode; lockModes?: CoreMode[] }) {
  const [selectedStationId, setSelectedStationId] = useState<number | null>(null)
  const [selectedShiftNumber, setSelectedShiftNumber] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<'raw' | 'core' | 'export'>('raw')
  // Режим центральной панели живёт в URL (?mode=) — чтобы под-вид можно было закрепить закладкой.
  const [searchParams, setSearchParams] = useSearchParams()
  const urlMode = readMode(searchParams)
  const coreMode = lockModes
    ? (lockModes.includes(urlMode) ? urlMode : lockModes[0])
    : urlMode
  // `sub` необязателен: без него раздел открывается со своего первого пункта, с ним —
  // на нужном. Второе понадобилось, когда пункт живёт в чужом разделе: старая ссылка
  // `?mode=store&sub=inventory` должна привести в «Склад» НА «Инвентаризацию», а не
  // просто в «Склад» — иначе закладка каждый раз падает на первый пункт.
  const setCoreMode = useCallback((mode: CoreMode, sub?: string) => {
    if (lockModes && !lockModes.includes(mode)) return   // за пределы продукта не пускаем
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('mode', mode)
      if (sub) next.set('sub', sub)
      else next.delete('sub')   // без пункта — со своего под-раздела по умолчанию
      return next
    }, { replace: true })
  }, [setSearchParams, lockModes])
  const [lastReconcileResult, setLastReconcileResult] = useState<unknown | null>(null)
  const [exportDocs, setExportDocs] = useState<ExportDocument[]>([])

  const selectShift = useCallback((stationId: number, shiftNumber: number) => {
    setSelectedStationId(stationId)
    setSelectedShiftNumber(shiftNumber)
    setActiveTab('core') // на мобильном автопереключение на Core
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedStationId(null)
    setSelectedShiftNumber(null)
  }, [])

  const addExportDoc = useCallback((doc: ExportDocument) => {
    setExportDocs((prev) => {
      if (prev.some((d) => d.id === doc.id)) return prev
      return [...prev, doc]
    })
  }, [])

  const removeExportDoc = useCallback((id: string) => {
    setExportDocs((prev) => prev.filter((d) => d.id !== id))
  }, [])

  const markExported = useCallback((id: string) => {
    setExportDocs((prev) =>
      prev.map((d) => (d.id === id ? { ...d, status: 'exported' as const } : d)),
    )
  }, [])

  return (
    <WorkspaceContext.Provider
      value={{
        selectedStationId,
        selectedShiftNumber,
        activeTab,
        selectShift,
        clearSelection,
        setActiveTab,
        coreMode,
        setCoreMode,
        lockedModes: lockModes ?? null,
        lastReconcileResult,
        setLastReconcileResult,
        exportDocs,
        addExportDoc,
        removeExportDoc,
        markExported,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return ctx
}
