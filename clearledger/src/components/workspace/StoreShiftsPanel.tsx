/**
 * «Смены» — смена как составной документ (архитектура МАГа): организующая
 * единица, на которую роллапятся продажи (сопутка/общепит), возвраты, приходы,
 * инвентаризации, списания того же дня. Приходы/инвентаризации в ЦБ не несут
 * GUID смены → связка по (станция, дата).
 * Данные: /api/store/shifts (GoodsDashboardService.shifts_composite).
 *
 * Реестр за квартал — это сотни строк, и глазами в нём ищут не «все смены», а
 * конкретную: смену с недостачей, день с приходом, станцию за дату. Поэтому
 * отбор и сортировка живут прямо над таблицей, а сводка считается по ВЫБОРКЕ,
 * а не по периоду: цифра, не совпадающая с тем, что видно в строках, врёт.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X, ArrowUp, ArrowDown } from 'lucide-react'
import { getStoreShifts, type ShiftComposite } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { ExportButton } from './analytics/ExportButton'
import { ShiftDetailModal } from './ShiftDetailModal'
import { rowDrill } from './rowDrill'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

/** Признаки, по которым смену ищут глазами: «где было движение товара». */
const ПРИЗНАКИ = [
  { key: 'returns', label: 'возвраты', has: (s: ShiftComposite) => s.returns > 0 },
  { key: 'receipts', label: 'приходы', has: (s: ShiftComposite) => s.receipts_count > 0 },
  { key: 'inventory', label: 'инвентаризации', has: (s: ShiftComposite) => s.inventory_count > 0 },
  { key: 'writeoff', label: 'списания', has: (s: ShiftComposite) => s.writeoff_count > 0 },
  { key: 'transfer', label: 'перемещения', has: (s: ShiftComposite) => s.transfer_count > 0 },
  { key: 'reval', label: 'переоценки', has: (s: ShiftComposite) => s.reval_count > 0 },
] as const

type Признак = typeof ПРИЗНАКИ[number]['key']
type Поле = 'date' | 'revenue' | 'positions' | 'receipts_amount' | 'writeoff_amount'

const ЧИСЛОВЫЕ: Record<Поле, (s: ShiftComposite) => number | string> = {
  date: (s) => `${s.date} ${s.number ?? ''}`,
  revenue: (s) => s.revenue,
  positions: (s) => s.positions,
  receipts_amount: (s) => s.receipts_amount,
  writeoff_amount: (s) => s.writeoff_amount,
}

// Классы выравнивания перечислены целиком: Tailwind собирает по литералам в
// исходнике, и `text-${align}` в сборке просто исчезает.
const ALIGN = { left: 'text-left', right: 'text-right', center: 'text-center' } as const

/** Заголовок-сортировка: направление видно стрелкой, а не только цветом. */
function Th({ поле, текст, align = 'right', sort, setSort }: {
  поле?: Поле; текст: string; align?: keyof typeof ALIGN
  sort: { поле: Поле; вниз: boolean }; setSort: (s: { поле: Поле; вниз: boolean }) => void
}) {
  const активно = поле && sort.поле === поле
  const cls = `px-3 py-2 font-medium whitespace-nowrap ${ALIGN[align]}`
  if (!поле) return <th className={cls}>{текст}</th>
  return (
    <th className={cls} aria-sort={активно ? (sort.вниз ? 'descending' : 'ascending') : 'none'}>
      <button type="button"
        onClick={() => setSort({ поле, вниз: активно ? !sort.вниз : true })}
        className={`inline-flex items-center gap-1 hover:text-foreground ${активно ? 'text-foreground' : ''}`}
        title={`Сортировать по «${текст}»`}>
        {текст}
        {активно && (sort.вниз ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
      </button>
    </th>
  )
}

/** Доля сопутки и общепита в выручке — одной полосой вместо двух чисел. */
function ДоляПолоса({ soputka, obshepit }: { soputka: number; obshepit: number }) {
  const всего = soputka + obshepit
  if (всего <= 0) return null
  const доля = Math.round((soputka / всего) * 100)
  return (
    <div className="mt-2">
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="bg-primary/80" style={{ width: `${доля}%` }} />
        <div className="bg-amber-400/70" style={{ width: `${100 - доля}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>сопутка {доля}% · {money(soputka)}</span>
        <span>общепит {100 - доля}% · {money(obshepit)}</span>
      </div>
    </div>
  )
}

function Метрика({ label, value, hint, cls }: {
  label: string; value: string; hint?: string; cls?: string
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 truncate text-lg font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
      {hint && <div className="truncate text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export function StoreShiftsPanel({ companyId, dateFrom, dateTo, stations }: { companyId: string; dateFrom: string; dateTo: string; stations?: string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [запрос, задатьЗапрос] = useState('')
  const [азс, задатьАЗС] = useState<string | null>(null)
  const [признаки, задатьПризнаки] = useState<Признак[]>([])
  const [sort, setSort] = useState<{ поле: Поле; вниз: boolean }>({ поле: 'date', вниз: true })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-shifts', companyId, dateFrom, dateTo, stations],
    queryFn: () => getStoreShifts(dateFrom, dateTo, stations),
  })

  const все = useMemo(() => data?.shifts ?? [], [data])
  const азсы = useMemo(
    () => Array.from(new Set(все.map((s) => s.station))).sort(),
    [все])

  const строки = useMemo(() => {
    const q = запрос.trim().toLowerCase()
    const отобранные = все.filter((s) => {
      if (азс && s.station !== азс) return false
      for (const k of признаки) {
        const п = ПРИЗНАКИ.find((x) => x.key === k)
        if (п && !п.has(s)) return false
      }
      if (!q) return true
      return `${s.date} ${s.station} ${s.number ?? ''} ${s.operator ?? ''} ${s.register ?? ''} ${s.internal_no ?? ''}`
        .toLowerCase().includes(q)
    })
    const знач = ЧИСЛОВЫЕ[sort.поле]
    return [...отобранные].sort((a, b) => {
      const x = знач(a), y = знач(b)
      const c = typeof x === 'number' && typeof y === 'number'
        ? x - y : String(x).localeCompare(String(y), 'ru')
      return sort.вниз ? -c : c
    })
  }, [все, азс, признаки, запрос, sort])

  // Сводка считается по выборке: смотреть на итог периода, отфильтровав до
  // одной станции, — верный способ увести человека не туда.
  const итог = useMemo(() => строки.reduce((a, s) => ({
    revenue: a.revenue + s.revenue,
    soputka: a.soputka + s.soputka,
    obshepit: a.obshepit + s.obshepit,
    returns: a.returns + s.returns,
    positions: a.positions + s.positions,
    receipts_amount: a.receipts_amount + s.receipts_amount,
    receipts_count: a.receipts_count + s.receipts_count,
    inventory_count: a.inventory_count + s.inventory_count,
    inventory_net: a.inventory_net + s.inventory_net,
    writeoff_amount: a.writeoff_amount + s.writeoff_amount,
    writeoff_count: a.writeoff_count + s.writeoff_count,
    transfer_count: a.transfer_count + s.transfer_count,
    reval_count: a.reval_count + s.reval_count,
  }), {
    revenue: 0, soputka: 0, obshepit: 0, returns: 0, positions: 0,
    receipts_amount: 0, receipts_count: 0, inventory_count: 0, inventory_net: 0,
    writeoff_amount: 0, writeoff_count: 0, transfer_count: 0, reval_count: 0,
  }), [строки])

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка смен…</div>
  if (error) return (
    <div className="p-6 text-sm text-red-400/90">
      Не удалось загрузить смены.{' '}
      <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
    </div>
  )
  if (!data) return null

  const отбор = запрос.trim() !== '' || азс !== null || признаки.length > 0
  const сбросить = () => { задатьЗапрос(''); задатьАЗС(null); задатьПризнаки([]) }
  const переключить = (k: Признак) => задатьПризнаки(
    признаки.includes(k) ? признаки.filter((x) => x !== k) : [...признаки, k])

  return (
    <div ref={ref} className="space-y-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Смены</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Смена как организующая единица: продажи + возвраты + приходы + инвентаризации + списания за смену.
            Приходы/инвентаризации связаны по дате и станции (в ЦБ отдельные документы).
          </p>
        </div>
        <ExportButton title="Смены магазина" subtitle={`${data.period.from} — ${data.period.to}`} getEl={() => ref.current} />
      </div>

      {/* Отбор: поиск, станция, признаки движения. Всё клиентское — реестр
          периода уже пришёл целиком, и лишний рейс к серверу тут не нужен. */}
      <div className="space-y-2.5 rounded-lg border border-border/50 bg-card/30 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={запрос}
              onChange={(e) => задатьЗапрос(e.target.value)}
              placeholder="Дата, смена, АЗС, оператор или пост"
              aria-label="Поиск по сменам"
              className="h-8 w-full rounded-md border border-border/60 bg-background/60 pl-8 pr-8 text-xs outline-none placeholder:text-muted-foreground/70 focus:border-primary/60"
            />
            {запрос && (
              <button type="button" onClick={() => задатьЗапрос('')} aria-label="Очистить поиск"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {азсы.length > 1 && (
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-muted-foreground">АЗС</span>
              <button type="button" onClick={() => задатьАЗС(null)}
                className={`rounded-md border px-2 py-1 text-xs ${азс === null
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
                все
              </button>
              {азсы.map((st) => (
                <button key={st} type="button" onClick={() => задатьАЗС(азс === st ? null : st)}
                  className={`rounded-md border px-2 py-1 text-xs tabular-nums ${азс === st
                    ? 'border-primary/60 bg-primary/10 text-foreground'
                    : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
                  {st}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Только смены, где есть:</span>
          {ПРИЗНАКИ.map((п) => {
            const активен = признаки.includes(п.key)
            const сколько = все.filter(п.has).length
            return (
              <button key={п.key} type="button" onClick={() => переключить(п.key)}
                aria-pressed={активен} disabled={сколько === 0}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${активен
                  ? 'border-primary/60 bg-primary/15 text-foreground'
                  : сколько === 0
                    ? 'cursor-not-allowed border-border/40 text-muted-foreground/40'
                    : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
                {п.label} <span className="tabular-nums opacity-70">{сколько}</span>
              </button>
            )
          })}
          {отбор && (
            <button type="button" onClick={сбросить}
              className="ml-1 inline-flex items-center gap-1 rounded-full border border-border/60 px-2.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
              <X className="h-3 w-3" />сбросить
            </button>
          )}
        </div>
      </div>

      {/* Сводка выборки: продажи слева, движение товара справа — это разные
          вопросы, и восемь одинаковых плиток их сваливали в один ряд. */}
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Продажи
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Метрика label="Смен" value={nf(строки.length)}
                     hint={отбор ? `из ${nf(все.length)} за период` : `${data.period.from} – ${data.period.to}`} />
            <Метрика label="Выручка" value={money(итог.revenue)} />
            <Метрика label="Позиций" value={nf(итог.positions)} />
            <Метрика label="Возвраты" value={money(итог.returns)}
                     cls={итог.returns > 0 ? 'text-amber-300/90' : ''} />
          </div>
          <ДоляПолоса soputka={итог.soputka} obshepit={итог.obshepit} />
        </div>

        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Движение товара
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Метрика label="Приходы (нетто)" value={money(итог.receipts_amount)}
                     hint={`${nf(итог.receipts_count)} документов`} />
            <Метрика label="Инвентаризации" value={nf(итог.inventory_count)}
                     hint={итог.inventory_net !== 0 ? `отклонение ${fmtMoney(итог.inventory_net)}` : 'без отклонений'} />
            <Метрика label="Списания" value={money(итог.writeoff_amount)}
                     hint={`${nf(итог.writeoff_count)} документов`}
                     cls={итог.writeoff_amount > 0 ? 'text-red-400/80' : ''} />
            <Метрика label="Перемещения · переоценки"
                     value={`${nf(итог.transfer_count)} · ${nf(итог.reval_count)}`} />
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <Th поле="date" текст="Дата" align="left" sort={sort} setSort={setSort} />
              <Th текст="АЗС" align="left" sort={sort} setSort={setSort} />
              <Th текст="№ смены" align="left" sort={sort} setSort={setSort} />
              {/* Оператор — реквизит смены, а не украшение: при разборе
                  расхождения это первый вопрос. Приходит от агента станции;
                  у смен, полученных из ЦБ, его нет вовсе. */}
              <Th текст="Оператор" align="left" sort={sort} setSort={setSort} />
              <Th текст="Пост" align="left" sort={sort} setSort={setSort} />
              <Th поле="revenue" текст="Выручка" sort={sort} setSort={setSort} />
              <Th текст="Сопутка" sort={sort} setSort={setSort} />
              <Th текст="Общепит" sort={sort} setSort={setSort} />
              <Th поле="positions" текст="Позиций" sort={sort} setSort={setSort} />
              <Th текст="Возвраты" sort={sort} setSort={setSort} />
              <Th поле="receipts_amount" текст="Приходы" sort={sort} setSort={setSort} />
              <Th текст="Инв." align="center" sort={sort} setSort={setSort} />
              <Th поле="writeoff_amount" текст="Списания" sort={sort} setSort={setSort} />
              <Th текст="Перем." align="center" sort={sort} setSort={setSort} />
              <Th текст="Переоц." align="center" sort={sort} setSort={setSort} />
            </tr>
          </thead>
          <tbody>
            {строки.map((sh: ShiftComposite) => (
              <tr key={sh.shift_key}
                {...rowDrill(() => setOpenKey(sh.shift_key),
                  `Открыть смену ${sh.number ?? sh.date}`, 'border-t border-border/30')}>
                <td className="whitespace-nowrap px-3 py-1.5">{sh.date}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{sh.station}</td>
                <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{sh.number ?? '—'}</td>
                <td className="max-w-[160px] truncate px-3 py-1.5 text-muted-foreground"
                  title={sh.operator ?? 'оператор не передан источником'}>
                  {sh.operator ?? '—'}
                </td>
                <td className="max-w-[120px] truncate px-3 py-1.5 text-muted-foreground"
                  title={sh.internal_no ? `внутренний номер ${sh.internal_no}` : undefined}>
                  {sh.register ?? '—'}{sh.internal_no ? ` · ${sh.internal_no}` : ''}
                </td>
                <td className="px-3 py-1.5 text-right font-medium tabular-nums">{money(sh.revenue)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{money(sh.soputka)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{money(sh.obshepit)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{nf(sh.positions)}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${sh.returns > 0 ? 'text-amber-300/90' : 'text-muted-foreground/50'}`}>{money(sh.returns)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {sh.receipts_amount > 0
                    ? <span title={`${sh.receipts_count} документ(ов)`}>{money(sh.receipts_amount)}</span>
                    : <span className="text-muted-foreground/50">—</span>}
                </td>
                <td className="px-3 py-1.5 text-center tabular-nums">
                  {sh.inventory_count > 0 ? <span className="text-blue-300/80" title={`отклонение ${fmtMoney(sh.inventory_net)}`}>{sh.inventory_count}</span> : <span className="text-muted-foreground/50">—</span>}
                </td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${sh.writeoff_amount > 0 ? 'text-red-400/80' : 'text-muted-foreground/50'}`}>
                  {sh.writeoff_amount > 0 ? <span title={`${sh.writeoff_count} документ(ов)`}>{money(sh.writeoff_amount)}</span> : '—'}
                </td>
                <td className="px-3 py-1.5 text-center tabular-nums">
                  {sh.transfer_count > 0 ? <span title={`перемещения на ${fmtMoney(sh.transfer_amount)}`}>{sh.transfer_count}</span> : <span className="text-muted-foreground/50">—</span>}
                </td>
                <td className="px-3 py-1.5 text-center tabular-nums">
                  {sh.reval_count > 0 ? <span className="text-amber-300/80">{sh.reval_count}</span> : <span className="text-muted-foreground/50">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {строки.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            {все.length === 0
              ? 'Нет смен за период.'
              : <>Под отбор не попала ни одна смена из {nf(все.length)}.{' '}
                  <button type="button" onClick={сбросить} className="text-primary hover:underline">
                    Сбросить отбор
                  </button></>}
          </div>
        )}
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Клик по смене — детализация (строки продаж, касса, приходы/инвентаризации/списания дня).
        Приходы/инвентаризации/списания показаны за дату смены (в ЦБ — отдельные документы, GUID смены не несут).
      </p>

      {openKey && <ShiftDetailModal shiftKey={openKey} companyId={companyId} onClose={() => setOpenKey(null)} />}
    </div>
  )
}
