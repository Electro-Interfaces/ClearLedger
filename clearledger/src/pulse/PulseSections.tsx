/**
 * Разделы «Пульса» кроме экрана дня (ecosystem-deploy/docs/PULSE.md §3):
 * «Бизнес» — картина для куратора, «Команда» — у кого затор, «Неделя» — дайджест.
 *
 * Все три читают готовые витрины и ничего не считают сами. Подача одинаковая:
 * крупная цифра, подпись словами, сравнение с прошлым периодом.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowDownRight, ArrowUpRight, Building2, Loader2, MessageCircle, TrendingUp, Users,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getPulseBusiness, getPulseTeam, getPulseWeek,
  type PulseKpi, type PulsePerson,
} from './pulseService'

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nfShort = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })

const fmt = (v: number | null, unit?: string | null) => {
  if (v == null) return '—'
  const s = (Math.abs(v) >= 100_000 ? nfShort : nf).format(v)
  return unit ? `${s} ${unit}` : s
}

const dt = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) : '—'

/** Стадии проекта по-русски: коды в интерфейсе руководителя — это брак. */
const STAGE_LABEL: Record<string, string> = {
  lead: 'Первичный контакт', screening: 'Скрининг', negotiation: 'Переговоры',
  dd: 'Проверка участка', decision: 'Решение', contracting: 'Контрактование',
  construction: 'Стройка', commissioning: 'Ввод', live: 'В эксплуатации',
  hold: 'Пауза', archive: 'Архив',
}

function Loading() {
  return (
    <div className="flex justify-center py-12">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  )
}

function Title({ icon: Icon, title, hint }: {
  icon: typeof Users; title: string; hint: string
}) {
  return (
    <div>
      <h1 className="flex items-center gap-2 text-lg font-semibold">
        <Icon className="h-5 w-5 text-primary" />{title}
      </h1>
      <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function KpiCard({ k }: { k: PulseKpi }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-[11px] text-muted-foreground">{k.title}</div>
      <div className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5">
        <span className="whitespace-nowrap text-xl font-bold tabular-nums">
          {fmt(k.value, k.unit)}
        </span>
        {k.delta_pct != null && (
          <span className={cn('flex items-center text-[11px] font-medium tabular-nums',
            k.delta_pct >= 0 ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-red-600 dark:text-red-400')}>
            {k.delta_pct >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(k.delta_pct)}%
          </span>
        )}
      </div>
      {k.note && <div className="mt-0.5 text-[11px] text-muted-foreground">{k.note}</div>}
    </div>
  )
}

/* ── «Бизнес» ─────────────────────────────────────────────────────────── */

export function PulseBusinessPage() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-business', company.id],
    queryFn: () => getPulseBusiness(company.id),
    refetchInterval: 5 * 60_000,
  })
  const d = q.data
  const maxTrend = Math.max(1, ...(d?.trend ?? []).map((t) => t.revenue))
  const maxFunnel = Math.max(1, ...(d?.funnel ?? []).map((f) => f.count))

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4">
      <Title icon={TrendingUp} title="Бизнес"
        hint="В каком состоянии дело: сеть зарабатывает, сеть растёт" />
      {q.isLoading && <Loading />}
      {d && (
        <>
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Сеть и продажи · за 30 дней
            </h2>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {d.net.map((k) => <KpiCard key={k.key} k={k} />)}
            </div>
            {/* Помесячно: форма кривой отвечает на «растём или стоим» быстрее таблицы. */}
            {d.trend.length > 1 && (
              <div className="rounded-lg border p-3">
                <div className="mb-2 text-[11px] text-muted-foreground">Выручка по месяцам</div>
                {/* Высота столбца в пикселях, а не в %: у колонки внутри flex нет
                    собственной высоты, и процент разворачивался в ноль. */}
                <div className="flex h-28 items-end gap-1.5">
                  {d.trend.map((t) => (
                    <div key={t.month} className="flex flex-1 flex-col items-center justify-end gap-1"
                      title={`${t.month}: ${fmt(t.revenue, '₽')}`}>
                      <span className="text-[10px] tabular-nums text-muted-foreground">
                        {nfShort.format(t.revenue)}
                      </span>
                      <div className="w-full rounded-t bg-primary/70"
                        style={{ height: `${Math.max(3, Math.round((t.revenue / maxTrend) * 80))}px` }} />
                      <span className="text-[10px] text-muted-foreground">{t.month.slice(0, 2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Развитие сети
            </h2>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              <KpiCard k={{ key: 'portfolio', title: 'Площадок в портфеле', value: d.development.portfolio,
                unit: null, delta_pct: null, note: null, state: null }} />
              <KpiCard k={{ key: 'comm90', title: 'Введено за 90 дней', value: d.development.commissioned_90d,
                unit: null, delta_pct: null, note: `всего введено: ${d.development.commissioned_total}`, state: null }} />
            </div>
            {/* Воронка: где стоит поток новых станций — от разговора до ввода. */}
            <div className="space-y-1.5 rounded-lg border p-3">
              {d.funnel.map((f) => (
                <div key={f.stage} className="flex items-center gap-2">
                  <span className="w-40 shrink-0 truncate text-xs text-muted-foreground">
                    {STAGE_LABEL[f.stage] ?? f.stage}
                  </span>
                  <div className="h-3 flex-1 rounded bg-muted">
                    <div className="h-3 rounded bg-primary/60"
                      style={{ width: `${(f.count / maxFunnel) * 100}%` }} />
                  </div>
                  <span className="w-10 shrink-0 text-right text-xs font-medium tabular-nums">{f.count}</span>
                </div>
              ))}
              {!d.funnel.length && (
                <div className="text-xs text-muted-foreground">Проектов в работе пока нет.</div>
              )}
            </div>
          </section>

          {d.events.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Что сдвинулось
              </h2>
              <ul className="space-y-1.5 rounded-lg border p-3">
                {d.events.map((e, i) => (
                  <li key={i} className="flex gap-2 text-xs">
                    <span className="shrink-0 text-muted-foreground tabular-nums">{dt(e.at)}</span>
                    <span className="truncate">{e.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

/* ── «Команда» ────────────────────────────────────────────────────────── */

export function PulseTeamPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['pulse-team', company.id],
    queryFn: () => getPulseTeam(company.id),
    refetchInterval: 2 * 60_000,
  })
  const d = q.data

  const seen = (p: PulsePerson) => {
    if (!p.last_seen) return 'ни разу не заходил'
    const days = Math.floor((Date.now() - new Date(p.last_seen).getTime()) / 86_400_000)
    if (days <= 0) return 'был сегодня'
    if (days === 1) return 'был вчера'
    return `был ${days} дн назад`
  }
  const week = d?.people.filter((p) => p.last_seen
    && Date.now() - new Date(p.last_seen).getTime() < 7 * 86_400_000).length ?? 0
  const noDept = d?.people.filter((p) => !p.department).length ?? 0
  const loaded = d?.people.filter((p) => p.open > 0).length ?? 0

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4">
      <Title icon={Users} title="Команда"
        hint="У кого затор: нагрузка по заявкам и кто давно не заходил" />
      {q.isLoading && <Loading />}
      {d && (
        <>
          {/* Сводка первой строкой: у кого работа и все ли на месте — до списка имён. */}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <KpiCard k={{ key: 'total', title: 'Людей в пространстве', value: d.people.length,
              unit: null, delta_pct: null, note: null, state: null }} />
            <KpiCard k={{ key: 'week', title: 'Заходили за неделю', value: week,
              unit: null, delta_pct: null, note: `из ${d.people.length}`, state: null }} />
            <KpiCard k={{ key: 'loaded', title: 'С заявками в работе', value: loaded,
              unit: null, delta_pct: null, note: 'на ком висит работа', state: null }} />
            <KpiCard k={{ key: 'nodept', title: 'Вне штатной структуры', value: noDept,
              unit: null, delta_pct: null,
              note: noDept ? 'эскалировать не через кого' : null,
              state: noDept ? 'warn' : null }} />
          </div>

          {d.departments.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Подразделения
              </h2>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {d.departments.map((dep) => (
                  <div key={dep.name} className="rounded-lg border p-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Building2 className="h-3.5 w-3.5 text-muted-foreground" />{dep.name}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {dep.head
                        ? `руководитель: ${dep.head}`
                        : 'руководитель не назначен — эскалировать некому'}
                      {` · людей: ${dep.people}`}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Люди · {d.people.length}
            </h2>
            <div className="divide-y rounded-lg border">
              {d.people.map((p) => (
                <div key={p.email} className="flex items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 truncate text-[13px]">
                      {p.name}
                      {p.is_head && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          руководитель
                        </span>
                      )}
                      {p.party === 'partner' && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          внешний
                        </span>
                      )}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {p.department ?? 'вне штатной структуры'} · {seen(p)}
                    </div>
                  </div>
                  {/* Нагрузка: то, ради чего экран и открыт. Ноль не прячем — «не занят» тоже ответ. */}
                  <div className="shrink-0 text-right">
                    <div className={cn('text-sm font-semibold tabular-nums',
                      p.breached && 'text-amber-600 dark:text-amber-400')}>
                      {p.open}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {p.breached ? `просрочено ${p.breached}` : 'заявок'}
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]"
                    title="Написать" onClick={() => navigate('/messages')}>
                    <MessageCircle className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}

/* ── «Неделя» ─────────────────────────────────────────────────────────── */

export function PulseWeekPage() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-week', company.id],
    queryFn: () => getPulseWeek(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4">
      <Title icon={TrendingUp} title="Неделя"
        hint="Как прошли последние семь дней против предыдущих" />
      {q.isLoading && <Loading />}
      {d && (
        <>
          <div className="divide-y rounded-lg border">
            {d.rows.map((r) => {
              const delta = r.prev ? Math.round(((r.value - r.prev) / r.prev) * 1000) / 10 : null
              return (
                <div key={r.label} className="flex items-center justify-between gap-3 p-3">
                  <span className="text-sm">{r.label}</span>
                  <div className="flex items-baseline gap-2">
                    <span className="whitespace-nowrap text-base font-semibold tabular-nums">
                      {fmt(r.value, r.unit)}
                    </span>
                    {delta != null && (
                      <span className={cn('flex items-center text-[11px] tabular-nums',
                        delta >= 0 ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-red-600 dark:text-red-400')}>
                        {delta >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                        {Math.abs(delta)}%
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Что сдвинулось за неделю
            </h2>
            {d.highlights.length ? (
              <ul className="space-y-1.5 rounded-lg border p-3">
                {d.highlights.map((h, i) => (
                  <li key={i} className="flex gap-2 text-xs">
                    <span className="shrink-0 text-muted-foreground tabular-nums">{dt(h.at)}</span>
                    <span className="truncate">{h.text}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                За неделю движений по проектам не было.
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
