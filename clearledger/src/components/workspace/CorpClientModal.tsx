/**
 * Карточка корпоративного клиента (ЮЛ) — открывается кликом по строке реестра.
 *
 * Отвечает на вопрос «как развиваются отношения с этим клиентом»: помесячная
 * реализация за период (основа — по месяцам живёт корп-договор: акт, счёт,
 * лимит), профиль потребления (станции · регионы · коннекторы · карты), режим
 * эксплуатации парка и срок отношений.
 *
 * Данные: /api/corporate/client-card (CorporateService.client_card).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'
import { TrendingDown, TrendingUp, Minus } from 'lucide-react'
import { getCorporateClientCard, type CorpClientCard, type CorpBreakdown } from '@/services/corporateService'
import { fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { seriesColor } from './analytics/palette'
import { TzToggle, type Tz } from './analytics/TzToggle'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'
import { MONTHS_SHORT_NOM } from '@/lib/formatDate'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** «янв 2026» — ось графика и первая колонка таблицы месяцев. */
function monthLabel(iso: string): string {
  const [y, m] = iso.split('-').map(Number)
  return `${MONTHS_SHORT_NOM[m - 1]} ${y}`
}

/** Дней от даты до сегодня — «последняя зарядка 7 дней назад». */
function daysAgo(iso: string | null): number | null {
  if (!iso) return null
  const [y, m, d] = iso.split('-').map(Number)
  const then = new Date(y, m - 1, d).getTime()
  return Math.floor((Date.now() - then) / 86_400_000)
}

export function CorpClientModal({ client, companyId, dateFrom, dateTo, onClose }: {
  client: string; companyId: string; dateFrom: string; dateTo: string; onClose: () => void
}) {
  // Горизонт ряда месяцев. 0 = контур рабочей области; больше — только для
  // графика и таблицы месяцев (итоги и разрезы всегда по контуру). Живёт в
  // useState и умирает с модалкой: персист заставил бы карточку через неделю
  // молча показывать чужой горизонт.
  const [horizon, setHorizon] = useState(0)
  const [tz, setTz] = useState<Tz>('msk')   // часы активности: МСК по умолчанию
  const { data: d, isLoading, error } = useQuery({
    queryKey: ['corp-client-card', companyId, client, dateFrom, dateTo, horizon, tz],
    queryFn: () => getCorporateClientCard({ companyId, client, dateFrom, dateTo, historyMonths: horizon, tz }),
  })

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-5xl w-full max-h-[88vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-3.5 border-b border-border/50">
          <div className="min-w-0">
            <h3 className="text-base font-semibold truncate">{client}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {d ? [
                d.profile.status,
                d.profile.contract_start ? `договор с ${d.profile.contract_start}` : null,
                d.profile.mode === 'flat' && d.profile.rate ? `плоский ${nf(d.profile.rate, 2)} ₽/кВтч`
                  : d.profile.mode === 'matrix' ? 'тариф по матрице' : 'розничный тариф',
                d.profile.phone,
              ].filter(Boolean).join(' · ') : ' '}
            </p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none px-2 shrink-0">×</button>
        </div>

        <div className="overflow-auto p-5 space-y-5">
          {isLoading ? <div className="text-sm text-muted-foreground py-10 text-center">Загрузка карточки…</div>
            : error || !d ? <div className="text-sm text-muted-foreground py-10 text-center">Не удалось загрузить карточку клиента</div>
            : <Body d={d} horizon={horizon} setHorizon={setHorizon} tz={tz} setTz={setTz} />}
        </div>
      </div>
    </div>
  )
}

function Body({ d, horizon, setHorizon, tz, setTz }: {
  d: CorpClientCard; horizon: number; setHorizon: (n: number) => void
  tz: Tz; setTz: (tz: Tz) => void
}) {
  const t = d.totals
  const full = d.months.filter((m) => !m.partial)
  // Тренд — по полным месяцам: неполный край периода иначе читался бы как обвал.
  const trend = full.length >= 2
    ? (full[full.length - 1].corp_revenue - full[0].corp_revenue) / (full[0].corp_revenue || 1) * 100
    : null
  const since = daysAgo(d.lifetime.last_session)

  return (
    <>
      {/* итоги за период */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Metric label="Сессий" value={nf(t.sessions)} />
        <Metric label="Энергия" value={`${nf(t.energy_kwh)} кВтч`} />
        <Metric label="Выручка" value={`${fmtMoney(t.corp_revenue)} ₽`} hint="по договору" />
        <Metric label="Средний тариф" value={`${nf(t.avg_tariff, 2)} ₽/кВтч`} />
        <Metric label="Средний чек" value={`${fmtMoney(d.averages.avg_check)} ₽`} hint={`${nf(d.averages.avg_kwh, 1)} кВтч за сессию`} />
        <Metric label="Скидка к рознице" value={`${nf(t.discount_pct, 1)}%`}
          hint={t.discount ? `${fmtMoney(Math.abs(t.discount))} ₽ ${t.discount < 0 ? 'недополучено' : 'сверх'}` : undefined}
          cls={t.discount_pct <= -20 ? 'text-amber-300/90' : t.discount_pct < 0 ? 'text-muted-foreground' : ''} />
      </div>

      {/* сколько лет клиенту и когда заряжался в последний раз */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border bg-muted/30 px-3.5 py-2.5 text-xs">
        <span className="text-muted-foreground">За всю историю:</span>
        <span><b className="tabular-nums">{nf(d.lifetime.sessions)}</b> сессий на <b className="tabular-nums">{fmtMoney(d.lifetime.corp_revenue)} ₽</b></span>
        {d.lifetime.first_session && <span className="text-muted-foreground">первая зарядка {d.lifetime.first_session}</span>}
        {d.lifetime.last_session && (
          <span className={since != null && since > 30 ? 'text-amber-300/90' : 'text-muted-foreground'}>
            последняя {d.lifetime.last_session}{since != null && since > 0 ? ` — ${since} дн. назад` : ''}
          </span>
        )}
      </div>

      {/* ── помесячная реализация: ядро карточки ── */}
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">Реализация по месяцам</h4>
            {/* Горизонт — только для этого блока: на контуре в три недели
                динамики не видно. Расширение видно бейджем, скрытых состояний нет. */}
            <div className="inline-flex rounded-md border bg-muted/60 p-0.5">
              {[[0, 'Период'], [6, '6 мес'], [12, '12 мес']].map(([v, label]) => (
                <button key={String(v)} onClick={() => setHorizon(Number(v))}
                  className={`rounded px-2 py-0.5 text-[11px] transition-colors ${horizon === v
                    ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {label}
                </button>
              ))}
            </div>
            {horizon > 0 && (
              <span className="rounded border border-amber-400/40 px-1.5 py-0.5 text-[10px] text-amber-300/90"
                title="Ряд месяцев шире периода рабочей области. Итоги и разрезы выше — по периоду.">
                ряд шире периода: с {monthLabel(d.months_period.from)}
              </span>
            )}
          </div>
          {trend != null && (
            <span className={`inline-flex items-center gap-1.5 text-xs ${trend <= -15 ? 'text-red-400/90' : trend >= 15 ? 'text-emerald-400/90' : 'text-muted-foreground'}`}>
              {trend <= -5 ? <TrendingDown className="h-3.5 w-3.5" /> : trend >= 5 ? <TrendingUp className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />}
              {monthLabel(full[0].month)} → {monthLabel(full[full.length - 1].month)}: {trend > 0 ? '+' : ''}{nf(trend, 1)}%
            </span>
          )}
        </div>

        {d.months.length === 0 ? <Empty text="За период нет ни одной сессии" /> : (
          <>
            <div className="h-52 rounded-lg border bg-muted/20 p-3">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={d.months} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/40" vertical={false} />
                  <XAxis dataKey="month" tickFormatter={monthLabel} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis yAxisId="l" tickFormatter={(v) => fmtMoneyShort(Number(v))} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={52} />
                  <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={38} />
                  <Tooltip {...rechartsTooltipTheme}
                    labelFormatter={(v) => monthLabel(String(v))}
                    formatter={(value, name) => name === 'Выручка'
                      ? [`${fmtMoney(Number(value))} ₽`, name]
                      : [nf(Number(value)), name]}
                    contentStyle={{ fontSize: 12 }} />
                  <Bar yAxisId="l" dataKey="corp_revenue" name="Выручка" radius={[3, 3, 0, 0]}>
                    {/* Неполный месяц гасим: столбик ниже не потому, что клиент
                        стал меньше ездить, а потому что период обрезал месяц. */}
                    {d.months.map((m, i) => (
                      <Cell key={i} fill={seriesColor(0, 3)} fillOpacity={m.partial ? 0.35 : 1} />
                    ))}
                  </Bar>
                  <Line yAxisId="r" type="monotone" dataKey="sessions" name="Сессии"
                    stroke={seriesColor(2, 3)} strokeWidth={2} dot={{ r: 2.5 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Месяц</th>
                    <th className="p-2 text-right font-medium">Сессий</th>
                    <th className="p-2 text-right font-medium">Энергия кВтч</th>
                    <th className="p-2 text-right font-medium">Выручка ₽</th>
                    <th className="p-2 text-right font-medium">Δ к пред.</th>
                    <th className="p-2 text-right font-medium">₽/кВтч</th>
                    <th className="p-2 text-right font-medium">Станций</th>
                  </tr>
                </thead>
                <tbody>
                  {d.months.map((m) => (
                    <tr key={m.month} className="border-b border-border/30 last:border-0">
                      <td className="p-2 font-medium">
                        {monthLabel(m.month)}
                        {m.partial && (
                          <span className="ml-1.5 text-[10px] text-muted-foreground"
                            title={`Период покрывает ${m.days_covered} из ${m.days_in_month} дней месяца — с полными месяцами не сравнивать`}>
                            неполный ({m.days_covered}/{m.days_in_month} дн.)
                          </span>
                        )}
                      </td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{nf(m.sessions)}</td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{nf(m.energy_kwh)}</td>
                      <td className="p-2 text-right tabular-nums">{fmtMoney(m.corp_revenue)}</td>
                      <td className={`p-2 text-right tabular-nums ${m.revenue_delta_pct == null ? 'text-muted-foreground/50'
                        : m.revenue_delta_pct < 0 ? 'text-red-400/80' : 'text-emerald-400/80'}`}>
                        {m.revenue_delta_pct == null ? '—'
                          : `${m.revenue_delta_pct > 0 ? '+' : ''}${nf(m.revenue_delta_pct, 1)}%`}
                      </td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{nf(m.avg_tariff, 2)}</td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{nf(m.stations)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {/* ── профиль потребления ── */}
      <div className="grid gap-4 md:grid-cols-2">
        <Breakdown title="Станции" rows={d.stations} empty="Нет сессий за период" />
        <Breakdown title="Регионы" rows={d.regions} empty="Регион не заполнен" />
        <Breakdown title="Коннекторы" rows={d.connectors} empty="Тип коннектора не заполнен" />
        <Breakdown title="Карты / водители" rows={d.drivers} empty="Идентификатор карты не приходит от CPO"
          note={d.drivers.length === 1 ? 'Все сессии на одном идентификаторе — CPO не разделяет карты этого клиента' : undefined} />
      </div>

      {/* режим эксплуатации: подсказка к переговорам о тарифе */}
      {(d.when.weekday + d.when.weekend) > 0 && (
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <h4 className="text-sm font-medium">Когда заряжаются <span className="text-[11px] font-normal text-muted-foreground">{tz === 'local' ? '· местное время' : '· МСК'}</span></h4>
            <TzToggle value={tz} onChange={setTz} />
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>Будни: <b className="tabular-nums text-foreground">{nf(d.when.weekday)}</b></span>
            <span>Выходные: <b className="tabular-nums text-foreground">{nf(d.when.weekend)}</b></span>
            <span className="text-muted-foreground/70">
              {d.when.weekend / (d.when.weekday + d.when.weekend) < 0.15
                ? 'рабочий парк — почти только будни'
                : d.when.weekend / (d.when.weekday + d.when.weekend) > 0.35
                ? 'эксплуатация без выходных'
                : 'смешанный режим'}
            </span>
          </div>
          <HourStrip hours={d.when.hours} />
        </section>
      )}
    </>
  )
}

function Metric({ label, value, hint, cls }: { label: string; value: string; hint?: string; cls?: string }) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums leading-tight ${cls ?? ''}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border bg-muted/20 py-6 text-center text-xs text-muted-foreground">{text}</div>
}

/** Разрез потребления: доля считается от выручки — тем же, чем меряется клиент. */
function Breakdown({ title, rows, empty, note }: { title: string; rows: CorpBreakdown[]; empty: string; note?: string }) {
  const total = rows.reduce((s, r) => s + r.corp_revenue, 0)
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{title}</h4>
      {rows.length === 0 ? <Empty text={empty} /> : (
        <div className="space-y-1.5">
          {rows.map((r) => (
            <div key={r.label} className="space-y-0.5">
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="truncate">{r.label}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {nf(r.sessions)} сес. · {fmtMoney(r.corp_revenue)} ₽
                </span>
              </div>
              <div className="h-1 rounded-full bg-muted">
                <div className="h-1 rounded-full bg-primary/60"
                  style={{ width: `${total ? Math.max(1, (r.corp_revenue / total) * 100) : 0}%` }} />
              </div>
            </div>
          ))}
          {note && <p className="pt-0.5 text-[11px] text-muted-foreground">{note}</p>}
        </div>
      )}
    </section>
  )
}

/** Сутки одной полосой: 24 колонки, высота — доля сессий часа. */
function HourStrip({ hours }: { hours: { hour: number; sessions: number }[] }) {
  const by = new Map(hours.map((h) => [h.hour, h.sessions]))
  const max = Math.max(1, ...hours.map((h) => h.sessions))
  return (
    <div className="flex items-end gap-px" style={{ height: 44 }}>
      {Array.from({ length: 24 }, (_, h) => {
        const v = by.get(h) ?? 0
        return (
          <div key={h} className="flex-1 rounded-sm bg-primary/50" title={`${h}:00 — ${nf(v)} сессий`}
            style={{ height: `${Math.max(2, (v / max) * 100)}%`, opacity: v ? 1 : 0.25 }} />
        )
      })}
    </div>
  )
}
