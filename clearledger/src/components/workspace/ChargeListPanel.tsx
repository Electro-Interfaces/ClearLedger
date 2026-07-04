/**
 * «Список» — полноценный реестр транзакций ЭЗС (все загруженные ChargeSession).
 * Таблица построчных сессий с поиском, фильтрами, сортировкой, пагинацией и
 * выгрузкой в Excel. Всё на клиенте: данные — существующий /charge-sessions/rows,
 * без серверного поиска/пагинации (backend не трогаем).
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Search, Download, AlertTriangle, ChevronsUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DualScrollX } from '@/components/common/DualScrollX'
import { PaginationWrapper } from '@/components/common/PaginationWrapper'
import { PeriodRangePicker } from './analytics/PeriodRangePicker'
import { type Period } from './analytics/periodPresets'
import { useTabParams } from '@/hooks/useTabParams'
import { loadXlsx } from '@/utils/xlsxLoader'
import { getChargeSessionRows, fmtMoney, type ChargeSessionRow } from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const ALL = '__all__'

function fmtDT(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

type SortKey = 'started_at' | 'station' | 'region' | 'connector' | 'user_type' | 'client'
  | 'charge_type' | 'energy_kwh' | 'duration_min' | 'tariff' | 'amount' | 'result'

const NUM_KEYS: SortKey[] = ['energy_kwh', 'duration_min', 'tariff', 'amount']

function rowVal(r: ChargeSessionRow, k: SortKey): string | number {
  switch (k) {
    case 'station': return r.station_name ?? r.station_code ?? ''
    case 'region': return r.region ?? ''
    case 'connector': return r.connector_type ?? ''
    case 'user_type': return r.user_type ?? ''
    case 'client': return r.client_name ?? ''
    case 'charge_type': return r.charge_type ?? ''
    case 'result': return r.result ?? ''
    case 'started_at': return r.started_at ?? ''
    default: return (r as unknown as Record<string, number>)[k] ?? 0
  }
}

const DEFAULTS = {
  override: null as Period | null,
  userType: 'all', region: ALL, connector: ALL, result: ALL, paid: 'all',
  sortKey: 'started_at' as SortKey, sortDir: 'desc' as 'asc' | 'desc',
}

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}

/** Сортируемый заголовок таблицы. */
function SortTh({ k, label, right, sortKey, sortDir, onSort }: {
  k: SortKey; label: string; right?: boolean; sortKey: SortKey; sortDir: 'asc' | 'desc'; onSort: (k: SortKey) => void
}) {
  const Icon = sortKey === k ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  return (
    <TableHead className={`cursor-pointer select-none whitespace-nowrap hover:text-foreground ${right ? 'text-right' : ''}`} onClick={() => onSort(k)}>
      <span className={`inline-flex items-center gap-0.5 ${right ? 'flex-row-reverse' : ''}`}>{label}<Icon className={`h-3 w-3 ${sortKey === k ? 'text-foreground' : 'text-muted-foreground/40'}`} /></span>
    </TableHead>
  )
}

function FilterSelect({ value, onChange, allLabel, options, width = 'w-[150px]' }: {
  value: string; onChange: (v: string) => void; allLabel: string; options: string[]; width?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={`h-8 ${width} text-xs`}><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL} className="text-xs">{allLabel}</SelectItem>
        {options.map((o) => <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

export function ChargeListPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [p, patch] = useTabParams('cs_list', DEFAULTS)
  const period = p.override ?? { from: dateFrom, to: dateTo }
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [exporting, setExporting] = useState(false)

  // debounce поиска
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const { data, isLoading } = useQuery({
    queryKey: ['charge-rows', companyId, period.from, period.to],
    queryFn: () => getChargeSessionRows({ companyId, dateFrom: period.from, dateTo: period.to, limit: 200000 }),
  })
  const rows = useMemo(() => data?.rows ?? [], [data])

  // distinct-опции фильтров (один проход)
  const opts = useMemo(() => {
    const reg = new Set<string>(), conn = new Set<string>(), res = new Set<string>()
    for (const r of rows) {
      if (r.region) reg.add(r.region)
      if (r.connector_type) conn.add(r.connector_type)
      if (r.result) res.add(r.result)
    }
    const s = (a: string, b: string) => a.localeCompare(b, 'ru')
    return { regions: [...reg].sort(s), connectors: [...conn].sort(s), results: [...res].sort(s) }
  }, [rows])

  const filtered = useMemo(() => {
    const wantType = p.userType === 'fl' ? 'ФЛ' : p.userType === 'ul' ? 'ЮЛ' : null
    return rows.filter((r) => {
      if (wantType && (r.user_type ?? '') !== wantType) return false
      if (p.region !== ALL && (r.region ?? '') !== p.region) return false
      if (p.connector !== ALL && (r.connector_type ?? '') !== p.connector) return false
      if (p.result !== ALL && (r.result ?? '') !== p.result) return false
      if (p.paid === 'paid' && !r.paid_at) return false
      if (p.paid === 'unpaid' && r.paid_at) return false
      if (search) {
        const hay = `${r.session_ext_id} ${r.station_code ?? ''} ${r.station_name ?? ''} ${r.client_name ?? ''}`.toLowerCase()
        if (!hay.includes(search)) return false
      }
      return true
    })
  }, [rows, p.userType, p.region, p.connector, p.result, p.paid, search])

  const sorted = useMemo(() => {
    const dir = p.sortDir === 'asc' ? 1 : -1
    const numeric = NUM_KEYS.includes(p.sortKey)
    return [...filtered].sort((a, b) => {
      const va = rowVal(a, p.sortKey), vb = rowVal(b, p.sortKey)
      if (numeric) return dir * ((va as number) - (vb as number))
      return dir * String(va).localeCompare(String(vb), 'ru')
    })
  }, [filtered, p.sortKey, p.sortDir])

  // сброс страницы при смене выборки
  useEffect(() => { setPage(1) }, [search, p.userType, p.region, p.connector, p.result, p.paid, period.from, period.to])

  const pageRows = useMemo(() => sorted.slice((page - 1) * pageSize, page * pageSize), [sorted, page, pageSize])
  const toggleSort = (k: SortKey) => patch({ sortKey: k, sortDir: p.sortKey === k && p.sortDir === 'desc' ? 'asc' : 'desc' })

  const doExport = async () => {
    setExporting(true)
    try {
      const XLSX = await loadXlsx()
      const out = sorted.map((r) => ({
        'ID сессии': r.session_ext_id,
        'Начало': fmtDT(r.started_at),
        'Станция': r.station_name || r.station_code || '',
        'Код станции': r.station_code || '',
        'Регион': r.region || '',
        'Коннектор': r.connector_type || '',
        'Тип клиента': r.user_type || '',
        'Клиент (ЮЛ)': r.client_name || '',
        'Канал запуска': r.charge_type || '',
        'Энергия кВтч': Number(r.energy_kwh) || 0,
        'Длительность мин': Number(r.duration_min) || 0,
        'Тариф ₽/кВтч': Number(r.tariff) || 0,
        'Выручка ₽': Number(r.amount) || 0,
        'Исход': r.result || '',
        'Оплата': r.paid_at ? fmtDT(r.paid_at) : '',
      }))
      const ws = XLSX.utils.json_to_sheet(out)
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Транзакции')
      XLSX.writeFile(wb, `transactions_${period.from}_${period.to}.xlsx`)
    } finally {
      setExporting(false)
    }
  }

  const th = (k: SortKey, label: string, right?: boolean) =>
    <SortTh k={k} label={label} right={right} sortKey={p.sortKey} sortDir={p.sortDir} onSort={toggleSort} />

  return (
    <div className="space-y-3 p-4">
      {/* тулбар */}
      <div className="flex flex-wrap items-center gap-2" data-export-ignore>
        {p.override ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-amber-400/70">Свой период</span>
            <PeriodRangePicker period={p.override} onChange={(o) => patch({ override: o })} />
            <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={() => patch({ override: null })}>← период раздела</Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Период: <span className="font-mono">{dateFrom} — {dateTo}</span></span>
            <Button variant="outline" size="sm" className="h-8 px-2 text-xs" onClick={() => patch({ override: { from: dateFrom, to: dateTo } })}>Свой период</Button>
          </div>
        )}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Поиск: станция, клиент, ID…" className="h-8 w-[240px] pl-8 text-xs" />
        </div>
        <Select value={p.userType} onValueChange={(v) => patch({ userType: v })}>
          <SelectTrigger className="h-8 w-[110px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все клиенты</SelectItem>
            <SelectItem value="fl" className="text-xs">ФЛ</SelectItem>
            <SelectItem value="ul" className="text-xs">ЮЛ</SelectItem>
          </SelectContent>
        </Select>
        <FilterSelect value={p.region} onChange={(v) => patch({ region: v })} allLabel="Все регионы" options={opts.regions} />
        <FilterSelect value={p.connector} onChange={(v) => patch({ connector: v })} allLabel="Все коннекторы" options={opts.connectors} width="w-[150px]" />
        <FilterSelect value={p.result} onChange={(v) => patch({ result: v })} allLabel="Все исходы" options={opts.results} width="w-[130px]" />
        <Select value={p.paid} onValueChange={(v) => patch({ paid: v })}>
          <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Оплата: все</SelectItem>
            <SelectItem value="paid" className="text-xs">Оплачено</SelectItem>
            <SelectItem value="unpaid" className="text-xs">Не оплачено</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" className="ml-auto h-8 gap-1 px-2 text-xs" onClick={doExport} disabled={exporting || sorted.length === 0}>
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Выгрузить в Excel
        </Button>
      </div>

      {/* счётчик + truncated */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" data-export-ignore>
        <span>Показано <b className="text-foreground">{nf0.format(filtered.length)}</b> из {nf0.format(rows.length)} транзакций{filtered.length !== rows.length ? ' (после фильтров)' : ''}</span>
        {data?.truncated && (
          <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />Показаны не все строки — сузьте период
          </span>
        )}
      </div>

      {isLoading ? <Loading /> : rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">Нет транзакций за период</div>
      ) : (
        <>
          <DualScrollX>
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  {th('started_at', 'Начало')}
                  {th('station', 'Станция')}
                  {th('region', 'Регион')}
                  {th('connector', 'Коннектор')}
                  {th('user_type', 'Тип')}
                  {th('client', 'Клиент (ЮЛ)')}
                  {th('charge_type', 'Канал')}
                  {th('energy_kwh', 'Энергия, кВтч', true)}
                  {th('duration_min', 'Длит., мин', true)}
                  {th('tariff', 'Тариф ₽/кВтч', true)}
                  {th('amount', 'Выручка, ₽', true)}
                  {th('result', 'Исход')}
                  <TableHead className="text-center">Оплата</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageRows.map((r) => (
                  <TableRow key={r.session_ext_id}>
                    <TableCell className="whitespace-nowrap font-mono text-muted-foreground">{fmtDT(r.started_at)}</TableCell>
                    <TableCell className="max-w-[220px] truncate font-medium" title={`${r.station_name ?? ''} (${r.station_code ?? '—'})`}>{r.station_name || r.station_code || '—'}</TableCell>
                    <TableCell className="max-w-[160px] truncate">{r.region || '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.connector_type || '—'}</TableCell>
                    <TableCell>{r.user_type || '—'}</TableCell>
                    <TableCell className="max-w-[200px] truncate" title={r.client_name ?? ''}>{r.client_name || '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.charge_type || '—'}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{nf1.format(r.energy_kwh)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{nf0.format(r.duration_min)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtMoney(r.tariff)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtMoney(r.amount)}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.result || '—'}</TableCell>
                    <TableCell className="text-center">
                      {r.paid_at ? <span className="text-emerald-400" title={fmtDT(r.paid_at)}>✓</span> : <span className="text-muted-foreground/50">✗</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DualScrollX>
          <PaginationWrapper total={filtered.length} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
        </>
      )}
    </div>
  )
}
