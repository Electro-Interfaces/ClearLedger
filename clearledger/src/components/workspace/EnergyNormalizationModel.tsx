/**
 * Витрина модели данных ЭЗС для раздела «Нормализация» (energy-профиль).
 *
 * Отражает нашу РЕАЛЬНУЮ внутреннюю многослойную БД, правильно организованную
 * под сводные таблицы / OLAP, на живых сессиях компании (РусГидро):
 *   • слои L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF (реальные счётчики);
 *   • звёздная схема: факт «Сессия зарядки» (меры) + измерения (кардинальность, топ-члены);
 *   • качество нормализации: заполнение полей + канонизация (коннектор/ФЛ-ЮЛ/регион/дедуп).
 *
 * Данные: GET /api/analytics/charge-sessions/model (по всему датасету, без периода).
 */
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getChargeModel,
  type ChargeModelDimension,
  type ChargeModelLayer,
  type ChargeModelMeasure,
} from '@/services/analyticsService'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtN } from '@/components/balance/balanceCalc'
import { ArrowRight, Database, KeyRound, Layers, Ruler, Sparkles, Star } from 'lucide-react'

/* ── тона слоёв (theme-aware) ── */
const LAYER_TONE: Record<ChargeModelLayer['tone'], { badge: string; bar: string; border: string }> = {
  raw: { badge: 'bg-slate-500/15 text-slate-600 dark:text-slate-300', bar: 'bg-slate-400/60', border: 'border-l-slate-400/50' },
  clean: { badge: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400', bar: 'bg-emerald-500/70', border: 'border-l-emerald-500/60' },
  export: { badge: 'bg-blue-500/15 text-blue-600 dark:text-blue-400', bar: 'bg-blue-500/70', border: 'border-l-blue-500/60' },
  ref: { badge: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400', bar: 'bg-zinc-400/50', border: 'border-l-zinc-400/40' },
}

function fmtMeasure(m: ChargeModelMeasure): string {
  if (m.unit === '%') return `${m.value.toLocaleString('ru-RU')}%`
  if (!m.unit) return fmtN(m.value)
  return `${fmtN(m.value)} ${m.unit}`
}

/* ── шкала заполнения (0–100%) ── */
function FillBar({ pct, tone = 'bg-primary/70' }: { pct: number; tone?: string }) {
  const warn = pct < 80
  const bar = warn ? 'bg-amber-500/70' : tone
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full max-w-[120px] overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      <span className={`w-11 shrink-0 text-right text-xs tabular-nums ${warn ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
        {pct.toLocaleString('ru-RU')}%
      </span>
    </div>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground/70">{sub}</div>}
    </CardContent></Card>
  )
}

/* ── карточка измерения (луч звезды) ── */
function DimensionCard({ d }: { d: ChargeModelDimension }) {
  return (
    <Card className="h-full">
      <CardContent className="space-y-2 pt-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">{d.label}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{d.field}</div>
          </div>
          <Badge variant="secondary" className="shrink-0 bg-primary/10 text-[10px] text-primary">
            {d.cardinality ? fmtN(d.cardinality) : '—'} знач.
          </Badge>
        </div>
        <FillBar pct={d.fill_pct} />
        <div className="flex flex-wrap items-center gap-1">
          {d.canonical && (
            <Badge variant="secondary" className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">канонизировано</Badge>
          )}
          {d.grain && <span className="text-[11px] text-muted-foreground">{d.grain}</span>}
        </div>
        {d.members.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {d.members.slice(0, 6).map((m) => (
              <span key={m.label} className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                <span className="max-w-[130px] truncate">{m.label}</span>
                <span className="tabular-nums text-foreground/70">{fmtN(m.count)}</span>
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function EnergyNormalizationModel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['charge-model', companyId],
    queryFn: () => getChargeModel(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  const m = q.data

  if (q.isLoading) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка модели данных…</div>
  }
  if (!m || m.rows === 0 || !m.fact) {
    return (
      <div className="px-6 py-10 text-sm text-muted-foreground">
        Нет загруженных сессий ЭЗС. Загрузите выгрузку ChargeTransactions в канале «Зарядные сессии ЭЗС»,
        затем модель данных (слои, звёздная схема, качество) отобразится здесь на реальных данных.
      </div>
    )
  }

  const { fact, layers, dimensions, quality } = m
  const period = fact.period.from && fact.period.to
    ? `${fact.period.from.split('-').reverse().join('.')} – ${fact.period.to.split('-').reverse().join('.')}`
    : '—'
  const energy = fact.measures.find((x) => x.key === 'energy_kwh')
  const amount = fact.measures.find((x) => x.key === 'amount')
  const ports = fact.measures.find((x) => x.key === 'ports')
  const success = fact.measures.find((x) => x.key === 'success_pct')

  return (
    <div className="space-y-5 px-6 py-6">
      {/* заголовок */}
      <div>
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">Модель данных · сеть ЭЗС</h1>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Внутренняя многослойная база (L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF), организованная
          звёздной схемой: факт «Сессия зарядки» + измерения. Готова к сводным таблицам и OLAP-анализу —
          строки/столбцы сводной = измерения, значения = меры.
        </p>
      </div>

      {/* KPI-полоса L2 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Сессий (L2)" value={fmtN(fact.rows)} sub={period} />
        <Kpi label="Энергия" value={energy ? fmtMeasure(energy) : '—'} />
        <Kpi label="Сумма списаний" value={amount ? fmtMeasure(amount) : '—'} />
        <Kpi label="Измерений" value={fmtN(dimensions.length)} sub="осей куба" />
        <Kpi label="Портов" value={ports ? fmtN(ports.value) : '—'} sub="станция × коннектор" />
        <Kpi label="Успешных" value={success ? fmtMeasure(success) : '—'} />
      </div>

      {/* Слои данных L1→L4 */}
      <Card><CardContent className="pt-5">
        <div className="mb-3 flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary" />
          <div className="text-sm font-medium">Слои данных</div>
          <span className="text-xs text-muted-foreground">приём → нормализация → витрины → 1С</span>
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
          {layers.map((l, i) => {
            const t = LAYER_TONE[l.tone]
            return (
              <div key={l.key} className="flex flex-1 items-stretch gap-3">
                <div className={`flex-1 rounded-lg border border-l-2 bg-muted/30 p-3 ${t.border}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-muted-foreground">{l.code}</span>
                    <Badge variant="secondary" className={`text-[10px] ${t.badge}`}>
                      {l.status === 'planned' ? 'план'
                        : l.status === 'direct' ? 'прямой импорт'
                        : l.records == null ? 'куб'
                        : `${fmtN(l.records)} ${l.unit}`}
                    </Badge>
                  </div>
                  <div className="mt-1 text-sm font-medium">{l.title}</div>
                  <p className="mt-1 text-xs text-muted-foreground">{l.desc}</p>
                </div>
                {i < layers.length - 1 && (
                  <ArrowRight className="hidden h-4 w-4 self-center text-muted-foreground/50 lg:block" />
                )}
              </div>
            )
          })}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground/70">
          L1 = загруженные выгрузки xlsx «как есть»; L2 = нормализованные сессии (эта витрина); L3 = OLAP-агрегаты
          (пункты меню сессий: обзор/станции/коннекторы/время/клиенты/надёжность/тренд/сравнение); L4 = обмен с 1С (для энергопрофиля в плане).
        </p>
      </CardContent></Card>

      {/* Звёздная схема */}
      <Card><CardContent className="pt-5">
        <div className="mb-3 flex items-center gap-2">
          <Star className="h-4 w-4 text-primary" />
          <div className="text-sm font-medium">Звёздная схема</div>
          <span className="text-xs text-muted-foreground">факт в центре, измерения — лучи</span>
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(220px,280px)_1fr]">
          {/* факт-таблица */}
          <Card className="border-primary/40 bg-primary/[0.03]">
            <CardContent className="space-y-2 pt-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <div className="text-sm font-semibold">{fact.name}</div>
              </div>
              <div className="font-mono text-[11px] text-muted-foreground">{fact.table}</div>
              <div className="text-[11px] text-muted-foreground">{fact.grain}</div>
              <div className="pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">Меры</div>
              <div className="space-y-1">
                {fact.measures.map((mm) => (
                  <div key={mm.key} className="flex items-center justify-between gap-2 border-b border-border/40 pb-1 last:border-0">
                    <span className="flex items-center gap-1.5 text-xs">
                      <Ruler className="h-3 w-3 text-muted-foreground/60" />
                      {mm.label}
                    </span>
                    <span className="tabular-nums text-xs font-medium">{fmtMeasure(mm)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          {/* измерения */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {dimensions.map((d) => <DimensionCard key={d.key} d={d} />)}
          </div>
        </div>
      </CardContent></Card>

      {/* Качество нормализации */}
      {quality && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* заполнение полей */}
          <Card><CardContent className="overflow-x-auto pt-5">
            <div className="mb-3 flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-primary" />
              <div className="text-sm font-medium">Заполнение полей</div>
            </div>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Поле</TableHead>
                <TableHead>Роль</TableHead>
                <TableHead className="min-w-[160px]">Заполнено</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {quality.fields.map((f) => (
                  <TableRow key={f.field}>
                    <TableCell className="font-medium">
                      {f.label}
                      <div className="font-mono text-[10px] text-muted-foreground">{f.field}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{f.role}</TableCell>
                    <TableCell><FillBar pct={f.fill_pct} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent></Card>

          {/* канонизация */}
          <Card><CardContent className="overflow-x-auto pt-5">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <div className="text-sm font-medium">Канонизация (L1 → L2)</div>
            </div>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Правило</TableHead>
                <TableHead>Из → В</TableHead>
                <TableHead className="text-center">Членов</TableHead>
                <TableHead className="min-w-[120px]">Покрытие</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {quality.canonicalization.map((c) => (
                  <TableRow key={c.name}>
                    <TableCell className="font-medium">{c.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.from} <ArrowRight className="mx-0.5 inline h-3 w-3" /> {c.to}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-xs">
                      {c.members == null ? '—' : fmtN(c.members)}
                    </TableCell>
                    <TableCell><FillBar pct={c.coverage_pct} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent></Card>
        </div>
      )}
    </div>
  )
}
