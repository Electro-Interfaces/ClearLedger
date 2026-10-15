import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { deriveTotals, feedNumber, withCalc, type CalcCol } from './calc'
import type { Cell } from './format'
import { closePanel, setRail, useRail } from './rail'
import { keepRow, type Cols, type Filters, type Picked } from './SheetTable'

export const STORAGE_PREFIX = 'report-kit.v1'

function useStored<T>(key: string, init: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : init
    } catch {
      return init
    }
  })
  const set = useCallback(
    (v: T) => {
      setValue(v)
      try {
        localStorage.setItem(key, JSON.stringify(v))
      } catch {
        return
      }
    },
    [key],
  )
  return [value, set]
}

export function useReportKit({
  id,
  title,
  head,
  rows,
  total,
  hide,
  ready,
  pivot = false,
  share = '',
  help = null,
}: {
  id: string
  title: string
  head: string[]
  rows: Cell[][]
  total?: Cell[]
  hide?: number[]
  ready: boolean
  pivot?: boolean
  share?: string
  help?: ReactNode
}) {
  const defaultCols = useMemo<Cols>(() => ({ order: [], hidden: hide ?? [] }), [hide])
  const [cols, setCols] = useStored<Cols>(`${STORAGE_PREFIX}:cols:${id}`, defaultCols)
  const [calcs, setCalcs] = useStored<CalcCol[]>(`${STORAGE_PREFIX}:calc:${id}`, [])
  const [rawFilters, setFilters] = useState<Filters>({})
  const [search, setSearch] = useState('')
  const [at, setAt] = useState(0)
  const [hits, setHits] = useState(0)
  const [picks, setPicks] = useState<{ rows: Cell[][]; map: Map<string, Picked> }>({ rows, map: new Map() })
  const { panel } = useRail()

  useEffect(() => {
    setRail({ available: true, title, tools: ready, pivot, share, help })
  }, [title, ready, pivot, share, help])
  useEffect(() => () => setRail({ available: false, panel: null, tools: false, pivot: false, share: '', help: null }), [])

  const sheet = useMemo(() => withCalc({ head, rows, total }, calcs), [head, rows, total, calcs])
  const derive = useMemo(() => deriveTotals(sheet.head, calcs), [sheet.head, calcs])

  const filters = useMemo<Filters>(
    () => Object.fromEntries(Object.entries(rawFilters).filter(([k]) => Number(k) < sheet.head.length)),
    [rawFilters, sheet.head.length],
  )
  const sel = useMemo(() => (picks.rows === rows ? picks.map : new Map<string, Picked>()), [picks, rows])

  const picking = panel === 'calc'
  const onPick = useCallback(
    (c: Picked) => {
      const next = new Map(sel)
      if (next.has(c.key)) next.delete(c.key)
      else {
        next.set(c.key, c)
        if (typeof c.value === 'number') feedNumber(c.value)
      }
      setPicks({ rows, map: next })
    },
    [sel, rows],
  )
  const selected = useMemo(() => new Set(sel.keys()), [sel])
  const kept = useMemo(() => sheet.rows.map((r, i) => (keepRow(r, filters) ? i : -1)).filter((i) => i >= 0), [sheet.rows, filters])

  return {
    sheet,
    filters,
    setFilters,
    kept,
    panel,
    table: {
      head: sheet.head,
      rows: sheet.rows,
      total: sheet.total,
      cols,
      onCols: setCols,
      filters,
      onFilters: setFilters,
      search: panel === 'search' ? search : '',
      searchAt: at,
      onHits: setHits,
      selected: picking ? selected : undefined,
      onPick: picking ? onPick : undefined,
      derive,
    },
    tools: {
      panel: panel ?? 'help',
      report: title,
      onClose: closePanel,
      sel: [...sel.values()],
      onClearSel: () => setPicks({ rows, map: new Map() }),
      head: sheet.head,
      cols,
      onCols: setCols,
      defaultCols,
      rows: sheet.rows,
      calcs,
      onCalcs: setCalcs,
      search,
      onSearch: setSearch,
      hits,
      at,
      onAt: setAt,
    },
  }
}
