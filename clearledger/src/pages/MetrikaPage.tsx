/**
 * Коннектор «Яндекс.Метрика» — подключение (счётчик + OAuth-токен) и дашборд
 * веб-аналитики (визиты/посетители/просмотры/отказы, динамика, источники).
 * Токен вводится здесь, хранится шифрованным на бэке; фронт его не получает.
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { BarChart2, Loader2, Link2, CheckCircle2, AlertTriangle, ExternalLink, Trash2, RefreshCw } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'
import {
  getMetrikaStatus, saveMetrikaConnection, deleteMetrikaConnection, testMetrikaConnection,
  getMetrikaSummary, getMetrikaTimeseries, getMetrikaSources, type MetrikaStatus,
} from '@/services/metrikaService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const pct = (v: number) => nf1.format(v) + '%'
const dur = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

const PERIODS = [{ k: '7daysAgo', label: '7 дней' }, { k: '30daysAgo', label: '30 дней' }, { k: '90daysAgo', label: '90 дней' }]

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="py-0"><CardContent className="p-3">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </CardContent></Card>
  )
}

// ── Форма подключения ──
function ConnectionForm({ companyId, current, onDone }: { companyId: string; current?: MetrikaStatus; onDone: () => void }) {
  const [counter, setCounter] = useState(current?.counter_id ?? '')
  const [token, setToken] = useState('')
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => saveMetrikaConnection(companyId, counter.trim(), token.trim()),
    onSuccess: (st) => {
      qc.invalidateQueries({ queryKey: ['metrika'] })
      if (st.status === 'ok') { toast.success(`Подключено: ${st.counter_name ?? 'счётчик ' + st.counter_id}`); onDone() }
      else toast.error(st.last_error ?? 'Не удалось проверить подключение')
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка сохранения'),
  })
  return (
    <Card><CardContent className="p-4 space-y-3 max-w-xl">
      <div className="text-sm font-medium">Подключение к Яндекс.Метрике</div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Номер счётчика</label>
        <input value={counter} onChange={(e) => setCounter(e.target.value.replace(/\D/g, ''))} placeholder="напр. 44147844"
          inputMode="numeric" className="h-9 w-full rounded-md border bg-background px-3 text-sm" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">OAuth-токен (право metrika:read)</label>
        <input value={token} onChange={(e) => setToken(e.target.value)} placeholder="вставьте токен" type="password"
          className="h-9 w-full rounded-md border bg-background px-3 text-sm font-mono" />
        <p className="text-[11px] text-muted-foreground">
          Токен хранится шифрованным на сервере и не показывается повторно.{' '}
          <a href="https://oauth.yandex.ru/authorize?response_type=token&client_id=" target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline">получить токен <ExternalLink className="h-3 w-3" /></a>
          {' '}(нужен client_id вашего приложения Метрики).
        </p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" disabled={!counter || token.length < 10 || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}Подключить
        </Button>
        {current?.configured && <Button size="sm" variant="ghost" onClick={onDone}>Отмена</Button>}
      </div>
    </CardContent></Card>
  )
}

// ── Дашборд метрик ──
function MetrikaDashboard({ companyId, status, onEdit }: { companyId: string; status: MetrikaStatus; onEdit: () => void }) {
  const [period, setPeriod] = useState('30daysAgo')
  const qc = useQueryClient()
  const sum = useQuery({ queryKey: ['metrika', 'summary', companyId, period], queryFn: () => getMetrikaSummary(companyId, period) })
  const ts = useQuery({ queryKey: ['metrika', 'ts', companyId, period], queryFn: () => getMetrikaTimeseries(companyId, period) })
  const src = useQuery({ queryKey: ['metrika', 'src', companyId, period], queryFn: () => getMetrikaSources(companyId, period) })
  const del = useMutation({
    mutationFn: () => deleteMetrikaConnection(companyId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['metrika'] }); toast.success('Подключение удалено') },
  })
  const t = sum.data?.totals
  const tsRows = useMemo(() => (ts.data?.rows ?? []).map((r) => ({ d: r.date.slice(5), Визиты: r.visits, Просмотры: r.pageviews })), [ts.data])
  const maxSrc = Math.max(1, ...(src.data?.rows ?? []).map((r) => r.visits))
  const err = (sum.error || ts.error) as Error | undefined

  return (
    <div className="space-y-4">
      {/* Статус подключения */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex items-center gap-2 text-sm">
          <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${status.status === 'ok' ? 'border-emerald-400/40 text-emerald-300/90' : 'border-amber-400/40 text-amber-300/90'}`}>
            {status.status === 'ok' ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
            {status.counter_name ?? `Счётчик ${status.counter_id}`}
          </span>
          {status.last_error && <span className="text-xs text-amber-300/80">{status.last_error}</span>}
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border p-0.5">
            {PERIODS.map((p) => (
              <button key={p.k} onClick={() => setPeriod(p.k)}
                className={`rounded px-2.5 py-1 text-xs ${period === p.k ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'}`}>{p.label}</button>
            ))}
          </div>
          <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" onClick={onEdit}><RefreshCw className="h-3.5 w-3.5" />Изменить</Button>
          <Button size="sm" variant="ghost" className="h-8 gap-1.5 text-xs text-muted-foreground" disabled={del.isPending} onClick={() => del.mutate()}><Trash2 className="h-3.5 w-3.5" />Отключить</Button>
        </div>
      </div>

      {err ? <Card><CardContent className="p-4 text-sm text-amber-300/90">Метрика: {err.message}</CardContent></Card> : (
        <>
          {/* KPI */}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Визиты" value={sum.isLoading ? '…' : nf0.format(t?.visits ?? 0)} />
            <Kpi label="Посетители" value={sum.isLoading ? '…' : nf0.format(t?.users ?? 0)} sub={`новых ${pct(t?.new_pct ?? 0)}`} />
            <Kpi label="Просмотры" value={sum.isLoading ? '…' : nf0.format(t?.pageviews ?? 0)} />
            <Kpi label="Отказы" value={sum.isLoading ? '…' : pct(t?.bounce_rate ?? 0)} />
            <Kpi label="Время на сайте" value={sum.isLoading ? '…' : dur(t?.avg_duration_sec ?? 0)} sub="мин:сек" />
            <Kpi label="Глубина" value={sum.isLoading ? '…' : nf1.format(t?.page_depth ?? 0)} sub="стр./визит" />
          </div>
          {sum.data?.sampled && <div className="text-[11px] text-amber-300/80">⚠ данные семплированы ({pct((sum.data.sample_share ?? 1) * 100)})</div>}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Динамика: визиты и просмотры</div>
              <Card><CardContent className="p-3">
                {ts.isLoading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> : (
                  <div data-chart><ResponsiveContainer width="100%" height={220}>
                    <BarChart data={tsRows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                      <XAxis dataKey="d" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                      <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} width={40} />
                      <Tooltip {...rechartsTooltipTheme} cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} />
                      <Bar dataKey="Визиты" fill="hsl(var(--chart-1))" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                      <Bar dataKey="Просмотры" fill="hsl(var(--chart-2))" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer></div>
                )}
              </CardContent></Card>
            </div>
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Источники трафика</div>
              <Card><CardContent className="space-y-2 p-3">
                {src.isLoading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
                  : (src.data?.rows ?? []).length === 0 ? <div className="py-6 text-center text-sm text-muted-foreground">Нет данных</div>
                    : (src.data?.rows ?? []).map((r) => (
                      <div key={r.source} className="space-y-0.5">
                        <div className="flex justify-between gap-2 text-xs">
                          <span className="truncate">{r.source}</span>
                          <span className="whitespace-nowrap tabular-nums text-muted-foreground">{nf0.format(r.visits)} виз · отказы {pct(r.bounce_rate)}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(2, r.visits / maxSrc * 100)}%` }} /></div>
                      </div>
                    ))}
              </CardContent></Card>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export function MetrikaPage() {
  const { companyId } = useCompany()
  const [editing, setEditing] = useState(false)
  const testM = useMutation({
    mutationFn: () => testMetrikaConnection(companyId),
    onSuccess: (r) => (r.ok ? toast.success(`Связь есть: ${r.counter_name ?? 'ок'}`) : toast.error(r.error ?? 'Нет связи')),
  })
  const status = useQuery({ queryKey: ['metrika', 'status', companyId], queryFn: () => getMetrikaStatus(companyId) })

  return (
    <div className="px-4 py-4 sm:px-6 sm:py-6 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="flex items-center gap-2">
          <BarChart2 className="h-6 w-6 text-primary shrink-0" />
          <div>
            <h1 className="text-xl font-semibold">Яндекс.Метрика</h1>
            <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
              Веб-аналитика сайта по Reporting API: визиты, посетители, просмотры, отказы, источники. Токен хранится на сервере.
            </p>
          </div>
        </div>
        {status.data?.configured && !editing && (
          <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs shrink-0" disabled={testM.isPending} onClick={() => testM.mutate()}>
            {testM.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}Проверить связь
          </Button>
        )}
      </div>

      {status.isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
        : !status.data?.configured || editing
          ? <ConnectionForm companyId={companyId} current={status.data} onDone={() => setEditing(false)} />
          : <MetrikaDashboard companyId={companyId} status={status.data} onEdit={() => setEditing(true)} />}
    </div>
  )
}
