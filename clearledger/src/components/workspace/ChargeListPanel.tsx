/**
 * «Список» — полноценный реестр транзакций ЭЗС (все загруженные ChargeSession).
 * Таблица построчных сессий с поиском, фильтрами, сортировкой, пагинацией и
 * выгрузкой в Excel. Поиск, фильтры, сортировка и пагинация выполняются в БД,
 * чтобы браузер не загружал целиком годовой реестр.
 */

import { useDeferredValue, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Search, Download, ChevronsUpDown, ArrowUp, ArrowDown, Layers } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DualScrollX } from '@/components/common/DualScrollX'
import { PaginationWrapper } from '@/components/common/PaginationWrapper'
import { useTabParams } from '@/hooks/useTabParams'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import { loadXlsx } from '@/utils/xlsxLoader'
import { getChargeSessionRows, getChargeGroupCatalog, fmtMoney, type ChargeSessionRow } from '@/services/analyticsService'
import { useFilters } from '@/contexts/FilterContext'
import { ChargeGroupedView } from './ChargeGroupedView'

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
  | 'charge_type' | 'energy_kwh' | 'duration_min' | 'tariff' | 'revenue' | 'result'

/** Расшифровка «канала запуска» сессии (сырые коды выгрузки ПК). */
const CHARGE_TYPE_LABEL: Record<string, string> = {
  USER: 'Приложение', ADMIN: 'Оператор', RFID: 'Карта RFID',
}
const chargeTypeLabel = (v: string | null): string =>
  v ? (CHARGE_TYPE_LABEL[v.toUpperCase()] ?? v) : '—'

const DEFAULTS = {
  userType: 'all', region: ALL, connector: ALL, result: ALL, paid: 'all',
  sortKey: 'started_at' as SortKey, sortDir: 'desc' as 'asc' | 'desc',
  // Разрез реестра ('none' — плоский список). Это «представление», а не
  // контур, поэтому персистится по (компания × пункт) вместе с сортировкой.
  groupBy: 'none',
}

/** Подписи разделов селектора группировки — порядок задаёт бэкенд (GROUPS). */
const FAMILY_LABEL: Record<string, string> = {
  'сеть': 'Сеть', 'клиент': 'Клиент', 'процесс': 'Процесс',
  'время': 'Время', 'визит': 'Визиты',
  // Оборудование — паспорт станции из справочника (бренд, мощность, площадка).
  // Распределения — как устроена масса сессий, а не «сколько всего».
  'оборудование': 'Оборудование', 'распределения': 'Распределения',
}

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}

/** Сортируемый заголовок таблицы. */
function SortTh({ k, label, right, sortKey, sortDir, onSort }: {
  k: SortKey; label: string; right?: boolean; sortKey: SortKey; sortDir: 'asc' | 'desc'; onSort: (k: SortKey) => void
}) {
  const active = sortKey === k
  const Icon = active ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  // aria-sort → скринридер объявляет направление сортировки колонки (WCAG).
  const ariaSort: 'ascending' | 'descending' | 'none' = active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <TableHead className={`whitespace-nowrap ${right ? 'text-right' : ''}`} aria-sort={ariaSort}>
      {/* <button> вместо onClick на <th>: операбельно с клавиатуры + фокус (см. index.css) */}
      <button type="button" onClick={() => onSort(k)} aria-label={`Сортировать по «${label}»`}
        className={`inline-flex items-center gap-0.5 rounded select-none cursor-pointer hover:text-foreground ${right ? 'flex-row-reverse' : ''}`}>
        {label}<Icon className={`h-3 w-3 ${active ? 'text-foreground' : 'text-muted-foreground/40'}`} />
      </button>
    </TableHead>
  )
}

function FilterSelect({ value, onChange, allLabel, options, width = 'w-[150px]' }: {
  value: string; onChange: (v: string) => void; allLabel: string; options: string[]; width?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={`h-11 ${width} max-sm:w-full text-sm sm:h-8 sm:text-xs`}><SelectValue /></SelectTrigger>
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
  // Вид-срез (реестр за период): период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  // Сужение по сети из контура (регион/станции) — реестр обязан ему подчиняться,
  // иначе таблица показывает всю сеть при выбранной области (расхождение с шапкой).
  const { stationCodes, regionIds } = useFilters()
  const scopeStations = stationCodes.length ? stationCodes.map(String) : undefined
  const scopeRegions = regionIds.length ? regionIds : undefined
  const scopeKey = `${stationCodes.join(',')}|${regionIds.join(',')}`
  const [searchInput, setSearchInput] = useState('')
  const [page, setPage] = useState(1)
  // Смена контура делает поиск и страницу бессмысленными (CLAUDE.md, правило 5).
  useResetOnScopeChange(() => { setSearchInput(''); setPage(1) })
  const [pageSize, setPageSize] = useState(50)
  const [exporting, setExporting] = useState(false)

  const search = useDeferredValue(searchInput.trim().toLowerCase())

  const grouped = p.groupBy !== 'none'
  const { data: catalog } = useQuery({
    queryKey: ['charge-group-catalog'],
    queryFn: getChargeGroupCatalog,
    staleTime: Infinity,   // справочник разрезов не меняется в рантайме
  })
  const userType = p.userType === 'fl' ? 'ФЛ' : p.userType === 'ul' ? 'ЮЛ' : null
  const paidFilter: 'paid' | 'unpaid' | null = p.paid === 'paid' || p.paid === 'unpaid' ? p.paid : null
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['charge-rows', companyId, period.from, period.to, scopeKey, page, pageSize,
      p.userType, p.region, p.connector, p.result, p.paid, p.sortKey, p.sortDir, search],
    queryFn: () => getChargeSessionRows({
      companyId, dateFrom: period.from, dateTo: period.to,
      limit: pageSize, offset: (page - 1) * pageSize,
      stations: scopeStations, regions: scopeRegions,
      userType, region: p.region === ALL ? null : p.region,
      connector: p.connector === ALL ? null : p.connector,
      result: p.result === ALL ? null : p.result,
      paid: paidFilter,
      search: search || null, sort: p.sortKey, sortDir: p.sortDir,
    }),
    placeholderData: (previous) => previous,
  })
  const rows = data?.rows ?? []
  const opts = data?.facets ?? { regions: [], connectors: [], results: [] }
  const totals = data?.totals ?? { revenue: 0, energy_kwh: 0 }
  const total = data?.total ?? 0
  const patchFilter = (next: Partial<typeof DEFAULTS>) => { setPage(1); patch(next) }
  const toggleSort = (k: SortKey) => patchFilter({ sortKey: k, sortDir: p.sortKey === k && p.sortDir === 'desc' ? 'asc' : 'desc' })

  const doExport = async () => {
    setExporting(true)
    try {
      const XLSX = await loadXlsx()
      const exported = await getChargeSessionRows({
        companyId, dateFrom: period.from, dateTo: period.to,
        limit: Math.min(Math.max(total, 1), 200000), stations: scopeStations, regions: scopeRegions,
        userType, region: p.region === ALL ? null : p.region,
        connector: p.connector === ALL ? null : p.connector,
        result: p.result === ALL ? null : p.result,
        paid: paidFilter,
        search: search || null, sort: p.sortKey, sortDir: p.sortDir,
      })
      const out = exported.rows.map((r: ChargeSessionRow) => ({
        'ID сессии': r.session_ext_id,
        'Начало': fmtDT(r.started_at),
        'Станция': r.station_name || r.station_code || '',
        'Код станции': r.station_code || '',
        'Регион': r.region || '',
        'Коннектор': r.connector_type || '',
        'Тип клиента': r.user_type || '',
        'Клиент (ЮЛ)': r.client_name || '',
        'Канал запуска': r.charge_type ? chargeTypeLabel(r.charge_type) : '',
        'Энергия кВтч': Number(r.energy_kwh) || 0,
        'Длительность мин': Number(r.duration_min) || 0,
        'Тариф ₽/кВтч': Number(r.tariff) || 0,
        'Тариф договора ₽/кВтч': r.client_tariff != null ? Number(r.client_tariff) : '',
        'Выручка ₽': Number(r.revenue) || 0,
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
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchInput} onChange={(e) => { setSearchInput(e.target.value); setPage(1) }} aria-label="Поиск транзакций" placeholder="Поиск: станция, клиент, ID…" className="h-11 w-full pl-8 text-base sm:h-8 sm:w-[240px] sm:text-xs" />
        </div>
        <Select value={p.userType} onValueChange={(v) => patchFilter({ userType: v })}>
          <SelectTrigger className="h-11 w-full text-sm sm:h-8 sm:w-[110px] sm:text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все клиенты</SelectItem>
            <SelectItem value="fl" className="text-xs">ФЛ</SelectItem>
            <SelectItem value="ul" className="text-xs">ЮЛ</SelectItem>
          </SelectContent>
        </Select>
        <FilterSelect value={p.region} onChange={(v) => patchFilter({ region: v })} allLabel="Все регионы" options={opts.regions} />
        <FilterSelect value={p.connector} onChange={(v) => patchFilter({ connector: v })} allLabel="Все коннекторы" options={opts.connectors} width="w-[150px]" />
        <FilterSelect value={p.result} onChange={(v) => patchFilter({ result: v })} allLabel="Все исходы" options={opts.results} width="w-[130px]" />
        <Select value={p.paid} onValueChange={(v) => patchFilter({ paid: v })}>
          <SelectTrigger className="h-11 w-full text-sm sm:h-8 sm:w-[130px] sm:text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Оплата: все</SelectItem>
            <SelectItem value="paid" className="text-xs">Оплачено</SelectItem>
            <SelectItem value="unpaid" className="text-xs">Не оплачено</SelectItem>
          </SelectContent>
        </Select>
        {/* Разрез: тот же набор данных под разными углами. Считает БД —
            свернуть 117 тыс. строк в браузере нечем. */}
        <Select value={p.groupBy} onValueChange={(v) => patch({ groupBy: v })}>
          <SelectTrigger className={`h-11 w-full text-sm sm:h-8 sm:w-[210px] sm:text-xs ${grouped ? 'border-primary/60 text-foreground' : ''}`}>
            <Layers className="h-3.5 w-3.5 shrink-0 opacity-70" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none" className="text-xs">Без группировки (список)</SelectItem>
            {Object.entries(
              (catalog ?? []).reduce<Record<string, typeof catalog>>((acc, g) => {
                (acc[g.family] ??= []).push(g); return acc
              }, {}),
            ).map(([family, defs]) => (
              <SelectGroup key={family}>
                <SelectLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  {FAMILY_LABEL[family] ?? family}
                </SelectLabel>
                {(defs ?? []).map((g) => (
                  <SelectItem key={g.key} value={g.key} className="text-xs">{g.label}</SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" className="ml-auto h-11 gap-1 px-3 text-sm sm:h-8 sm:px-2 sm:text-xs" onClick={doExport} disabled={exporting || total === 0}>
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Выгрузить в Excel
        </Button>
      </div>

      {/* В разрезе счётчик строк списка не показываем: там свои итоги. */}
      {!grouped && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" data-export-ignore>
          <span>Найдено <b className="text-foreground">{nf0.format(total)}</b> транзакций</span>
          {isFetching && <span className="inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" />Обновляем…</span>}
        </div>
      )}

      {grouped ? (
        <ChargeGroupedView
          companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy={p.groupBy}
          filters={{
            userType: p.userType === 'fl' ? 'ФЛ' : p.userType === 'ul' ? 'ЮЛ' : null,
            region: p.region === ALL ? null : p.region,
            connector: p.connector === ALL ? null : p.connector,
            result: p.result === ALL ? null : p.result,
            paid: p.paid === 'all' ? null : p.paid,
            search: search || null,
          }} />
      ) : isLoading ? <Loading /> : total === 0 ? (
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
                  {th('revenue', 'Выручка, ₽', true)}
                  {th('result', 'Исход')}
                  <TableHead className="text-center">Оплата</TableHead>
                  {/* Деньги эквайринга рядом со строкой: сколько банк реально
                      списал и сошлось ли это с начисленным по сессии. */}
                  <TableHead className="text-right whitespace-nowrap">Списано</TableHead>
                  <TableHead className="text-right whitespace-nowrap">Разрыв</TableHead>
                  <TableHead className="text-center">Чек</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.session_ext_id}>
                    <TableCell className="whitespace-nowrap font-mono text-muted-foreground">{fmtDT(r.started_at)}</TableCell>
                    {/* Канон подписи станции: «Имя (код)» — имена не уникальны и меняются, код стабилен */}
                    <TableCell className="max-w-[220px] truncate font-medium" title={`${r.station_name ?? ''} (${r.station_code ?? '—'})`}>
                      {r.station_name || 'Станция'}{r.station_code ? ` (${r.station_code})` : ''}
                    </TableCell>
                    <TableCell className="max-w-[160px] truncate">{r.region || '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.connector_type || '—'}</TableCell>
                    <TableCell>{r.user_type || '—'}</TableCell>
                    <TableCell className="max-w-[200px] truncate" title={r.client_name ?? ''}>{r.client_name || '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{chargeTypeLabel(r.charge_type)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{nf1.format(r.energy_kwh)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{nf0.format(r.duration_min)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {r.client_tariff != null
                        ? <span title={`договорной тариф ЮЛ (розничный ${fmtMoney(r.tariff)})`}>{fmtMoney(r.client_tariff)}<span className="text-muted-foreground">*</span></span>
                        : fmtMoney(r.tariff)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{fmtMoney(r.revenue)}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.result || '—'}</TableCell>
                    <TableCell className="text-center">
                      {r.paid_at ? <span className="text-emerald-600 dark:text-emerald-400" title={fmtDT(r.paid_at)} aria-label="Оплачено">✓</span> : <span className="text-muted-foreground/70" aria-label="Не оплачено">✗</span>}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums"
                      title={(r.payments ?? 0) > 1 ? `${r.payments} списаний` : undefined}>
                      {r.paid_amount != null ? fmtMoney(r.paid_amount) : '—'}
                    </TableCell>
                    <TableCell className={`text-right font-mono tabular-nums ${
                      Math.abs(r.pay_gap ?? 0) > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground/70'}`}>
                      {r.pay_gap != null && Math.abs(r.pay_gap) > 0.01 ? fmtMoney(r.pay_gap) : '—'}
                    </TableCell>
                    <TableCell className="text-center">
                      {r.receipt ? <span className="text-emerald-600 dark:text-emerald-400" aria-label="Чек есть">✓</span>
                        : <span className="text-muted-foreground/70" aria-label="Чека нет">—</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    Итого по фильтру: <span className="font-medium text-foreground">{nf0.format(total)}</span> транзакций
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{nf1.format(totals.energy_kwh)}</TableCell>
                  <TableCell />
                  <TableCell />
                  <TableCell className="text-right font-mono tabular-nums">{fmtMoney(totals.revenue)}</TableCell>
                  <TableCell colSpan={5} />
                </TableRow>
              </TableFooter>
            </Table>
          </DualScrollX>
          <PaginationWrapper total={total} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
        </>
      )}
    </div>
  )
}
