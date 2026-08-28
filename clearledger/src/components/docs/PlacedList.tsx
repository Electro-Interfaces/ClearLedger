/**
 * Список того, что человек разложил у себя: день, подборка, отложенное, важное.
 *
 * Строка показывает предмет таким, каким его видит компания — ключ, срок,
 * просрочку, — и рядом личные действия. Это не украшение: раскладка вправе
 * менять порядок, но не вправе прятать правду о сроке. Иначе человек аккуратно
 * разложит работу по своим подборкам и потеряет из виду, что виза горит третий
 * день.
 *
 * Закрытая работа сюда не приходит: сервер её не отдаёт. Убирать руками нечего —
 * необходимость уборки и есть то, из-за чего личные списки зарастают.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FileText, ListChecks, Loader2, NotebookPen } from 'lucide-react'
import { QueryError } from '@/components/common/QueryError'
import { PlaceActions } from '@/components/docs/PlaceActions'
import * as workService from '@/services/workService'
import type { PlacedItem } from '@/services/workService'
import { dt } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

type Scope = NonNullable<NonNullable<Parameters<typeof workService.placed>[1]>['scope']>

/** Куда ведёт строка: документ открывается в реестре, поручение — в работе,
 *  личная запись — в своей карточке. Тот же разбор, что у очереди. */
function href(item: PlacedItem): string {
  if (item.kind === 'doc') return `/docs?view=all&doc=${item.id}`
  return item.personal ? `/tasks/${item.id}` : `/docs/company?view=errands&task=${item.id}`
}

export function PlacedList({ companyId, scope, listId, on, empty, onChanged }: {
  companyId: string
  scope: Scope
  listId?: string
  /** День для `scope: 'day'`. Пусто — сегодня. */
  on?: string
  empty: string
  onChanged?: () => void
}) {
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['placed', companyId, scope, listId ?? '', on ?? ''],
    queryFn: () => workService.placed(companyId, { scope, listId, on }),
  })
  const refresh = () => { void q.refetch(); onChanged?.() }
  const rows = q.data?.items ?? []

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Смотрим, что разложено…
      </div>
    )
  }
  if (q.isError) {
    return <QueryError message="Раскладка не загрузилась" onRetry={() => void q.refetch()} />
  }
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-border px-4 py-6 text-center text-sm text-muted-foreground">
        {empty}
      </p>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      {rows.map((item) => {
        const Icon = item.kind === 'doc' ? FileText
          : item.personal ? NotebookPen : ListChecks
        const overdue = Boolean(item.due_at && new Date(item.due_at) < new Date())
        return (
          <div key={`${item.kind}-${item.id}`}
            // Строку можно унести в календарь рельсы: там она встанет на день.
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData('text/plain', workService.targetRef(item))
              e.dataTransfer.effectAllowed = 'move'
            }}
            className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0 hover:bg-muted/40">
            <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <button type="button" onClick={() => navigate(href(item))}
              className="min-w-0 flex-1 text-left">
              <div className="truncate text-sm leading-snug">{item.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                <span className="font-mono">{item.key}</span>
                {item.personal && <span>своя запись</span>}
                {item.mark?.starred && (
                  <span className="text-amber-600 dark:text-amber-400">важно</span>
                )}
                {item.mark?.deferred_until && scope !== 'deferred' && (
                  <span>скрыто до {item.mark.deferred_until}</span>
                )}
                {scope === 'deferred' && (item.mark?.defer_count ?? 0) > 0 && (
                  <span>откладывали {item.mark?.defer_count}</span>
                )}
              </div>
            </button>
            <span className={cn('shrink-0 text-xs tabular-nums',
              overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
              {item.due_at ? dt(item.due_at) : 'без срока'}
            </span>
            <PlaceActions companyId={companyId} targetRef={workService.targetRef(item)}
              mark={item.mark} onChanged={refresh} />
          </div>
        )
      })}
    </div>
  )
}

export default PlacedList
