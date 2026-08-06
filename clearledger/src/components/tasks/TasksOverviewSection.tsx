/**
 * «Обзор» приложения «Задачи» — то, чем приложение отличается от кнопки в шапке.
 *
 * Кнопка отвечает на «что на мне сейчас». Здесь другой вопрос: как идёт работа
 * компании — сколько в руках и сколько горит, кто чем занят, по каким типам и
 * объектам она копится и что вообще происходило за период. Цифры кликабельны:
 * каждая ведёт в «Работу» уже с фильтром, а не оставляет искать глазами.
 */
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRightLeft, CheckCircle2, MessageSquare, Plus, Route as RouteIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import type { TasksCut } from '@/services/tasksService'

const PERIODS = [7, 30, 90]

/** Значок события — словарь общий с карточкой задачи: один вид следа везде. */
const KIND_ICON: Record<string, typeof Plus> = {
  created: Plus, stage: RouteIcon, assign: ArrowRightLeft,
  status: CheckCircle2, comment: MessageSquare,
}
const KIND_TEXT: Record<string, string> = {
  created: 'поставил задачу', stage: 'перевёл', assign: 'передал',
  status: 'изменил статус', comment: 'написал',
}
const STATUS_LABEL: Record<string, string> = {
  open: 'в работе', done: 'выполнена', cancelled: 'отменена',
}

const dtT = (s: string | null) => (s ? new Date(s).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')

export function TasksOverviewSection({ companyId, days, onDays, onDrill }: {
  companyId: string
  days: number
  onDays: (d: number) => void
  /** Провал в «Работу» с фильтром: обзор — вход в список, а не отдельный мир. */
  onDrill: (f: { scope?: string; assignee?: string; type?: string; object?: string }) => void
}) {
  const q = useQuery({
    queryKey: ['tasks-summary', companyId, days],
    queryFn: () => tasksService.tasksSummary(companyId, days),
  })
  const s = q.data

  if (q.isError) return <QueryError message="Не удалось загрузить обзор" onRetry={() => void q.refetch()} />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Период:</span>
        {PERIODS.map((d) => (
          <Button key={d} size="sm" variant={d === days ? 'default' : 'outline'} className="h-7 px-2.5 text-xs"
            onClick={() => onDays(d)}>
            {d} дн
          </Button>
        ))}
        <span className="text-[11px] text-muted-foreground">
          «в работе» и «просрочено» — на сейчас, остальное — за период
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricTile label="В работе" value={s?.totals.open ?? '—'} hint="активные задачи компании"
          onClick={() => onDrill({ scope: 'open' })} />
        <MetricTile label="Просрочено" value={s?.totals.overdue ?? '—'} tone="danger"
          hint="срок прошёл, задача жива" onClick={() => onDrill({ scope: 'overdue' })} />
        <MetricTile label="На мне" value={s?.totals.mine ?? '—'} hint="я исполнитель или автор"
          onClick={() => onDrill({ scope: 'mine' })} />
        <MetricTile label="Без исполнителя" value={s?.totals.unassigned ?? '—'}
          tone={s && s.totals.unassigned > 0 ? 'warning' : undefined}
          hint="поставлена, но ни у кого не в руках" onClick={() => onDrill({ scope: 'open' })} />
        <MetricTile label="Поставлено" value={s?.totals.created ?? '—'} hint={`новых за ${days} дн`} />
        <MetricTile label="Закрыто" value={s?.totals.done ?? '—'} hint={
          s?.totals.avg_days != null ? `в среднем за ${s.totals.avg_days} дн` : `за ${days} дн`}
          onClick={() => onDrill({ scope: 'closed' })} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <CutCard title="Кто чем занят" empty="Задачи пока никому не поручены"
          rows={s?.by_assignee} loading={q.isLoading}
          onRow={(r) => r.id && onDrill({ scope: 'all', assignee: r.id })} />
        <CutCard title="По типам" empty="Типы ещё не заведены"
          rows={s?.by_type} loading={q.isLoading}
          onRow={(r) => r.id && onDrill({ scope: 'all', type: r.id })} />
        <CutCard title="По объектам" empty="Задачи не привязаны к объектам"
          rows={s?.by_object} loading={q.isLoading}
          onRow={(r) => r.id && onDrill({ scope: 'all', object: r.id })} />
      </div>

      <Card className="p-0">
        <div className="border-b px-4 py-2.5">
          <h3 className="text-sm font-medium">Что происходило</h3>
          <p className="text-[11px] text-muted-foreground">
            След работы за {days} дн: кто передал, кто двинул, кто закрыл
          </p>
        </div>
        {q.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
        ) : !s?.activity.length ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            За период ничего не происходило.
          </div>
        ) : (
          <div className="max-h-[420px] overflow-y-auto">
            {s.activity.map((e) => {
              const Icon = KIND_ICON[e.kind] ?? MessageSquare
              return (
                <button key={e.id} onClick={() => onDrill({ scope: 'all' })}
                  className="flex w-full items-start gap-2.5 border-b px-4 py-2 text-left last:border-0 hover:bg-muted/40">
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs">
                      <span className="font-medium">{e.user ?? 'система'}</span>{' '}
                      {KIND_TEXT[e.kind] ?? e.kind}
                      {e.kind === 'status' && e.to ? ` → ${STATUS_LABEL[e.to] ?? e.to}` : ''}
                      {e.kind !== 'status' && e.to ? ` → ${e.to}` : ''}
                      {' · '}
                      <span className="text-muted-foreground">№{e.number} {e.title}</span>
                    </span>
                    {e.note && <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">«{e.note}»</span>}
                  </span>
                  <span className="shrink-0 whitespace-nowrap text-[11px] text-muted-foreground">{dtT(e.created_at)}</span>
                </button>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}

/** Разрез: строка — сколько в работе, из них просрочено, и сколько закрыто. */
function CutCard({ title, rows, empty, loading, onRow }: {
  title: string; rows?: TasksCut[]; empty: string; loading: boolean
  onRow: (r: TasksCut) => void
}) {
  return (
    <Card className="p-0">
      <div className="flex items-baseline justify-between border-b px-4 py-2.5">
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="text-[11px] text-muted-foreground">в работе · просроч. · закрыто</span>
      </div>
      {loading ? (
        <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
      ) : !rows?.length ? (
        <div className="p-6 text-center text-sm text-muted-foreground">{empty}</div>
      ) : (
        <div className="max-h-[280px] overflow-y-auto">
          {rows.map((r) => (
            <button key={r.name} onClick={() => onRow(r)}
              className="flex w-full items-center gap-2 border-b px-4 py-1.5 text-left text-xs last:border-0 hover:bg-muted/40">
              <span className="min-w-0 flex-1 truncate">{r.name}</span>
              <span className="w-7 shrink-0 text-right tabular-nums">{r.open}</span>
              <span className={cn('w-7 shrink-0 text-right tabular-nums',
                r.overdue > 0 ? 'font-medium text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                {r.overdue}
              </span>
              <span className="w-7 shrink-0 text-right tabular-nums text-muted-foreground">{r.done}</span>
            </button>
          ))}
        </div>
      )}
    </Card>
  )
}
