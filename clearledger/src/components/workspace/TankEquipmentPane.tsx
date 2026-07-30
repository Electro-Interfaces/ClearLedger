/**
 * Карточка резервуара как оборудования: паспорт, что в нём сейчас, исправность
 * уровнемера и как всё это менялось.
 *
 * Отдельно от разбора расхождения (`TankCardDialog`): там вопрос «куда девалось
 * топливо», здесь — «что это за резервуар и можно ли верить его прибору». Пока
 * прибор врёт, разбирать литры бессмысленно, поэтому эта карточка идёт первой.
 *
 * История берётся книгой резервуара (`tank-ledger` с фильтром по резервуару): в её
 * строках уже есть уровень, температура, плотность, вода и оба остатка.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts'
import { AlertTriangle, Check, Gauge, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DetailPane } from './DetailPane'
import { cn } from '@/lib/utils'
import { getTankLedger, type TankSpecRow } from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)
const dmy = (s: string | null | undefined) => (s ? new Date(s).toLocaleDateString('ru-RU') : '—')

const SOURCE_LABEL: Record<string, string> = {
  sts: 'из STS (volume_max)', manual: 'введена вручную', estimate: 'оценка по книге',
}

function Row({ label, value, tone, hint }: {
  label: string; value: React.ReactNode; tone?: string; hint?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/50 py-1.5 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right">
        <span className={cn('text-xs font-medium tabular-nums', tone)}>{value}</span>
        {hint && <span className="ml-2 text-[11px] font-normal text-muted-foreground">{hint}</span>}
      </span>
    </div>
  )
}

function Block({ title, badge, children }: {
  title: string; badge?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <h4 className="text-xs font-semibold">{title}</h4>
        {badge}
      </div>
      <div className="px-3 py-1.5">{children}</div>
    </section>
  )
}

export function TankEquipmentPane({ row, companyId, dateFrom, dateTo, onClose, onOpenVariance }: {
  row: TankSpecRow | null
  companyId: string
  dateFrom: string
  dateTo: string
  onClose: () => void
  /** Перейти к разбору расхождения по этому резервуару. */
  onOpenVariance?: (r: TankSpecRow) => void
}) {
  const q = useQuery({
    queryKey: ['tank-ledger-one', companyId, dateFrom, dateTo, row?.station_code, row?.tank_number],
    queryFn: () => getTankLedger({
      companyId, dateFrom, dateTo,
      stationCodes: row ? [row.station_code] : [],
      tankNumber: row?.tank_number,
    }),
    enabled: !!row,
    staleTime: 60_000,
  })

  const rows = useMemo(() => (q.data?.rows ?? []).filter(
    (r) => r.station_code === row?.station_code && r.tank_number === row?.tank_number),
    [q.data, row])
  const tank = useMemo(() => (q.data?.tanks ?? []).find(
    (t) => t.station_code === row?.station_code && t.tank_number === row?.tank_number) ?? null,
    [q.data, row])

  /** Наполнение и уровень по сменам — видно ритм завозов и провалы. */
  const chart = useMemo(() => rows
    .filter((r) => r.fact_end != null || r.book_end != null)
    .map((r) => ({
      x: r.opened_at ? r.opened_at.slice(0, 10) : String(r.shift_number),
      Замер: r.fact_end != null ? Math.round(r.fact_end) : null,
      Книга: Math.round(r.book_end),
      Уровень: r.level_end != null ? Math.round(r.level_end) : null,
    })), [rows])

  const cond = useMemo(() => {
    const pick = (f: (r: typeof rows[number]) => number | null | undefined) =>
      rows.map(f).filter((v): v is number => v != null)
    const t = pick((r) => r.temp_end)
    const w = pick((r) => r.water_volume)
    const d = pick((r) => r.density_end)
    return {
      tMin: t.length ? Math.min(...t) : null, tMax: t.length ? Math.max(...t) : null,
      wMax: w.length ? Math.max(...w) : null, wLast: w.length ? w[w.length - 1] : null,
      dMin: d.length ? Math.min(...d) : null, dMax: d.length ? Math.max(...d) : null,
    }
  }, [rows])

  const receipts = useMemo(() => {
    const withDelivery = rows.filter((r) => r.receipts > 1)
    return {
      count: withDelivery.length,
      volume: withDelivery.reduce((s, r) => s + r.receipts, 0),
      docs: rows.flatMap((r) => r.receipts_docs ?? []).length,
      last: withDelivery.length ? withDelivery[withDelivery.length - 1] : null,
    }
  }, [rows])

  if (!row) return <DetailPane open={false} title="" onClose={onClose}><div /></DetailPane>

  const st = row.state
  const now = st?.fact_volume ?? st?.book_end ?? null
  const fillPct = row.usable_liters && now != null
    ? Math.round((now / row.usable_liters) * 100) : null
  const broken = row.at_limit > 0 || row.fact_max > row.fact_limit
  const measuredPct = row.records > 0 ? Math.round((row.measured / row.records) * 100) : 0

  return (
    <DetailPane
      open
      onClose={onClose}
      title={`${row.station_name} · резервуар №${row.tank_number} · ${row.fuel_name}`}
      subtitle={st?.shift_date
        ? `состояние на смену №${st.shift_number} от ${dmy(st.shift_date)} · история за ${dmy(dateFrom)} — ${dmy(dateTo)}`
        : `история за ${dmy(dateFrom)} — ${dmy(dateTo)}`}
      badges={
        <>
          <Badge variant="outline" className={broken
            ? 'border-red-500/50 text-red-400' : 'border-emerald-500/40 text-emerald-500'}>
            {broken ? 'уровнемер врёт' : 'прибор в порядке'}
          </Badge>
          {row.source && (
            <span className="text-[11px] text-muted-foreground">
              вместимость: {SOURCE_LABEL[row.source] ?? row.source}
            </span>
          )}
        </>
      }
    >
      {/* Что в резервуаре сейчас. */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-4">
        {[
          ['Остаток', L(now), fillPct != null ? `${fillPct}% ёмкости` : 'по последней смене'],
          ['Свободно', row.usable_liters && now != null
            ? L(Math.max(0, row.usable_liters - now)) : '—', 'до полной ёмкости'],
          ['Уровень', st?.level_mm != null ? `${nf0.format(st.level_mm)} мм` : '—', 'по уровнемеру'],
          ['Масса', st?.mass_kg != null ? `${nf0.format(st.mass_kg)} кг` : '—', 'на конец смены'],
        ].map(([label, value, hint]) => (
          <div key={label} className="bg-card px-3 py-2.5">
            <div className="text-[11px] text-muted-foreground">{label}</div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Паспорт резервуара">
          <Row label="Рабочая вместимость" value={L(row.usable_liters)} />
          <Row label="Номинал по паспорту" value={L(row.nominal_liters)} />
          <Row label="Мёртвый остаток" value={L(row.dead_liters)} />
          <Row label="Источник вместимости"
               value={row.source ? (SOURCE_LABEL[row.source] ?? row.source) : 'нет паспорта'} />
          <Row label="Синхронизирован" value={row.synced_at ? dmy(row.synced_at) : '—'} />
          {row.note && (
            <div className="border-t border-border/50 py-1.5 text-[11px] text-muted-foreground">{row.note}</div>
          )}
        </Block>

        <Block
          title="Уровнемер"
          badge={broken
            ? <span className="flex items-center gap-1 text-[11px] text-red-500"><AlertTriangle className="h-3 w-3" />требует поверки</span>
            : <span className="flex items-center gap-1 text-[11px] text-emerald-500"><Check className="h-3 w-3" />показания в норме</span>}
        >
          <Row label="Смен в истории" value={nf0.format(row.records)} />
          <Row label="Из них с показанием" value={`${nf0.format(row.measured)}`} hint={`${measuredPct}%`}
               tone={measuredPct < 90 ? 'text-amber-500' : undefined} />
          <Row label="Отдал предел шкалы" value={row.at_limit > 0 ? `${nf0.format(row.at_limit)} раз` : 'нет'}
               tone={row.at_limit > 0 ? 'text-red-500' : undefined} />
          <Row label="Наибольшее показание" value={L(row.fact_max)}
               tone={row.fact_max > row.fact_limit ? 'text-red-500' : undefined} />
          <Row label="Граница достоверности" value={L(row.fact_limit)}
               hint="выше — в расчёт не берём" />
          <Row label="Максимум по книге" value={L(row.book_max)} />
          {broken && (
            <div className="border-t border-border/50 py-1.5 text-[11px] text-red-500">
              {row.at_limit > 0
                ? 'Прибор в части смен отдаёт вместо измерения свою верхнюю границу. Эти смены выпадают из контроля баланса и из инвентаризации — резервуар надо мерить вручную, прибор поверять.'
                : 'Прибор показывал больше, чем входит в резервуар. Показания отбракованы, требуется поверка.'}
            </div>
          )}
        </Block>
      </div>

      {/* Наполнение по сменам: ритм завозов, просадки, провалы данных. */}
      {chart.length > 2 && (
        <section>
          <h4 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
            Наполнение по сменам
          </h4>
          <div className="h-44 rounded-lg border p-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="tankFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
                <XAxis dataKey="x" tick={{ fontSize: 10 }} minTickGap={24}
                       stroke="currentColor" className="text-muted-foreground"
                       tickFormatter={(v: string) => (v.length === 10
                         ? new Date(v).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) : v)} />
                <YAxis tick={{ fontSize: 10 }} width={52} stroke="currentColor" className="text-muted-foreground" />
                <RTooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                  formatter={(v, n) => [n === 'Уровень' ? `${nf0.format(Number(v ?? 0))} мм` : `${nf0.format(Number(v ?? 0))} л`, n]}
                  labelFormatter={(l) => (String(l).length === 10 ? new Date(String(l)).toLocaleDateString('ru-RU') : String(l))}
                />
                <Area type="monotone" dataKey="Замер" stroke="hsl(var(--primary))" strokeWidth={1.5}
                      fill="url(#tankFill)" connectNulls />
                <Line type="monotone" dataKey="Книга" stroke="#f59e0b" strokeWidth={1} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {row.usable_liters && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Полная ёмкость — {L(row.usable_liters)}. Провалы линии замера — смены, где прибор
              не дал показание или отдал невозможное.
            </p>
          )}
        </section>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Условия за период">
          <Row label="Температура"
               value={cond.tMin != null ? `${nf1.format(cond.tMin)} … ${nf1.format(cond.tMax as number)} °C` : '—'} />
          <Row label="Плотность"
               value={cond.dMin != null ? `${cond.dMin} … ${cond.dMax}` : '—'} />
          <Row label="Подтоварная вода"
               value={cond.wLast != null ? `${nf1.format(cond.wLast)} л` : 'нет'}
               hint={cond.wMax ? `максимум ${nf1.format(cond.wMax)} л` : undefined}
               tone={(cond.wMax ?? 0) > 20 ? 'text-amber-500' : undefined} />
          <div className="border-t border-border/50 py-1.5 text-[11px] text-muted-foreground">
            Вода занимает объём и попадает в замер как топливо. Разброс температуры в 10 °C —
            около 1% объёма.
          </div>
        </Block>

        <Block title="Приёмка в резервуар">
          <Row label="Смен со сливом" value={nf0.format(receipts.count)} />
          <Row label="Принято за период" value={L(receipts.volume)} />
          <Row label="Накладных привязано" value={nf0.format(receipts.docs)}
               tone={receipts.count > 0 && receipts.docs === 0 ? 'text-amber-500' : undefined}
               hint={receipts.count > 0 && receipts.docs === 0 ? 'приход без ТТН' : undefined} />
          <Row label="Последний слив"
               value={receipts.last ? `${dmy(receipts.last.opened_at)} · ${L(receipts.last.receipts)}` : '—'} />
        </Block>
      </div>

      {/* Мостик в разбор расхождения: это соседний вопрос, но по тому же резервуару. */}
      {tank && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/70 bg-card/60 px-3 py-2.5">
          <div className="text-xs">
            <span className="text-muted-foreground">Книга − факт за период: </span>
            <span className={cn('font-medium tabular-nums',
              (tank.fact_gap ?? 0) > 50 ? 'text-red-500'
                : (tank.fact_gap ?? 0) < -50 ? 'text-amber-500' : 'text-muted-foreground')}>
              {tank.fact_gap == null ? '—'
                : Math.abs(tank.fact_gap) < 0.5 ? 'сходится'
                : `${nf0.format(Math.abs(tank.fact_gap))} л ${tank.fact_gap > 0 ? 'недостача' : 'излишек'}`}
            </span>
            <span className="ml-2 text-muted-foreground">
              · замечаний: арифметика {tank.arithmetic_breaks} · стык {tank.continuity_breaks} · замер {tank.fact_breaks}
            </span>
          </div>
          {onOpenVariance && (
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => onOpenVariance(row)}>
              <Gauge className="mr-1.5 h-3.5 w-3.5" />Разбор расхождения
            </Button>
          )}
        </div>
      )}

      {q.isLoading && (
        <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Загружаю историю резервуара…
        </div>
      )}
    </DetailPane>
  )
}
