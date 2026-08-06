/**
 * Управленческий кокпит ЭЗС (раздел «Управленческий», energy):
 *   OpsOverviewVitrine — «Обзор»: общая ситуация (вход/отпуск/деньги по месяцам)
 *     + светофор проблем с РАБОЧИМИ СПИСКАМИ (где расхождения, где нет данных,
 *     кто не заплатил/не предоставил документы, что истекло) — для решений;
 *   OpsBalanceVitrine — «Баланс (факт)»: пообъектный энергобаланс за месяц:
 *     вход (счета) · отпуск (сессии) · собственные нужды (оценка) ·
 *     сверхнормативный небаланс · стоимость · выручка · маржа.
 *
 * Исследование строки — StationDrillModal (клик по строке ЛЮБОЙ таблицы):
 * паспорт объекта + договорные контуры (э/э/аренда/сервис) + помесячный баланс.
 * Полный рабочий список проблемы — IssueListModal (поиск + drill).
 * Фильтр по региону — в «Обзоре» и «Балансе» (серверный, /api/ops/*?region=).
 *
 * ⚠ Ширина модалок: базовый dialog.tsx перебивает sm:max-w-lg — задаём
 * sm:max-w-6xl прямо на DialogContent (как drill-down в ChargeChart).
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { ChevronDown, ChevronRight, MapPin, Plug, Search, Zap } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getOpsBalance, getOpsOverview, getOpsStation,
  type OpsIssue, type OpsIssueRow, type OpsStationContour,
} from '@/services/opsService'
import { PAYMENT_META, ROLE_LABEL, paidThroughLabel, type PaymentStatus, type SettlementRole } from '@/types/settlement'
import { fmtN } from '@/components/balance/balanceCalc'
import { formatBucket } from '@/lib/formatDate'
import { MetricTile as Kpi } from '@/components/ui/metric-tile'

const dLabel = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : null)

/* ── фильтр по региону (селект из данных ответа) ── */
function RegionSelect({ regions, value, onChange }: {
  regions: string[]; value: string | undefined; onChange: (v: string | undefined) => void
}) {
  if (!regions.length) return null
  return (
    <Select value={value ?? '__all'} onValueChange={(v) => onChange(v === '__all' ? undefined : v)}>
      <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent className="max-h-[300px]">
        <SelectItem value="__all">Все регионы</SelectItem>
        {regions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

/* ═══════════════ Модалка объекта: паспорт + контуры + баланс ═══════════════ */
function ContourCard({ c }: { c: OpsStationContour }) {
  const meta = PAYMENT_META[c.paymentStatus as PaymentStatus] ?? PAYMENT_META.unknown
  const amount = c.amountGross ?? c.amountNet
  const varGross = typeof c.extra?.variableGross === 'number' ? c.extra.variableGross : null
  const expired = !!(c.contractEnd && c.contractEnd < new Date().toISOString().slice(0, 10))
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{ROLE_LABEL[c.role as SettlementRole] ?? c.role}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}>
          {paidThroughLabel({ paymentStatus: c.paymentStatus as PaymentStatus, paidThrough: c.paidThrough })}
        </span>
        {c.basis && c.basis !== 'договор' && <Badge variant="secondary" className="text-[10px]">{c.basis}</Badge>}
        {expired && <Badge variant="secondary" className="bg-red-500/15 text-[10px] text-red-600 dark:text-red-400">договор истёк</Badge>}
      </div>
      <div className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        <div><span className="text-muted-foreground">Контрагент: </span>{c.counterpartyName || '—'}</div>
        <div><span className="text-muted-foreground">Договор: </span>{c.contractNumber || '—'}
          {(c.contractStart || c.contractEnd) && (
            <span className="text-muted-foreground"> · {dLabel(c.contractStart) || '…'} — {dLabel(c.contractEnd) || '…'}</span>
          )}
        </div>
        {amount != null && (
          <div><span className="text-muted-foreground">Плата: </span>
            {fmtN(Math.round(amount))} ₽/мес{c.amountGross == null && ' (без НДС)'}
            {c.vatPct != null && <span className="text-muted-foreground"> · НДС {c.vatPct}%</span>}
          </div>
        )}
        {varGross != null && <div><span className="text-muted-foreground">Переменная часть: </span>{fmtN(Math.round(varGross))} ₽</div>}
        {typeof c.extra?.avgTariff === 'number' && (
          <div><span className="text-muted-foreground">Средний тариф: </span>{(c.extra.avgTariff as number).toFixed(2)} ₽/кВт·ч</div>
        )}
        {typeof c.extra?.contacts === 'string' && (
          <div className="sm:col-span-2"><span className="text-muted-foreground">Контакты: </span>{c.extra.contacts as string}</div>
        )}
        {c.comment && <div className="sm:col-span-2 text-muted-foreground/80">{c.comment}</div>}
      </div>
    </div>
  )
}

export function StationDrillModal({ locationId, onClose }: { locationId: string | null; onClose: () => void }) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['ops-station', companyId, locationId],
    queryFn: () => getOpsStation(companyId, locationId!),
    enabled: !!companyId && !!locationId,
    staleTime: 60_000,
  })
  const s = q.data
  const last12 = (s?.series ?? []).slice(-12)
  const maxKwh = Math.max(1, ...last12.map((p) => Math.max(p.intakeKwh ?? 0, p.dispensedKwh)))
  return (
    <Dialog open={!!locationId} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2 pr-6">
            {s?.found ? <>ЭЗС {s.bu ? `№${s.bu}` : ''} — {s.name}</> : 'Карточка объекта'}
            {s?.status && s.status !== 'unknown' && <Badge variant="secondary" className="text-[10px]">{s.status}</Badge>}
          </DialogTitle>
        </DialogHeader>
        {q.isLoading && <p className="py-8 text-sm text-muted-foreground">Загрузка карточки…</p>}
        {s?.found && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {s.address && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{s.address}{s.region && ` · ${s.region}`}</span>}
              {s.powerKw != null && <span className="inline-flex items-center gap-1"><Zap className="h-3 w-3" />{s.powerKw} кВт</span>}
              {s.connectors != null && <span className="inline-flex items-center gap-1"><Plug className="h-3 w-3" />{s.connectors} конн.</span>}
              {s.zoi && <span>ZOI-1: {s.zoi}</span>}
              {s.serial && <span>зав.№ {s.serial}</span>}
              {s.ownUseEstKwh != null && <span>СН ≈{fmtN(s.ownUseEstKwh)} кВт·ч/мес (по простоям)</span>}
              {s.avgTariff != null && <span>тариф ср. {s.avgTariff.toFixed(2)} ₽/кВт·ч</span>}
            </div>

            {s.contours.length > 0 ? (
              <div className="grid gap-2 lg:grid-cols-3">
                {s.contours.map((c, i) => <ContourCard key={`${c.role}-${i}`} c={c} />)}
              </div>
            ) : (
              <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                Договорных контуров нет — объект не сопоставлен в реестрах «Энергоснабжение и аренда ЭЗС»
                (или строки-сироты). Проверить № БУ в реестре и «Обработать все» в канале.
              </p>
            )}

            <div>
              <div className="mb-2 flex items-center gap-2">
                <div className="text-sm font-medium">Энергобаланс по месяцам</div>
                <span className="text-xs text-muted-foreground/70">▬ вход по счетам · ▬ отпуск по сессиям</span>
              </div>
              <div className="overflow-x-auto rounded-md border border-border/40">
                <Table><TableHeader><TableRow>
                  <TableHead>Месяц</TableHead>
                  <TableHead className="w-[22%]"></TableHead>
                  <TableHead className="text-right">Вход, кВт·ч</TableHead>
                  <TableHead className="text-right">Отпуск, кВт·ч</TableHead>
                  <TableHead className="text-right">Сессий</TableHead>
                  <TableHead className="text-right">Небаланс</TableHead>
                  <TableHead className="text-right">Сверхнорм.</TableHead>
                  <TableHead className="text-right">Тариф, ₽</TableHead>
                  <TableHead className="text-right">Затраты, ₽</TableHead>
                  <TableHead className="text-right">Выручка, ₽</TableHead>
                </TableRow></TableHeader><TableBody>
                  {last12.map((p) => (
                    <TableRow key={p.period}>
                      <TableCell className="font-medium whitespace-nowrap">{formatBucket(p.period)}</TableCell>
                      <TableCell>
                        <div className="space-y-0.5">
                          <div className="h-1.5 rounded-sm bg-primary/70" style={{ width: `${Math.max(1, ((p.intakeKwh ?? 0) / maxKwh) * 100)}%` }} />
                          <div className="h-1.5 rounded-sm bg-emerald-500/60" style={{ width: `${Math.max(1, (p.dispensedKwh / maxKwh) * 100)}%` }} />
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.intakeKwh != null ? fmtN(Math.round(p.intakeKwh))
                          : <span className="rounded bg-amber-500/15 px-1 text-[9px] text-amber-600 dark:text-amber-400">нет счетов</span>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmtN(Math.round(p.dispensedKwh))}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.sessions || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.imbalanceKwh != null ? fmtN(Math.round(p.imbalanceKwh)) : '—'}</TableCell>
                      <TableCell className={`text-right tabular-nums ${(p.overImbalanceKwh ?? 0) > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                        {p.overImbalanceKwh != null && p.overImbalanceKwh > 0 ? fmtN(Math.round(p.overImbalanceKwh)) : '—'}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.tariff != null ? p.tariff.toFixed(2) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.costEst != null ? fmtN(p.costEst) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.revenue != null ? fmtN(p.revenue) : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody></Table>
              </div>
            </div>
          </div>
        )}
        {s && !s.found && <p className="py-8 text-sm text-muted-foreground">Объект не найден.</p>}
      </DialogContent>
    </Dialog>
  )
}

/* ═══════════ Модалка полного рабочего списка проблемы (поиск + drill) ═══════════ */
function IssueListModal({ issue, onClose, onOpenStation }: {
  issue: OpsIssue | null; onClose: () => void; onOpenStation: (id: string) => void
}) {
  const [text, setText] = useState('')
  const rows = useMemo(() => {
    if (!issue) return []
    const t = text.trim().toLowerCase()
    if (!t) return issue.rows
    return issue.rows.filter((r) =>
      (r.bu || '').toLowerCase().includes(t) || r.name.toLowerCase().includes(t)
      || (r.region || '').toLowerCase().includes(t) || (r.note || '').toLowerCase().includes(t))
  }, [issue, text])
  return (
    <Dialog open={!!issue} onOpenChange={(v) => { if (!v) { setText(''); onClose() } }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="pr-6">{issue?.label}</DialogTitle>
        </DialogHeader>
        {issue && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{issue.hint}</p>
            <div className="relative w-[260px]">
              <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Поиск: №, имя, регион, комментарий"
                className="h-8 pl-7 text-xs" />
            </div>
            <div className="max-h-[52vh] overflow-auto rounded-md border border-border/40">
              <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
                <TableHead>№ БУ</TableHead><TableHead>ЭЗС</TableHead><TableHead>Регион</TableHead>
                <TableHead className="text-right">{issue.unit || 'Показатель'}</TableHead>
                <TableHead>Комментарий</TableHead>
              </TableRow></TableHeader><TableBody>
                {rows.map((r) => (
                  <TableRow key={`${r.locationId}-${r.note}`} className="cursor-pointer hover:bg-muted/40"
                    onClick={() => onOpenStation(r.locationId)}>
                    <TableCell className="font-medium tabular-nums whitespace-nowrap">{r.bu || '—'}</TableCell>
                    <TableCell className="max-w-[260px] truncate text-xs">{r.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.region || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.value != null && r.value !== 0 ? fmtN(Math.round(r.value)) : '—'}</TableCell>
                    <TableCell className="max-w-[280px] text-xs text-muted-foreground">{r.note}</TableCell>
                  </TableRow>
                ))}
              </TableBody></Table>
            </div>
            <p className="text-[11px] text-muted-foreground/70">
              {rows.length} из {issue.count} · клик по строке — карточка объекта (договоры/баланс/оплаты).
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/* ── карточка проблемы: top-5 + «показать все» + drill по строке ── */
function IssueCard({ issue, onOpenAll, onOpenStation }: {
  issue: OpsIssue; onOpenAll: (i: OpsIssue) => void; onOpenStation: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const tone = issue.severity === 'red'
    ? { badge: 'bg-red-500/15 text-red-600 dark:text-red-400', border: issue.count ? 'border-l-red-500/60' : '' }
    : { badge: 'bg-amber-500/15 text-amber-600 dark:text-amber-400', border: issue.count ? 'border-l-amber-500/60' : '' }
  const dim = issue.count === 0
  const top = issue.rows.slice(0, 5)
  return (
    <Card className={`border-l-2 ${dim ? 'border-l-emerald-500/40 opacity-70' : tone.border}`}>
      <CardContent className="pt-4">
        <button type="button" className="flex w-full items-start gap-2 text-left"
          onClick={() => top.length > 0 && setOpen((v) => !v)}>
          <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${dim ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : tone.badge}`}>
            {fmtN(issue.count)}
          </span>
          <span className="flex-1">
            <span className="block text-sm font-medium">{issue.label}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{issue.hint}</span>
          </span>
          {top.length > 0 && (
            open ? <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
                 : <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
        </button>
        {open && top.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="overflow-x-auto rounded-md border border-border/40">
              <Table><TableBody>
                {top.map((r: OpsIssueRow) => (
                  <TableRow key={`${issue.key}-${r.locationId}-${r.note}`} className="cursor-pointer hover:bg-muted/40"
                    onClick={() => onOpenStation(r.locationId)}>
                    <TableCell className="w-16 font-medium tabular-nums whitespace-nowrap">{r.bu || '—'}</TableCell>
                    <TableCell className="max-w-[220px] truncate text-xs">{r.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.value != null && r.value !== 0 ? fmtN(Math.round(r.value)) : ''}</TableCell>
                    <TableCell className="max-w-[220px] truncate text-xs text-muted-foreground">{r.note}</TableCell>
                  </TableRow>
                ))}
              </TableBody></Table>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted-foreground/70">клик по строке — карточка объекта</span>
              {issue.count > top.length && (
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => onOpenAll(issue)}>
                  Показать все ({fmtN(issue.count)})
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ═════════════════ «Обзор» — общая ситуация + светофор проблем ═════════════════ */
export function OpsOverviewVitrine({ embedded }: {
  /** Витрина внутри чужого экрана («Пульс»): свой h1 и внешний отступ там лишние. */
  embedded?: boolean
} = {}) {
  const { companyId } = useCompany()
  const rootRef = useRef<HTMLDivElement>(null)
  const [region, setRegion] = useState<string | undefined>(undefined)
  const [drill, setDrill] = useState<string | null>(null)
  const [issueModal, setIssueModal] = useState<OpsIssue | null>(null)
  const q = useQuery({
    queryKey: ['ops-overview', companyId, region ?? 'all'],
    queryFn: () => getOpsOverview(companyId, region),
    enabled: !!companyId, staleTime: 60_000,
  })
  const d = q.data
  if (q.isLoading && !d) return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка кокпита…</div>
  if (!d || (d.series.length === 0 && !region)) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Нет данных: загрузите реестры (канал «Энергоснабжение и аренда ЭЗС») и сессии.</div>
  }
  const k = d.kpis
  const last12 = d.series.slice(-12)
  const maxKwh = Math.max(1, ...last12.map((s) => Math.max(s.intakeKwh, s.dispensedKwh)))
  const red = d.issues.filter((i) => i.severity === 'red')
  const amber = d.issues.filter((i) => i.severity === 'amber')
  return (
    <div ref={rootRef} className={embedded ? 'space-y-5' : 'space-y-5 px-6 py-6'}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            {/* Второй h1 на странице «Пульса» ломал и заголовочную структуру, и
                визуальную иерархию: заголовок экрана там уже стоит. */}
            {!embedded && <h1 className="text-xl font-semibold">Управленческий обзор ЭЗС</h1>}
            <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
            <ExportButton title="Управленческий обзор ЭЗС" subtitle={region} getEl={() => rootRef.current} />
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Общая ситуация по обязательствам и энергобалансу сети + конкретные проблемы с рабочими
            списками — что требует действий во внешнем мире (контрагенты, договоры, счета).
            {k.refPeriod && <> Опорный месяц анализа — <b className="text-foreground">{formatBucket(k.refPeriod)}</b> (последний с полными данными входа).</>}
          </p>
        </div>
        <RegionSelect regions={d.regions} value={region} onChange={setRegion} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label={`Затраты на э/э (${k.refPeriod ? formatBucket(k.refPeriod) : '—'}), ₽`} value={k.energyCostRef != null ? fmtN(k.energyCostRef) : '—'} sub="вход × входящий тариф (оценка)" />
        <Kpi label="Аренда, ₽/мес (постоянная часть)" value={fmtN(k.rentMonthly)} sub={`${k.rentContractsWithAmount} договоров с суммой`} />
        <Kpi label={`Выручка сессий (${k.refPeriod ? formatBucket(k.refPeriod) : '—'}), ₽`} value={k.revenueRef != null ? fmtN(k.revenueRef) : '—'} sub={region ? region : 'вся сеть, вкл. корп-тарифы'} />
        <Kpi label="Проблемных позиций" value={fmtN(k.issuesTotal)} sub={`${k.issuesRed} красных зон`} accent={k.issuesRed ? 'danger' : undefined} />
      </div>

      {/* Энергобаланс сети по месяцам: вход vs отпуск (+СН) */}
      <Card><CardContent className="space-y-3 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-sm font-medium">Энергобаланс {region ? `— ${region}` : 'сети'} по месяцам</div>
          <span className="text-xs text-muted-foreground/70">
            вход (счета) = отпуск (сессии) + собственные нужды станций (СН, медиана ≈{fmtN(k.ownUseFleetMedianKwh)} кВт·ч/мес) + потери
          </span>
        </div>
        <Table><TableHeader><TableRow>
          <TableHead>Месяц</TableHead>
          <TableHead className="w-[26%]">Вход / Отпуск</TableHead>
          <TableHead className="text-right">Вход, кВт·ч</TableHead>
          <TableHead className="text-right">ЭЗС со счетами</TableHead>
          <TableHead className="text-right">Отпуск, кВт·ч</TableHead>
          <TableHead className="text-right">Сверхнорматив, кВт·ч</TableHead>
          <TableHead className="text-right">Затраты (оценка), ₽</TableHead>
          <TableHead className="text-right">Выручка, ₽</TableHead>
        </TableRow></TableHeader><TableBody>
          {last12.map((s) => {
            const dataGap = s.intakeStations === 0 || (s.dispensedKwh > 0 && s.intakeKwh < s.dispensedKwh * 0.2)
            return (
              <TableRow key={s.period} className={dataGap ? 'opacity-60' : ''}>
                <TableCell className="font-medium whitespace-nowrap">
                  {formatBucket(s.period)}
                  {dataGap && <span className="ml-1 rounded bg-amber-500/15 px-1 text-[9px] text-amber-600 dark:text-amber-400">нет счетов</span>}
                </TableCell>
                <TableCell>
                  <div className="space-y-0.5">
                    <div className="h-1.5 rounded-sm bg-primary/70" style={{ width: `${Math.max(1, (s.intakeKwh / maxKwh) * 100)}%` }} />
                    <div className="h-1.5 rounded-sm bg-emerald-500/60" style={{ width: `${Math.max(1, (s.dispensedKwh / maxKwh) * 100)}%` }} />
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(Math.round(s.intakeKwh))}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{s.intakeStations}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(Math.round(s.dispensedKwh))}</TableCell>
                <TableCell className={`text-right tabular-nums ${s.overImbalanceKwh > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                  {s.overImbalanceKwh > 0 ? fmtN(Math.round(s.overImbalanceKwh)) : '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{s.costEst != null ? fmtN(s.costEst) : '—'}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{s.revenue != null ? fmtN(s.revenue) : '—'}</TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
        <p className="text-xs text-muted-foreground/70">
          ▬ синий — вход по счетам контрагентов · ▬ зелёный — отпуск по сессиям. «Нет счетов» —
          вход за месяц ещё не выставлен/не загружен: затраты и небаланс не считаются. Пообъектная
          детализация — пункт «Баланс (факт)».
        </p>
      </CardContent></Card>

      {/* Светофор проблем: красные зоны → действия */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <div className="text-sm font-medium">Красные зоны — требуют действий</div>
          <Badge className="bg-red-500/15 text-[10px] text-red-600 dark:text-red-400">{red.reduce((a, i) => a + i.count, 0)}</Badge>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {red.map((i) => <IssueCard key={i.key} issue={i} onOpenAll={setIssueModal} onOpenStation={setDrill} />)}
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center gap-2">
          <div className="text-sm font-medium">Жёлтые зоны — контроль и запрос данных</div>
          <Badge className="bg-amber-500/15 text-[10px] text-amber-600 dark:text-amber-400">{amber.reduce((a, i) => a + i.count, 0)}</Badge>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {amber.map((i) => <IssueCard key={i.key} issue={i} onOpenAll={setIssueModal} onOpenStation={setDrill} />)}
        </div>
      </div>

      <IssueListModal issue={issueModal} onClose={() => setIssueModal(null)}
        onOpenStation={(id) => setDrill(id)} />
      <StationDrillModal locationId={drill} onClose={() => setDrill(null)} />
    </div>
  )
}

/* ═════════════ «Баланс (факт)» — пообъектный энергобаланс за месяц ═════════════ */
type SortKey = 'over' | 'intake' | 'dispensed' | 'margin' | 'bu'

export function OpsBalanceVitrine() {
  const { companyId } = useCompany()
  const rootRef = useRef<HTMLDivElement>(null)
  const [period, setPeriod] = useState<string | undefined>(undefined)
  const [region, setRegion] = useState<string | undefined>(undefined)
  const [qtext, setQtext] = useState('')
  const [flt, setFlt] = useState<'all' | 'over' | 'no_intake' | 'idle' | 'neg_margin'>('all')
  const [sort, setSort] = useState<SortKey>('over')
  const [drill, setDrill] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['ops-balance', companyId, period ?? 'last', region ?? 'all'],
    queryFn: () => getOpsBalance(companyId, period, region),
    enabled: !!companyId, staleTime: 60_000,
  })
  const d = q.data
  const rows = useMemo(() => {
    let r = d?.rows ?? []
    if (qtext.trim()) {
      const t = qtext.trim().toLowerCase()
      r = r.filter((x) => (x.bu || '').toLowerCase().includes(t) || x.name.toLowerCase().includes(t) || (x.region || '').toLowerCase().includes(t))
    }
    if (flt === 'over') r = r.filter((x) => (x.overImbalanceKwh ?? 0) > 0)
    if (flt === 'no_intake') r = r.filter((x) => x.intakeKwh == null && x.dispensedKwh > 0)
    if (flt === 'idle') r = r.filter((x) => (x.intakeKwh ?? 0) > 0 && x.dispensedKwh <= 0)
    if (flt === 'neg_margin') r = r.filter((x) => (x.marginEst ?? 0) < 0 && x.marginEst != null)
    const key: Record<SortKey, (x: typeof r[number]) => number | string> = {
      over: (x) => -(x.overImbalanceKwh ?? -1),
      intake: (x) => -(x.intakeKwh ?? -1),
      dispensed: (x) => -x.dispensedKwh,
      margin: (x) => (x.marginEst ?? Number.POSITIVE_INFINITY),
      bu: (x) => Number(x.bu) || 1e9,
    }
    return [...r].sort((a, b) => {
      const ka = key[sort](a), kb = key[sort](b)
      return ka < kb ? -1 : ka > kb ? 1 : 0
    })
  }, [d, qtext, flt, sort])

  if (q.isLoading && !d) return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка баланса…</div>
  if (!d || !d.period) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Нет данных входа э/э — загрузите «Сводную» в канале реестров.</div>
  }
  const totals = rows.reduce((a, r) => ({
    intake: a.intake + (r.intakeKwh ?? 0), disp: a.disp + r.dispensedKwh,
    over: a.over + (r.overImbalanceKwh ?? 0),
    cost: a.cost + (r.costEst ?? 0), rev: a.rev + (r.revenue ?? 0),
  }), { intake: 0, disp: 0, over: 0, cost: 0, rev: 0 })
  return (
    <div ref={rootRef} className="space-y-4 px-6 py-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Энергобаланс по объектам</h1>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
          <ExportButton title="Энергобаланс по объектам" subtitle={d.period ? formatBucket(d.period) : undefined} getEl={() => rootRef.current} />
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Вход по счетам vs отпуск по сессиям vs собственные нужды (СН ≈{fmtN(d.ownUseFleetMedianKwh)} кВт·ч/мес медиана парка,
          у станций с историей простоя — их собственная). Сверхнорматив — расхождение сверх СН: повод проверить счета и учёт.
          Клик по строке — карточка объекта.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={d.period} onValueChange={(v) => setPeriod(v)}>
          <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {[...d.months].reverse().map((m) => <SelectItem key={m} value={m}>{formatBucket(m)}</SelectItem>)}
          </SelectContent>
        </Select>
        <RegionSelect regions={d.regions} value={region} onChange={setRegion} />
        <Select value={flt} onValueChange={(v) => setFlt(v as typeof flt)}>
          <SelectTrigger className="h-8 w-[230px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все объекты</SelectItem>
            <SelectItem value="over">Сверхнормативный небаланс</SelectItem>
            <SelectItem value="no_intake">Нет входа (есть продажи)</SelectItem>
            <SelectItem value="idle">Простой (вход без продаж)</SelectItem>
            <SelectItem value="neg_margin">Отрицательная маржа э/э</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
          <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="over">Сортировка: сверхнорматив</SelectItem>
            <SelectItem value="intake">Сортировка: вход</SelectItem>
            <SelectItem value="dispensed">Сортировка: отпуск</SelectItem>
            <SelectItem value="margin">Сортировка: маржа ↑</SelectItem>
            <SelectItem value="bu">Сортировка: № БУ</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={qtext} onChange={(e) => setQtext(e.target.value)} placeholder="Поиск: №, имя, регион"
            className="h-8 w-[220px] pl-7 text-xs" />
        </div>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {rows.length} объектов · вход {fmtN(Math.round(totals.intake))} · отпуск {fmtN(Math.round(totals.disp))} кВт·ч
          {totals.over > 0 && <> · сверхнорматив <span className="text-amber-600 dark:text-amber-400">{fmtN(Math.round(totals.over))}</span></>}
        </span>
      </div>

      <Card><CardContent className="pt-4">
        <div className="max-h-[560px] overflow-auto rounded-md border border-border/40">
          <Table><TableHeader className="sticky top-0 z-10 bg-card"><TableRow>
            <TableHead>№ БУ</TableHead>
            <TableHead>ЭЗС</TableHead>
            <TableHead className="text-right">Вход, кВт·ч</TableHead>
            <TableHead className="text-right">Отпуск, кВт·ч</TableHead>
            <TableHead className="text-right">Сессий</TableHead>
            <TableHead className="text-right">СН (оценка)</TableHead>
            <TableHead className="text-right">Сверхнорматив</TableHead>
            <TableHead className="text-right">Тариф, ₽</TableHead>
            <TableHead className="text-right">Затраты, ₽</TableHead>
            <TableHead className="text-right">Выручка, ₽</TableHead>
            <TableHead className="text-right">Маржа э/э, ₽</TableHead>
          </TableRow></TableHeader><TableBody>
            {rows.map((r) => {
              const overBad = (r.overImbalanceKwh ?? 0) > 0
              const noIn = r.intakeKwh == null && r.dispensedKwh > 0
              return (
                <TableRow key={r.locationId} className="cursor-pointer hover:bg-muted/40"
                  onClick={() => setDrill(r.locationId)}>
                  <TableCell className="font-medium tabular-nums whitespace-nowrap">{r.bu || '—'}</TableCell>
                  <TableCell className="max-w-[240px]">
                    <span className="block truncate text-xs">{r.name}</span>
                    {r.region && <span className="block truncate text-[10px] text-muted-foreground/70">{r.region}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.intakeKwh != null ? fmtN(Math.round(r.intakeKwh))
                      : <span className="rounded bg-amber-500/15 px-1 text-[9px] text-amber-600 dark:text-amber-400">{noIn ? 'нет счетов' : '—'}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmtN(Math.round(r.dispensedKwh))}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.sessions || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.ownUseEstKwh != null ? fmtN(Math.round(r.ownUseEstKwh)) : '—'}</TableCell>
                  <TableCell className={`text-right tabular-nums ${overBad ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                    {r.overImbalanceKwh != null && r.overImbalanceKwh > 0
                      ? <>{fmtN(Math.round(r.overImbalanceKwh))}{r.overImbalancePct != null && <span className="ml-0.5 text-[10px]">({r.overImbalancePct}%)</span>}</>
                      : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.tariff != null ? r.tariff.toFixed(2) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.costEst != null ? fmtN(r.costEst) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.revenue != null ? fmtN(r.revenue) : '—'}</TableCell>
                  <TableCell className={`text-right tabular-nums ${r.marginEst != null && r.marginEst < 0 ? 'font-medium text-red-600 dark:text-red-400' : ''}`}>
                    {r.marginEst != null ? fmtN(r.marginEst) : '—'}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody></Table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground/70">
          Маржа э/э = выручка сессий − затраты на вход (без аренды и сервиса). «Нет счетов» — объект
          продаёт, но входа за месяц нет: запросить документы у поставщика. Простой — вход без
          продаж: станция жжёт деньги (плюс аренда) — решение о ремонте/переносе.
        </p>
      </CardContent></Card>

      <StationDrillModal locationId={drill} onClose={() => setDrill(null)} />
    </div>
  )
}
