/**
 * «На мне» — одна очередь на все роды действия (этап 13г).
 *
 * Личное было разложено по четырём пунктам: визы, поручения, ознакомления, свои
 * документы. Человек утром хочет знать не «сколько у меня виз», а «что горит», —
 * поэтому здесь один список, сгруппированный по сроку, а род действия остаётся
 * значком и словом в строке.
 *
 * Действие делается прямо в строке: расписаться, отметить прочтение, закрыть
 * работу. Открывать карточку ради одного нажатия — то, из-за чего почтовые
 * ящики разрастаются до тысяч непрочитанных.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Check, Eye, FileText, ListChecks, Loader2, Stamp,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { MyWorkItem } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import * as docsService from '@/services/docsService'
import { dt } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

const REASON_ICON = {
  approve: Stamp, acquaint: Eye, do: ListChecks, own: FileText,
} as const

export function MyWorkPage({ buckets: only, heading = true }: {
  /** Какие корзины показывать. Пусто — все. «Сегодня» берёт две первые: там
   *  вопрос не «что на мне вообще», а «что на мне сегодня». */
  buckets?: MyWorkItem['bucket'][]
  /** Заголовок печатает вызывающий экран, когда очередь у него не единственное. */
  heading?: boolean
} = {}) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()

  const q = useQuery({
    queryKey: ['work-mine', company.id],
    queryFn: () => workService.myWork(company.id),
  })
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    void qc.invalidateQueries({ queryKey: ['work'] })
  }

  // Действие в строке — то же самое, что в карточке: одна ручка, один след.
  const act = useMutation({
    mutationFn: async (item: MyWorkItem) => {
      if (item.reason === 'do') {
        return tasksService.taskAction(item.id, {
          companyId: company.id, status: 'done',
        })
      }
      if (item.reason === 'acquaint' && item.acquaint_id) {
        return docsService.markAcquainted(company.id, item.id, item.acquaint_id)
      }
      throw new Error('Это действие делается в карточке')
    },
    onSuccess: () => { refresh(); toast.success('Готово') },
    onError: (e) => toast.error((e as Error).message),
  })

  const all = q.data?.mine ?? []
  const rows = only?.length ? all.filter((r) => only.includes(r.bucket)) : all
  const buckets = (q.data?.buckets ?? []).filter((b) => !only?.length || only.includes(b.code))

  return (
    <div className={cn('space-y-4', heading && 'p-4')}>
      {heading && (
        <div>
          <h1 className="text-lg font-semibold">На мне</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">
            Всё, что ждёт лично меня: визы, поручения, ознакомления и свои документы.
            Сгруппировано по сроку, а не по тому, какой движок за предметом стоит.
          </p>
        </div>
      )}

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираем очередь…
        </div>
      ) : q.isError ? (
        <QueryError message="Очередь не загрузилась" onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          {only?.length
            ? 'На сегодня ничего не назначено.'
            : 'На вас ничего не ждёт. Это нормальное состояние, а не пустой экран.'}
        </div>
      ) : buckets.map((b) => {
        const group = rows.filter((r) => r.bucket === b.code)
        if (group.length === 0) return null
        return (
          <section key={b.code} className="space-y-1.5">
            <h2 className={cn('text-xs font-semibold uppercase tracking-wide',
              b.code === 'overdue' ? 'text-red-600 dark:text-red-400'
                : 'text-muted-foreground')}>
              {b.name} <span className="tabular-nums">({group.length})</span>
            </h2>
            <div className="overflow-hidden rounded-lg border">
              {group.map((item) => (
                <Line key={`${item.kind}-${item.id}-${item.reason}`} item={item}
                  busy={act.isPending}
                  onOpen={() => navigate(workService.myWorkHref(item))}
                  onDone={() => act.mutate(item)} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function Line({ item, busy, onOpen, onDone }: {
  item: MyWorkItem; busy: boolean; onOpen: () => void; onDone: () => void
}) {
  const Icon = REASON_ICON[item.reason]
  // Кнопка показана только там, где действие правда доступно строкой: визу
  // ставят в карточке, где видно лист согласования и предыдущие круги.
  const canFinish = item.reason === 'do' || (item.reason === 'acquaint' && item.acquaint_id)
  return (
    <div className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0 hover:bg-muted/40">
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <button type="button" onClick={onOpen} className="flex-1 text-left">
        <div className="text-sm leading-snug">{item.title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
          <span className="font-mono">{item.key}</span>
          <span>{item.reason_name}</span>
          {item.note && <span>{item.note}</span>}
          {item.acting_for && <span>за коллегу</span>}
        </div>
      </button>
      <span className={cn('shrink-0 text-[11px] tabular-nums',
        item.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
        {item.due_at ? dt(item.due_at) : 'без срока'}
      </span>
      {canFinish ? (
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={busy}
          title={item.reason === 'do' ? 'Закрыть работу' : 'Отметить ознакомление'}
          onClick={onDone}>
          <Check className="h-3.5 w-3.5" />
        </Button>
      ) : (
        <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]"
          onClick={onOpen}>Открыть</Button>
      )}
    </div>
  )
}

export default MyWorkPage
