/**
 * Разделы «Пульса» кроме экрана дня (ecosystem-deploy/docs/PULSE.md §3):
 * «Бизнес» — картина для куратора, «Команда» — у кого затор, «Неделя» — дайджест.
 *
 * Читают готовые витрины и ничего не считают сами. Примитивы — общие (`parts.tsx`
 * поверх `Card`/`Badge` пространства), словарь стадий проекта — один на продукт
 * (`services/sitesService.STAGE_META`), чтобы «Проработка» не стала «Проверкой
 * участка» только потому, что экран другой.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowDownRight, ArrowUpRight, Building2, CalendarDays, MessageCircle, TrendingUp, Users,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { STAGE_META, type SiteStage } from '@/services/sitesService'
import {
  getPulseBusiness, getPulseTeam, getPulseWeek, type PulsePerson,
} from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, fmtDate, plural } from './parts'

/** Имя стадии — из общего словаря продукта; чужой код показываем как есть. */
const stageLabel = (code: string) => STAGE_META[code as SiteStage]?.label ?? code

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

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
      {children}
    </h2>
  )
}

/* ── «Бизнес»: как идут дела вообще ───────────────────────────────────── */

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
    <div className="space-y-5">
      <Title icon={TrendingUp} title="Бизнес"
        hint="В каком состоянии дело: сеть зарабатывает, сеть растёт" />
      {q.isLoading && <PulseLoading what="картины бизнеса" />}
      {q.isError && <PulseError what="картину бизнеса" onRetry={() => q.refetch()} />}

      {d && (
        <>
          <section className="space-y-2">
            <SectionTitle>Сеть и продажи · за 30 дней</SectionTitle>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
              {d.net.map((k) => <KpiTile key={k.key} k={k} />)}
            </div>
            {d.trend.length > 1 && (
              <Card className="py-0">
                <CardContent className="p-3">
                  <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                    Выручка по месяцам
                  </div>
                  {/* Высота столбца в пикселях: у колонки внутри flex нет собственной
                      высоты, и процент разворачивался в ноль. */}
                  <div className="flex h-28 items-end gap-1.5">
                    {d.trend.map((t) => (
                      <div key={t.month}
                        className="flex flex-1 flex-col items-center justify-end gap-1"
                        title={`${t.month}: ${fmtNum(t.revenue, '₽')}`}>
                        <span className="text-[10px] tabular-nums text-muted-foreground">
                          {fmtNum(t.revenue)}
                        </span>
                        <div className="w-full rounded-t bg-primary/70"
                          style={{ height: `${Math.max(3, Math.round((t.revenue / maxTrend) * 80))}px` }} />
                        <span className="text-[10px] text-muted-foreground">
                          {t.month.slice(0, 2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </section>

          <section className="space-y-2">
            <SectionTitle>Развитие сети</SectionTitle>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
              <KpiTile k={{ key: 'portfolio', title: 'Площадок в портфеле',
                value: d.development.portfolio, unit: null, delta_pct: null, note: null,
                state: null, link: null, higher_is_better: true }} />
              <KpiTile k={{ key: 'comm90', title: 'Введено за 90 дней',
                value: d.development.commissioned_90d, unit: null, delta_pct: null,
                note: `всего введено: ${d.development.commissioned_total}`,
                state: null, link: null, higher_is_better: true }} />
            </div>
            {/* Воронка: где стоит поток новых станций — от разговора до ввода. */}
            <Card className="py-0">
              <CardContent className="space-y-1.5 p-3">
                {/* На телефоне подпись стадии занимала половину строки, и трек
                    сжимался до нечитаемых 70 px — там она уезжает над полосой. */}
                {d.funnel.map((f) => (
                  <div key={f.stage}
                    className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
                    <span className="truncate text-xs text-muted-foreground sm:w-40 sm:shrink-0">
                      {stageLabel(f.stage)}
                    </span>
                    <div className="flex flex-1 items-center gap-2">
                      <div className="h-3 flex-1 rounded bg-muted ring-1 ring-inset ring-border">
                        <div className="h-3 rounded bg-primary/60"
                          style={{ width: `${(f.count / maxFunnel) * 100}%` }} />
                      </div>
                      <span className="w-10 shrink-0 text-right text-xs font-medium tabular-nums">
                        {f.count}
                      </span>
                    </div>
                  </div>
                ))}
                {!d.funnel.length && (
                  <div className="text-xs text-muted-foreground">Проектов в работе пока нет.</div>
                )}
              </CardContent>
            </Card>
          </section>

          {d.events.length > 0 && (
            <section className="space-y-2">
              <SectionTitle>Что сдвинулось</SectionTitle>
              <Card className="py-0">
                <CardContent className="space-y-1.5 p-3">
                  {d.events.map((e, i) => (
                    <div key={i} className="flex gap-2 text-xs">
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {fmtDate(e.at)}
                      </span>
                      {/* title: строка обрезается, а прочитать её целиком надо. */}
                      <span className="truncate" title={e.text}>{e.text}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </section>
          )}
        </>
      )}
    </div>
  )
}

/* ── «Команда»: у кого затор ──────────────────────────────────────────── */

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
  // Сортировка отвечает на вопрос экрана: сверху те, у кого работа горит.
  const people = [...(d?.people ?? [])].sort((a, b) =>
    b.breached - a.breached || b.open - a.open)

  return (
    <div className="space-y-5">
      <Title icon={Users} title="Команда"
        hint="У кого затор: нагрузка по заявкам и кто давно не заходил" />
      {q.isLoading && <PulseLoading what="команды" />}
      {q.isError && <PulseError what="состав команды" onRetry={() => q.refetch()} />}

      {d && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <KpiTile k={{ key: 'total', title: 'Людей в пространстве', value: d.people.length,
              unit: null, delta_pct: null, note: null, state: null, link: null, higher_is_better: true }} />
            <KpiTile k={{ key: 'week', title: 'Заходили за неделю', value: week,
              unit: null, delta_pct: null, note: `из ${d.people.length}`, state: null,
              link: null, higher_is_better: true }} />
            <KpiTile k={{ key: 'loaded', title: 'С заявками в работе', value: loaded,
              unit: null, delta_pct: null, note: 'на ком висит работа', state: null,
              link: null, higher_is_better: true }} />
            <KpiTile k={{ key: 'nodept', title: 'Вне штатной структуры', value: noDept,
              unit: null, delta_pct: null,
              note: noDept ? 'эскалировать не через кого' : null,
              state: noDept ? 'warn' : null, link: null, higher_is_better: false }} />
          </div>

          {d.departments.length > 0 && (
            <section className="space-y-2">
              <SectionTitle>Подразделения</SectionTitle>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {d.departments.map((dep) => (
                  <Card key={dep.name} className="py-0">
                    <CardContent className="p-3">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <Building2 className="h-3.5 w-3.5 text-muted-foreground" />{dep.name}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {dep.head
                          ? `руководитель: ${dep.head}`
                          : 'руководитель не назначен — эскалировать некому'}
                        {` · людей: ${dep.people}`}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-2">
            <SectionTitle>
              Люди · {d.people.length} {plural(d.people.length, 'человек', 'человека', 'человек')}
            </SectionTitle>
            <Card className="py-0">
              <CardContent className="divide-y p-0">
                {people.map((p) => (
                  <div key={p.email} className="flex items-center gap-3 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 truncate text-[13px]">
                        {p.name}
                        {p.is_head && (
                          <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">
                            руководитель
                          </Badge>
                        )}
                        {p.party === 'partner' && (
                          <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">
                            внешний
                          </Badge>
                        )}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {p.department ?? 'вне штатной структуры'} · {seen(p)}
                      </div>
                    </div>
                    {/* Нагрузка: ради неё экран и открыт. Ноль не прячем — «свободен» тоже ответ. */}
                    <div className="shrink-0 text-right">
                      <div className={cn('text-sm font-semibold tabular-nums',
                        p.breached && 'text-amber-600 dark:text-amber-400')}>
                        {p.open}
                      </div>
                      <div className="text-[10px] text-muted-foreground">
                        {p.breached ? `просрочено ${p.breached}` : 'заявок'}
                      </div>
                    </div>
                    <Button size="sm" variant="ghost" className="h-8 w-8 p-0"
                      aria-label={`Написать: ${p.name}`} onClick={() => navigate('/messages')}>
                      <MessageCircle className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          </section>
        </>
      )}
    </div>
  )
}

/* ── «Неделя»: дайджест ───────────────────────────────────────────────── */

export function PulseWeekPage() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-week', company.id],
    queryFn: () => getPulseWeek(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data

  return (
    <div className="space-y-5">
      <Title icon={CalendarDays} title="Неделя"
        hint="Как прошли последние семь дней против предыдущих" />
      {q.isLoading && <PulseLoading what="итогов недели" />}
      {q.isError && <PulseError what="итоги недели" onRetry={() => q.refetch()} />}

      {d && (
        <>
          <Card className="py-0">
            <CardContent className="divide-y p-0">
              {d.rows.map((r) => {
                const delta = r.prev ? Math.round(((r.value - r.prev) / r.prev) * 1000) / 10 : null
                // Полярность приходит с сервера: рост потока заявок победой не считаем.
                const good = delta == null ? null
                  : (r.higher_is_better === false ? delta < 0 : delta >= 0)
                return (
                  <div key={r.label} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <span className="text-sm">{r.label}</span>
                    <div className="flex items-baseline gap-2">
                      <span className="whitespace-nowrap text-base font-semibold tabular-nums">
                        {fmtNum(r.value, r.unit)}
                      </span>
                      {delta != null && Math.abs(delta) <= 500 && (
                        <span className={cn('flex items-center text-[11px] tabular-nums',
                          good ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-red-600 dark:text-red-400')}>
                          {delta >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                          {Math.abs(delta)}%
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </CardContent>
          </Card>

          <section className="space-y-2">
            <SectionTitle>Что сдвинулось за неделю</SectionTitle>
            {d.highlights.length ? (
              <Card className="py-0">
                <CardContent className="space-y-1.5 p-3">
                  {d.highlights.map((h, i) => (
                    <div key={i} className="flex gap-2 text-xs">
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {fmtDate(h.at)}
                      </span>
                      <span className="truncate" title={h.text}>{h.text}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            ) : (
              <Card className="border-dashed py-0">
                <CardContent className="p-4 text-xs text-muted-foreground">
                  За неделю движений по проектам не было.
                </CardContent>
              </Card>
            )}
          </section>
        </>
      )}
    </div>
  )
}
