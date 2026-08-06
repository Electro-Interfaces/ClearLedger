/**
 * «Пульс» → «Бизнес» → «Задачи»: работа компании глазами руководителя.
 *
 * Приложение «Задачи» отвечает исполнителю («что на мне») и постановщику («где
 * мяч»). Здесь три других вопроса: успевает ли компания вообще, у кого затор и
 * что уже горит. Поэтому не второй реестр, а разрезы — по людям, типам и
 * объектам, каждый со входом в реестр с готовым отбором.
 *
 * Цифры берём той же ручкой, что и «Обзор» приложения (`/api/tasks/summary`):
 * «Пульс» переиспользует смысл, а не заводит второй набор метрик — иначе
 * руководитель и исполнитель увидят разные числа про одну работу.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useTasksApp } from '@/hooks/useTasksApp'
import * as tasksService from '@/services/tasksService'
import type { TasksCut } from '@/services/tasksService'
import type { PulseKpi } from './pulseService'
import { KpiTile, PulseError, PulseLoading } from './parts'

/** Разрез в «Пульсе» показывает затор, поэтому строки — по числу просрочек,
 *  а не по объёму работы: «у кого больше всех задач» руководителю не вопрос. */
function byStuck(rows: TasksCut[]): TasksCut[] {
  return [...rows].sort((a, b) => (b.overdue - a.overdue) || (b.open - a.open)).slice(0, 8)
}

export function TasksView() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const enabled = useTasksApp()
  const q = useQuery({
    queryKey: ['pulse-tasks', company.id],
    queryFn: () => tasksService.tasksSummary(company.id, 30),
    enabled,
    refetchInterval: 10 * 60_000,
  })

  if (!enabled) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Продукт «Задачи» компании не подключён — работа ведётся вне системы.
        </CardContent>
      </Card>
    )
  }
  if (q.isLoading) return <PulseLoading what="работы компании" />
  if (q.isError) return <PulseError what="работу компании" onRetry={() => q.refetch()} />
  const s = q.data
  if (!s) return null

  if (!s.totals.open && !s.totals.done) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Задач в работе нет и за месяц не закрывали. Либо работа ещё не заведена в
          систему, либо у компании сейчас нет активных поручений.
        </CardContent>
      </Card>
    )
  }

  // Ссылка из цифры несёт отбор: переход на корень продукта — невыполненное обещание.
  const go = (params: Record<string, string>) =>
    navigate(`/tasks/company?${new URLSearchParams({ view: 'registry', ...params })}`)

  // `higher_is_better: false` там, где рост — это ухудшение: просрочки,
  // бесхозные задачи и средний срок зелёными быть не должны.
  const kpi: PulseKpi[] = [
    {
      key: 'open', title: 'В работе', value: s.totals.open, unit: null,
      delta_pct: null, note: null, state: null, link: null, higher_is_better: true,
    },
    {
      key: 'overdue', title: 'Просрочено', value: s.totals.overdue, unit: null,
      delta_pct: null, state: s.totals.overdue > 0 ? 'warn' : null, link: null,
      note: s.totals.overdue ? 'срок прошёл, работа стоит' : null,
      higher_is_better: false,
    },
    {
      key: 'unassigned', title: 'Без исполнителя', value: s.totals.unassigned, unit: null,
      delta_pct: null, state: s.totals.unassigned > 0 ? 'warn' : null, link: null,
      note: s.totals.unassigned ? 'поставлены, но ни у кого не в руках' : null,
      higher_is_better: false,
    },
    {
      key: 'created', title: 'Поставлено за месяц', value: s.totals.created, unit: null,
      delta_pct: null, note: null, state: null, link: null, higher_is_better: true,
    },
    {
      key: 'done', title: 'Закрыто за месяц', value: s.totals.done, unit: null,
      delta_pct: null, note: null, state: null, link: null, higher_is_better: true,
    },
    {
      key: 'avg', title: 'Средний срок', value: s.totals.avg_days, unit: 'дн',
      delta_pct: null, note: 'от постановки до закрытия', state: null, link: null,
      higher_is_better: false,
    },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {kpi.map((k) => (
          <KpiTile key={k.key} k={k}
            onOpen={k.key === 'overdue' ? () => go({ scope: 'overdue' })
              : k.key === 'unassigned' ? () => go({ assignee: '' })
                : () => go({})} />
        ))}
      </div>

      <Cut title="У кого затор" rows={byStuck(s.by_assignee)}
        empty="Работа ни на ком не висит."
        onOpen={(r) => (r.id ? go({ assignee: r.id }) : go({}))} />

      <Cut title="По каким типам копится" rows={byStuck(s.by_type)}
        empty="Типы не заведены — вся работа идёт поручениями."
        onOpen={(r) => (r.id ? go({ type: r.id }) : go({}))} />

      {s.by_object.length > 0 && (
        <Cut title="На каких объектах" rows={byStuck(s.by_object)}
          empty="К объектам работа не привязана."
          onOpen={(r) => (r.id ? go({ object: r.id }) : go({}))} />
      )}

      <a href="/tasks/company?view=registry"
        className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Весь реестр задач <ArrowUpRight className="h-3 w-3" />
      </a>
    </div>
  )
}

function Cut({ title, rows, empty, onOpen }: {
  title: string; rows: TasksCut[]; empty: string; onOpen: (r: TasksCut) => void
}) {
  const max = Math.max(1, ...rows.map((r) => r.open))
  return (
    <section className="space-y-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
        {title}
      </h2>
      {rows.length === 0 ? (
        <Card className="border-dashed py-0">
          <CardContent className="p-3 text-xs text-muted-foreground">{empty}</CardContent>
        </Card>
      ) : (
        <div className="space-y-1">
          {rows.map((r) => (
            <button key={r.id ?? r.name} type="button" onClick={() => onOpen(r)}
              className="flex w-full items-center gap-3 rounded-md border px-3 py-1.5 text-left text-xs transition-colors hover:bg-accent/40">
              <span className="w-40 shrink-0 truncate font-medium">{r.name}</span>
              {/* Полоса — доля от самого нагруженного: глазом видно, где перекос. */}
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary/50"
                  style={{ width: `${Math.round((r.open / max) * 100)}%` }} />
              </span>
              <span className="w-24 shrink-0 text-right text-muted-foreground">
                {r.open} в работе
              </span>
              <span className={cn('w-24 shrink-0 text-right',
                r.overdue > 0
                  ? 'font-medium text-red-600 dark:text-red-400'
                  : 'text-muted-foreground')}>
                {r.overdue > 0 ? `${r.overdue} просрочено` : 'без просрочек'}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

export default TasksView
