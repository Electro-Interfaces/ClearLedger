/**
 * Разделы «Пульса» кроме экрана дня (ecosystem-deploy/docs/PULSE.md §3):
 * «Бизнес» — картина для куратора, «Команда» — у кого затор, «Неделя» — дайджест.
 *
 * Читают готовые витрины и ничего не считают сами. Примитивы — общие (`parts.tsx`
 * поверх `Card`/`Badge` пространства), словарь стадий проекта — один на продукт
 * (`services/sitesService.STAGE_META`), чтобы «Проработка» не стала «Проверкой
 * участка» только потому, что экран другой.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowDownRight, ArrowUpRight, Building2, CalendarDays, ChevronRight, ClipboardList,
  Gauge, HardHat, LifeBuoy, MessageCircle, TrendingUp, Users,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { STAGE_META, type SiteStage } from '@/services/sitesService'
// Витрины продуктов — as is: «Пульс» показывает чужой экран, а не свою копию.
import { OverviewDashboardPanel } from '@/components/workspace/OverviewDashboardPanel'
import { ProjectsPortfolioPanel } from '@/components/sites/ProjectsPortfolioPanel'
import { OpsOverviewVitrine } from '@/components/balance/OpsCockpit'
import { AnalyticsSection as TicketsAnalyticsSection } from '@/pages/TicketsAppPage'
import { useFilters } from '@/contexts/FilterContext'
import {
  getPulseBusiness, getPulsePerson, getPulseTeam, getPulseWeek, type PulsePerson,
} from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, fmtDate, plural } from './parts'
import { usePulseView } from './PulseLayout'

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
  const view = usePulseView('/pulse/business')
  // Период берём общий, из контура пространства: у руководителя та же рамка
  // времени, что у коммерсанта, — иначе цифры «Пульса» и «Продаж» разойдутся.
  const { period } = useFilters()
  const q = useQuery({
    queryKey: ['pulse-business', company.id],
    queryFn: () => getPulseBusiness(company.id),
    refetchInterval: 5 * 60_000,
  })
  const d = q.data
  const maxTrend = Math.max(1, ...(d?.trend ?? []).map((t) => t.revenue))
  const maxFunnel = Math.max(1, ...(d?.funnel ?? []).map((f) => f.count))
  // Заголовок экрана = имя пункта (SPACE.md §4): человек видит, где он.
  const meta = {
    sales: { title: 'Продажи', hint: 'Обзор сети — та же витрина, что в приложении «Продажи»' },
    projects: { title: 'Проекты', hint: 'Портфель стройки — витрина приложения «Проекты»' },
    ops: { title: 'Эксплуатация', hint: 'Состояние сети и баланс — витрина «Эксплуатации»' },
    support: { title: 'Поддержка', hint: 'Сервисный контур: сколько и где стоит работа' },
    summary: { title: 'Коротко', hint: 'Выжимка для куратора: цифры сети, воронка и вехи' },
  }[view] ?? { title: 'Бизнес', hint: 'В каком состоянии дело' }

  // Витрины продуктов открываются КАК ЕСТЬ: свою копию «Пульс» не рисует.
  if (view === 'sales') {
    return (
      <div className="space-y-4">
        <Title icon={TrendingUp} title={meta.title} hint={meta.hint} />
        <OverviewDashboardPanel companyId={company.id}
          dateFrom={period.from} dateTo={period.to} />
      </div>
    )
  }
  if (view === 'projects') {
    return (
      <div className="space-y-4">
        <Title icon={HardHat} title={meta.title} hint={meta.hint} />
        <ProjectsPortfolioPanel companyId={company.id} />
      </div>
    )
  }
  if (view === 'ops') {
    return (
      <div className="space-y-4">
        <Title icon={Gauge} title={meta.title} hint={meta.hint} />
        <OpsOverviewVitrine />
      </div>
    )
  }
  if (view === 'support') {
    return (
      <div className="space-y-4">
        <Title icon={LifeBuoy} title={meta.title} hint={meta.hint} />
        <TicketsAnalyticsSection companyId={company.id} />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <Title icon={TrendingUp} title={meta.title} hint={meta.hint} />
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
        </>
      )}

      {d && (
        <>
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
        </>
      )}

      {d && (
        <>
          {d.events.length > 0 ? (
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
          ) : (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                Событий по проектам пока нет.
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

/* ── «Команда»: у кого затор ──────────────────────────────────────────── */

export function PulseTeamPage() {
  const { company } = useCompany()
  const view = usePulseView('/pulse/team')
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

  const meta = view === 'departments'
    ? { title: 'Подразделения', hint: 'Штатная структура: кто кому подчиняется и куда эскалировать' }
    : { title: 'Люди', hint: 'У кого затор: нагрузка по заявкам и кто давно не заходил' }

  return (
    <div className="space-y-5">
      <Title icon={Users} title={meta.title} hint={meta.hint} />
      {q.isLoading && <PulseLoading what="команды" />}
      {q.isError && <PulseError what="состав команды" onRetry={() => q.refetch()} />}

      {d && view === 'people' && (
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

          <section className="space-y-2">
            <SectionTitle>
              Люди · {d.people.length} {plural(d.people.length, 'человек', 'человека', 'человек')}
            </SectionTitle>
            <PeopleList people={people} seen={seen} companyId={company.id} />
          </section>
        </>
      )}

      {d && view === 'departments' && (
        <>
          {d.departments.length > 0 ? (
            <section className="space-y-2">
              <SectionTitle>Структура компании</SectionTitle>
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
          ) : (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                Подразделения не заведены. Штатная структура ведётся в
                «Управление → Сотрудники» — без неё эскалация не знает, к кому идти.
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

/* ── «Неделя»: дайджест ───────────────────────────────────────────────── */

export function PulseWeekPage() {
  const { company } = useCompany()
  const view = usePulseView('/pulse/week')
  const q = useQuery({
    queryKey: ['pulse-week', company.id],
    queryFn: () => getPulseWeek(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data
  const meta = view === 'moves'
    ? { title: 'Движения', hint: 'Что сдвинулось по проектам за семь дней' }
    : { title: 'Итоги недели', hint: 'Как прошли последние семь дней против предыдущих' }

  return (
    <div className="space-y-5">
      <Title icon={CalendarDays} title={meta.title} hint={meta.hint} />
      {q.isLoading && <PulseLoading what="итогов недели" />}
      {q.isError && <PulseError what="итоги недели" onRetry={() => q.refetch()} />}

      {d && view === 'totals' && (
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
        </>
      )}

      {d && view === 'moves' && (
        <>
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

/**
 * Люди с разрезом по ВСЕМ приложениям пространства (постановка МАГа 31.07.2026):
 * штатное место, заявки, проекты, чаты, действия. Строка разворачивается в карточку —
 * руководитель видит не только счётчики, но и что именно у человека в работе.
 */
function PeopleList({ people, seen, companyId }: {
  people: PulsePerson[]; seen: (p: PulsePerson) => string; companyId: string
}) {
  // Карточка открывается модальным окном поверх списка (решение МАГа 31.07.2026):
  // разворот строки уводил список вниз, а руководителю нужно рассмотреть человека,
  // не теряя строя остальных и не листая экран.
  const [openId, setOpenId] = useState<string | null>(null)
  const selected = people.find((p) => p.id === openId) ?? null
  return (
    <Card className="py-0">
      <CardContent className="divide-y p-0">
        {/* Шапка колонок — только на широком экране: на телефоне цифры подписаны. */}
        <div className="hidden items-center gap-3 px-3 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60 md:flex">
          <span className="flex-1">Человек</span>
          <span className="w-24 text-right">Заявки</span>
          <span className="w-24 text-right">Проекты</span>
          <span className="w-20 text-right">Активность</span>
          <span className="w-8" />
        </div>

        {people.map((p) => {
          return (
            <div key={p.email}>
              <button type="button"
                onClick={() => setOpenId(p.id)}
                title={`Открыть карточку: ${p.name}`}
                className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-accent/40">
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
                    {[p.position, p.department ?? 'вне штатной структуры', seen(p)]
                      .filter(Boolean).join(' · ')}
                  </div>
                </div>

                {/* Заявки: сколько на человеке и сколько из них горит. */}
                <div className="w-24 shrink-0 text-right">
                  <span className={cn('text-sm font-semibold tabular-nums',
                    p.breached && 'text-amber-600 dark:text-amber-400')}>{p.open}</span>
                  <div className="text-[10px] text-muted-foreground">
                    {p.breached ? `просрочено ${p.breached}` : 'в работе'}
                  </div>
                </div>

                {/* Проекты: ведёт и сколько реально правил за месяц. */}
                <div className="w-24 shrink-0 text-right">
                  <span className="text-sm font-semibold tabular-nums">{p.projects_owned}</span>
                  <div className="text-[10px] text-muted-foreground">
                    {p.project_edits_30d ? `${fmtNum(p.project_edits_30d)} правок` : 'ведёт'}
                  </div>
                </div>

                {/* Активность в пространстве: действия журнала и участие в чатах. */}
                <div className="hidden w-20 shrink-0 text-right md:block">
                  <span className="text-sm font-semibold tabular-nums">{p.actions_30d}</span>
                  <div className="text-[10px] text-muted-foreground">
                    {p.chat_rooms} чат{p.chat_rooms === 1 ? '' : 'ов'}
                  </div>
                </div>

                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </div>
          )
        })}
      </CardContent>

      {/* Модальное окно карточки — поверх списка, с полной расшифровкой. */}
      <Dialog open={!!selected} onOpenChange={(v) => !v && setOpenId(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          {selected && (
            <PersonCard companyId={companyId} person={selected} seen={seen}
              onClose={() => setOpenId(null)} />
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}

/**
 * Карточка человека в модальном окне: кто это, чем занят и куда перейти.
 *
 * Три слоя: характеристики (штатное место и присутствие), работа (заявки,
 * проекты, чаты) и переходы. Счётчики строки здесь получают расшифровку —
 * руководителю мало «1018 правок», ему нужно, ЧТО именно человек ведёт.
 */
function PersonCard({ companyId, person, seen, onClose }: {
  companyId: string; person: PulsePerson
  seen: (p: PulsePerson) => string; onClose: () => void
}) {
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['pulse-person', companyId, person.id],
    queryFn: () => getPulsePerson(companyId, person.id),
  })
  const d = q.data
  const go = (to: string) => { onClose(); navigate(to) }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-center gap-2">
          {person.name}
          {person.is_head && (
            <Badge variant="outline" className="font-normal">руководитель</Badge>
          )}
          {person.party === 'partner' && (
            <Badge variant="outline" className="font-normal">внешний</Badge>
          )}
        </DialogTitle>
        <DialogDescription>
          {[person.position, person.department ?? 'вне штатной структуры', seen(person)]
            .filter(Boolean).join(' · ')}
        </DialogDescription>
      </DialogHeader>

      {q.isLoading && <PulseLoading what="карточки" />}
      {q.isError && <PulseError what="карточку" onRetry={() => q.refetch()} />}

      {d?.found && (
        <div className="space-y-4">
          {/* Характеристики: то, что отвечает «кто это» без листания. */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border p-3 text-xs md:grid-cols-3">
            <Field label="Почта" value={d.email} />
            <Field label="Подразделение" value={d.department ?? 'не назначено'} />
            <Field label="Руководитель"
              value={d.head ?? (person.is_head ? 'сам руководитель' : 'не назначен')} />
            <Field label="Заявок в работе"
              value={person.breached
                ? `${person.open} · просрочено ${person.breached}`
                : String(person.open)}
              tone={person.breached ? 'warn' : undefined} />
            <Field label="Ведёт проектов" value={String(person.projects_owned)} />
            <Field label="Правок в проектах"
              value={d.edits.month
                ? `${fmtNum(d.edits.week)} за неделю · ${fmtNum(d.edits.month)} за месяц`
                : 'нет'} />
            <Field label="Заявок завёл" value={String(person.authored)} />
            <Field label="Закрыл за 30 дней" value={String(person.closed_30d)} />
            <Field label="Действий в журнале" value={`${person.actions_30d} за месяц`} />
          </div>

          {d.tickets.length > 0 && (
            <Block title={`Заявки в работе · ${d.tickets.length}`}>
              {d.tickets.slice(0, 10).map((t, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  {t.breached && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500"
                      title="SLA нарушен" />
                  )}
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {t.number ?? '—'}
                  </span>
                  <span className="truncate" title={t.title}>{t.title}</span>
                  {t.object && (
                    <span className="shrink-0 text-muted-foreground">· {t.object}</span>
                  )}
                </div>
              ))}
            </Block>
          )}

          {d.projects.length > 0 && (
            <Block title={`Ведёт проекты · ${d.projects.length}`}>
              <div className="flex flex-wrap gap-1.5">
                {d.projects.slice(0, 12).map((pr, i) => (
                  <Badge key={i} variant="outline" className="font-normal">
                    {pr.title} · {stageLabel(pr.stage)}
                  </Badge>
                ))}
              </div>
            </Block>
          )}

          {d.rooms.length > 0 && (
            <Block title={`Чаты пространства · ${d.rooms.length}`}>
              <div className="flex flex-wrap gap-1.5">
                {d.rooms.slice(0, 14).map((r, i) => (
                  <Badge key={i} variant="secondary" className="font-normal">{r.name}</Badge>
                ))}
                {d.rooms.length > 14 && (
                  <span className="self-center text-[11px] text-muted-foreground">
                    и ещё {d.rooms.length - 14}
                  </span>
                )}
              </div>
            </Block>
          )}

          {d.actions.length > 0 && (
            <Block title="Последние действия">
              {d.actions.slice(0, 8).map((a, i) => (
                <div key={i} className="flex gap-2 text-[11px]">
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {fmtDate(a.at)}
                  </span>
                  <span className="truncate">{a.action}</span>
                </div>
              ))}
            </Block>
          )}

          {/* Переходы: из карточки видно не только «что», но и куда пойти дальше. */}
          <div className="flex flex-wrap gap-2 border-t pt-3">
            <Button size="sm" className="h-8" onClick={() => go('/messages')}>
              <MessageCircle className="mr-1 h-3.5 w-3.5" />Написать
            </Button>
            <Button size="sm" variant="outline" className="h-8"
              onClick={() => go('/tickets')}>
              <ClipboardList className="mr-1 h-3.5 w-3.5" />Его заявки
            </Button>
            <Button size="sm" variant="outline" className="h-8"
              onClick={() => go('/projects')}>
              <HardHat className="mr-1 h-3.5 w-3.5" />Проекты
            </Button>
            <Button size="sm" variant="ghost" className="h-8"
              onClick={() => go(`/admin/company/map?user=${person.id}`)}>
              Журнал и доступы
            </Button>
          </div>
        </div>
      )}
    </>
  )
}

/** Пара «подпись — значение» в характеристиках карточки. */
function Field({ label, value, tone }: { label: string; value: string; tone?: 'warn' }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</div>
      <div className={cn('truncate', tone === 'warn' && 'text-amber-600 dark:text-amber-400')}
        title={value}>{value}</div>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60">
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}
