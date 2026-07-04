/**
 * Модалка выгрузки сводной таблицы сессий ЭЗС (из «Нормализации»).
 * Два режима:
 *   • «Готовый шаблон» — многолистовой Excel: лист сессий (опц.) + преднастроенные
 *     сводные (регион×разрез, клиент ЮЛ×месяц, надёжность, загрузка по времени);
 *   • «Своя сводная» — задать строки × столбцы × меру × период вручную.
 * Данные и файл — через exportChargePivots (backend /charge-sessions/pivot|rows).
 */
import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'
import { Download, Loader2 } from 'lucide-react'
import { exportChargePivots, PIVOT_DIM_LABEL, PIVOT_METRIC_LABEL, type PivotSpec } from '@/services/chargeExport'
import type { ChargePivotDim, ChargeMetric } from '@/services/analyticsService'

const DIMS: ChargePivotDim[] = [
  'region', 'station', 'connector', 'user_type', 'client', 'charge_type',
  'result', 'cut', 'tariff', 'month', 'week', 'day', 'quarter', 'hour', 'weekday',
]
const METRICS: ChargeMetric[] = [
  'amount', 'sessions', 'energy_kwh', 'avg_check', 'avg_energy',
  'avg_duration_min', 'success_pct', 'price_per_kwh',
]

interface Template { id: string; name: string; desc: string; sessions: boolean; pivots: PivotSpec[] }
const TEMPLATES: Template[] = [
  {
    id: 'full', name: 'Полная сводка', sessions: true,
    desc: 'Лист сессий (детально) + ключевые сводные',
    pivots: [
      { title: 'Регион × Разрез', rows: 'region', cols: 'cut', metric: 'amount' },
      { title: 'Станция × Коннектор', rows: 'station', cols: 'connector', metric: 'energy_kwh' },
      { title: 'Клиент ЮЛ × Месяц', rows: 'client', cols: 'month', metric: 'amount' },
      { title: 'Надёжность станций', rows: 'station', cols: 'result', metric: 'sessions' },
    ],
  },
  {
    id: 'clients', name: 'Корп-клиенты (ЮЛ)', sessions: false,
    desc: 'Юрлица по месяцам, разрезам и энергии',
    pivots: [
      { title: 'Клиент × Месяц (₽)', rows: 'client', cols: 'month', metric: 'amount' },
      { title: 'Клиент × Разрез', rows: 'client', cols: 'cut', metric: 'sessions' },
      { title: 'Клиент × Энергия', rows: 'client', cols: 'month', metric: 'energy_kwh' },
    ],
  },
  {
    id: 'reliability', name: 'Надёжность', sessions: false,
    desc: 'Исходы по станциям/коннекторам + тренд успеха',
    pivots: [
      { title: 'Станция × Исход', rows: 'station', cols: 'result', metric: 'sessions' },
      { title: 'Коннектор × Исход', rows: 'connector', cols: 'result', metric: 'sessions' },
      { title: 'Успех% станций × месяц', rows: 'station', cols: 'month', metric: 'success_pct' },
    ],
  },
  {
    id: 'time', name: 'По месяцам', sessions: false,
    desc: 'Помесячная динамика: разрезы, коннекторы, клиенты',
    pivots: [
      { title: 'Месяц × Разрез (₽)', rows: 'month', cols: 'cut', metric: 'amount' },
      { title: 'Месяц × Коннектор (энергия)', rows: 'month', cols: 'connector', metric: 'energy_kwh' },
      { title: 'Месяц × Клиент ЮЛ (₽)', rows: 'month', cols: 'client', metric: 'amount' },
    ],
  },
]

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

export function ChargePivotExportDialog({ open, onOpenChange, companyId, defaultFrom, defaultTo }: {
  open: boolean; onOpenChange: (v: boolean) => void
  companyId: string; defaultFrom: string; defaultTo: string
}) {
  const [mode, setMode] = useState<'template' | 'custom'>('template')
  const [tpl, setTpl] = useState('full')
  const [rows, setRows] = useState<ChargePivotDim>('region')
  const [cols, setCols] = useState<string>('cut')   // '__none__' → одномерная
  const [metric, setMetric] = useState<ChargeMetric>('amount')
  const [from, setFrom] = useState(defaultFrom)
  const [to, setTo] = useState(defaultTo)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  async function run() {
    if (from > to) { toast.error('Период задан неверно: «С» позже «По»'); return }
    setBusy(true)
    try {
      const base = { companyId, dateFrom: from, dateTo: to, onProgress: setStatus }
      const t = TEMPLATES.find((x) => x.id === tpl)!
      const c = cols === '__none__' ? undefined : (cols as ChargePivotDim)
      const pivots: PivotSpec[] = mode === 'template' ? t.pivots : [{ title: 'Сводная', rows, cols: c, metric }]
      const title = mode === 'template'
        ? `Сессии ЭЗС · ${t.name}`
        : `Сводная · ${PIVOT_DIM_LABEL[rows]}${c ? ` × ${PIVOT_DIM_LABEL[c]}` : ''}`
      await exportChargePivots({ ...base, title, pivots })
      toast.success('Выгружено в Excel', { description: 'Лист «Данные» — таблица: выделите её → Вставка → Сводная таблица.' })
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка выгрузки')
    } finally {
      setBusy(false); setStatus('')
    }
  }

  const seg = (active: boolean) =>
    `px-3 py-1.5 text-xs rounded-[5px] transition-colors ${active ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Выгрузка сводной таблицы</DialogTitle>
        </DialogHeader>
        <p className="-mt-1 text-xs text-muted-foreground">
          Готовый шаблон (лист-таблица «Данные» + преднастроенные сводные-матрицы) или своя сводная. Формат — Excel (.xlsx).
        </p>

        {/* режим */}
        <div className="inline-flex w-fit gap-0.5 rounded-md border border-border p-0.5">
          <button type="button" disabled={busy} onClick={() => setMode('template')} className={seg(mode === 'template')}>Готовый шаблон</button>
          <button type="button" disabled={busy} onClick={() => setMode('custom')} className={seg(mode === 'custom')}>Своя сводная</button>
        </div>

        {mode === 'template' ? (
          <div className="max-h-[46vh] space-y-2 overflow-y-auto pr-1">
            {TEMPLATES.map((t) => (
              <button key={t.id} type="button" onClick={() => setTpl(t.id)}
                className={`block w-full rounded-lg border p-3 text-left transition-colors ${tpl === t.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent/40'}`}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{t.name}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground/70">{t.pivots.length} сводных</span>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{t.desc}</div>
                <div className="mt-1 text-[11px] text-muted-foreground/70">{t.pivots.map((p) => p.title).join(' · ')}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Строки">
              <Select value={rows} onValueChange={(v) => setRows(v as ChargePivotDim)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{DIMS.map((d) => <SelectItem key={d} value={d} className="text-xs">{PIVOT_DIM_LABEL[d]}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Столбцы">
              <Select value={cols} onValueChange={setCols}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__" className="text-xs">— нет (одномерная) —</SelectItem>
                  {DIMS.map((d) => <SelectItem key={d} value={d} className="text-xs">{PIVOT_DIM_LABEL[d]}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Мера">
              <Select value={metric} onValueChange={(v) => setMetric(v as ChargeMetric)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{METRICS.map((m) => <SelectItem key={m} value={m} className="text-xs">{PIVOT_METRIC_LABEL[m]}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
          </div>
        )}

        {/* период */}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Период с"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 text-xs" /></Field>
          <Field label="по"><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 text-xs" /></Field>
        </div>

        <p className="rounded-md border border-border/60 bg-muted/20 p-2 text-[11px] text-muted-foreground">
          В файле: лист <b className="text-foreground">«Данные»</b> — Excel-таблица для своей сводной
          (выделить → Вставка → Сводная таблица, откроется область полей) + листы с преднастроенными сводными-матрицами.
        </p>

        <div className="mt-1 flex items-center gap-2">
          {busy && <span className="mr-auto text-xs text-muted-foreground">{status}</span>}
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} disabled={busy} className={busy ? '' : 'ml-auto'}>Отмена</Button>
          <Button size="sm" onClick={run} disabled={busy}>
            {busy ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Download className="mr-2 size-4" />}
            Выгрузить Excel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
