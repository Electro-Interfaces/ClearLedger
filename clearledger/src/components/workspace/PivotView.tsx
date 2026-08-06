/**
 * Сводная таблица: пользователь сам собирает разрез.
 *
 * Сервер отдаёт только листья (агрегаты по НАБОРУ измерений), дерево и подытоги
 * собирает браузер (`services/fuel/pivotTree.ts`). Отсюда главное свойство экрана:
 * **перестановка уровней не идёт в сеть**. Ключ кэша строится по отсортированному
 * набору измерений, поэтому «АЗС → топливо» и «топливо → АЗС» это один запрос.
 *
 * Конструктор двухзонный: слева выбранные уровни (перетаскиваются мышью), справа
 * палитра невыбранных (добавляются кликом). Оба способа обязательны: HTML5 drag&drop
 * на тач-устройствах не работает вовсе, и без клика телефон остался бы без сводной.
 *
 * Фильтры, период и KPI берутся с самой страницы - второй раз их не делаем. Поэтому
 * итог сводной обязан совпадать с карточками страницы до копейки.
 *
 * Компонент общий на все экраны со сводной: источник (реализации, приёмка ТТН), его
 * измерения и метрики приходят пропсами. Метрики разные не для красоты - приёмку
 * сверяют по массе, продажи считают в литрах и рублях, и одна зашитая тройка колонок
 * одному из экранов всегда врала бы.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Download, GripVertical, Loader2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  allExpandablePaths, buildPivotTree, flattenVisible, reorderDims, type PivotNode,
} from '@/services/fuel/pivotTree'
import { exportPivotToExcel } from '@/services/fuel/pivotExport'
import { getPivotCatalog, type PivotMetricDef, type PivotResp } from '@/services/fuel/fuelMappingService'

const nfInt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

/** Формат по числу знаков из справочника метрик источника (кг и литры точнее рублей). */
function fmt(v: number, digits: number): string {
  if (digits === 0) return nfInt.format(v)
  const d = Math.min(digits, 2)
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d }).format(v)
}

function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function PivotView({
  source, storageKey, defaultDims, fetchLeaves, fetchCatalog, queryKey,
  dateFrom, dateTo, scopeLabel, hint,
}: {
  /** Источник в реестре сервера: `transactions` | `receipts` | `store_*`. */
  source: string
  /** Своя память разреза на каждый экран: у приёмки и продаж разрезы разные. */
  storageKey: string
  defaultDims: string[]
  /** Загрузка листьев по набору измерений (фильтры экран подставляет сам). */
  fetchLeaves: (dims: string[]) => Promise<PivotResp>
  /** Справочник измерений источника. По умолчанию — реестр топлива: там
      сводная появилась первой. «Магазин» держит свой реестр и передаёт его
      сюда, иначе один экран знал бы про измерения другого. */
  fetchCatalog?: (source: string) => Promise<{ dims: { key: string; label: string }[]; metrics: PivotMetricDef[] }>
  /** Часть ключа кэша, зависящая от фильтров экрана. */
  queryKey: unknown
  dateFrom: string
  dateTo: string
  /** Подпись отбора для шапки Excel (АЗС, сегмент). */
  scopeLabel?: string
  hint?: string
}) {
  const [dims, setDims] = useState<string[]>(() => readStored(`${storageKey}:dims`, defaultDims))
  const [metric, setMetric] = useState<string>(() => readStored(`${storageKey}:metric`, ''))
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => { localStorage.setItem(`${storageKey}:dims`, JSON.stringify(dims)) }, [dims, storageKey])
  useEffect(() => {
    if (metric) localStorage.setItem(`${storageKey}:metric`, JSON.stringify(metric))
  }, [metric, storageKey])

  const catalog = useQuery({
    queryKey: ['pivot-catalog', source],
    queryFn: () => (fetchCatalog ?? getPivotCatalog)(source),
    staleTime: 60 * 60_000,
  })
  const labelOf = useMemo(() => {
    const m = new Map((catalog.data?.dims ?? []).map((d) => [d.key, d.label]))
    return (k: string) => m.get(k) ?? k
  }, [catalog.data])

  // Ключ кэша — ОТСОРТИРОВАННЫЙ набор: порядок уровней меняет только сборку дерева.
  const sortedDims = useMemo(() => [...dims].sort(), [dims])
  const pivot = useQuery({
    queryKey: ['pivot', source, queryKey, sortedDims],
    queryFn: () => fetchLeaves(sortedDims),
    enabled: sortedDims.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })

  const metrics: PivotMetricDef[] = pivot.data?.metrics ?? catalog.data?.metrics ?? []
  // Метрика сортировки: сохранённая, если она есть у источника, иначе вторая по счёту
  // (первая обычно «сколько документов», а сортировать интереснее по объёму).
  const activeMetric = metrics.some((m) => m.key === metric)
    ? metric
    : (metrics[1]?.key ?? metrics[0]?.key ?? '')
  useEffect(() => { if (!metric && activeMetric) setMetric(activeMetric) }, [metric, activeMetric])

  const labeler = useMemo(() => {
    const names = pivot.data?.stationNames ?? {}
    return (dim: string, value: string | null) => {
      if (value === null || value === '') return '— не указано —'
      if (dim === 'station') return names[value] ?? `АЗС ${value}`
      if (dim === 'hour') return `${value}:00`
      if (dim === 'weekday') return ['', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][Number(value)] ?? value
      return value
    }
  }, [pivot.data])

  const { nodes, totals } = useMemo(
    () => buildPivotTree(pivot.data?.rows ?? [], pivot.data?.dims ?? [], dims, activeMetric, labeler),
    [pivot.data, dims, activeMetric, labeler],
  )
  const visible = useMemo(() => flattenVisible(nodes, expanded), [nodes, expanded])
  const available = (catalog.data?.dims ?? []).filter((d) => !dims.includes(d.key))

  const toggleNode = (path: string) => setExpanded((s) => {
    const n = new Set(s)
    if (n.has(path)) n.delete(path); else n.add(path)
    return n
  })

  const addDim = (key: string) => setDims((d) => (d.length >= 5 ? d : [...d, key]))
  const removeDim = (key: string) => setDims((d) => d.filter((x) => x !== key))
  const onDrop = (to: number) => {
    if (dragFrom === null) return
    setDims((d) => reorderDims(d, dragFrom, to))
    setDragFrom(null)
  }

  async function runExport() {
    setExporting(true)
    try {
      await exportPivotToExcel({
        nodes, totals, dims, dimLabels: dims.map(labelOf), metrics,
        sortBy: activeMetric,
        leaves: pivot.data?.rows ?? [], serverDims: pivot.data?.dims ?? [],
        labeler, dateFrom, dateTo, scopeLabel,
      })
      toast.success('Сводная выгружена')
    } catch (e) {
      // Молчаливый catch здесь стоил бы отладки: «экспорт не работает» без зацепок.
      console.error('Экспорт сводной:', e)
      toast.error('Не удалось выгрузить сводную', { description: (e as Error).message })
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="min-w-0 space-y-3">
      {/* ── Конструктор разреза ─────────────────────────────────────────── */}
      <div className="rounded-lg border border-border/60 bg-card/60 p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Уровни:</span>
            {dims.map((key, i) => (
              <span
                key={key}
                draggable
                onDragStart={() => setDragFrom(i)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => onDrop(i)}
                onDragEnd={() => setDragFrom(null)}
                className={cn(
                  'inline-flex cursor-grab items-center gap-1 rounded-md border px-2 py-1 text-xs',
                  dragFrom === i ? 'border-primary bg-primary/10' : 'border-border bg-background',
                )}
                title="Перетащите, чтобы изменить порядок"
              >
                <GripVertical className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono text-[10px] text-muted-foreground">{i + 1}</span>
                {labelOf(key)}
                {/* Крестик и клик по палитре — единственная механика на телефоне:
                    HTML5 drag&drop там не работает. */}
                <button type="button" onClick={() => removeDim(key)} aria-label={`Убрать ${labelOf(key)}`}
                  className="text-muted-foreground hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {dims.length === 0 && <span className="text-xs text-muted-foreground">добавьте измерение справа</span>}
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Добавить:</span>
            {available.map((d) => (
              <button key={d.key} type="button" onClick={() => addDim(d.key)} disabled={dims.length >= 5}
                className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-xs text-muted-foreground hover:border-primary/60 hover:text-foreground disabled:opacity-40">
                <Plus className="h-3 w-3" />{d.label}
              </button>
            ))}
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            {metrics.map((m) => (
              <button key={m.key} type="button" onClick={() => setMetric(m.key)}
                title={`Сортировка и доли по «${m.label}»`}
                className={cn('rounded-md px-2 py-1 text-xs',
                  activeMetric === m.key ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground')}>
                {m.label}
              </button>
            ))}
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={runExport}
              disabled={exporting || !nodes.length}>
              {exporting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1 h-3.5 w-3.5" />}
              Excel
            </Button>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <button type="button" onClick={() => setExpanded(new Set(allExpandablePaths(nodes)))}
            className="hover:text-foreground">развернуть всё</button>
          <span>·</span>
          <button type="button" onClick={() => setExpanded(new Set())} className="hover:text-foreground">свернуть</button>
          <span>·</span>
          <span>{hint ?? 'сортировка по выбранной метрике, доля считается от родителя'}</span>
          {pivot.isFetching && <Loader2 className="h-3 w-3 animate-spin" />}
        </div>
      </div>

      {pivot.data?.truncated && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          Разрез упёрся в потолок строк. Уточните период или уберите измерение: показана часть данных.
        </div>
      )}

      {/* ── Дерево ──────────────────────────────────────────────────────── */}
      <div className="min-w-0 overflow-x-auto rounded-lg border border-border/60">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Разрез</th>
              {metrics.map((m) => (
                <th key={m.key} className="px-3 py-2 text-right font-medium">{m.label}</th>
              ))}
              <th className="px-3 py-2 text-right font-medium">Доля</th>
            </tr>
          </thead>
          <tbody>
            {pivot.isLoading ? (
              <tr><td colSpan={metrics.length + 2} className="py-10 text-center">
                <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
              </td></tr>
            ) : !visible.length ? (
              <tr><td colSpan={metrics.length + 2} className="py-10 text-center text-sm text-muted-foreground">
                Нет данных по выбранным фильтрам.
              </td></tr>
            ) : visible.map((n) => (
              <Row key={n.path} node={n} metrics={metrics} expanded={expanded.has(n.path)} onToggle={toggleNode} />
            ))}
          </tbody>
          {visible.length > 0 && (
            <tfoot className="border-t-2 border-border bg-muted/30 font-semibold">
              <tr>
                <td className="px-3 py-2">Итого</td>
                {metrics.map((m) => (
                  <td key={m.key} className="px-3 py-2 text-right tabular-nums">
                    {fmt(totals[m.key] ?? 0, m.digits)}
                  </td>
                ))}
                <td className="px-3 py-2 text-right">100 %</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  )
}

function Row({ node, metrics, expanded, onToggle }: {
  node: PivotNode
  metrics: PivotMetricDef[]
  expanded: boolean
  onToggle: (p: string) => void
}) {
  const canOpen = node.children.length > 0
  return (
    <tr className={cn('border-t border-border/40', node.level === 0 && 'bg-muted/10')}>
      <td className="px-3 py-1.5">
        <button type="button" onClick={() => canOpen && onToggle(node.path)}
          className={cn('flex items-center gap-1 text-left', canOpen ? 'hover:text-primary' : 'cursor-default')}
          style={{ paddingLeft: node.level * 16 }}>
          {canOpen
            ? (expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />)
            : <span className="w-3.5 shrink-0" />}
          <span className={cn(node.level === 0 && 'font-medium')}>{node.label}</span>
        </button>
      </td>
      {metrics.map((m) => (
        <td key={m.key} className="px-3 py-1.5 text-right tabular-nums">
          {fmt(node.m[m.key] ?? 0, m.digits)}
        </td>
      ))}
      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
        {(node.share * 100).toFixed(1)} %
      </td>
    </tr>
  )
}
