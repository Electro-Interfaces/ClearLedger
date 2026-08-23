/**
 * Общая доска: документы и поручения в одних колонках (этап 13д).
 *
 * Колонки — общая ось состояния (`work_state`), одна для обоих контуров.
 * Перенос делает движок предмета: поручение идёт по маршруту своего типа,
 * документ — через круг виз. Доска не заводит третьего способа менять
 * состояние, иначе след работы разошёлся бы с самой работой.
 *
 * Отказ всегда с причиной. Карточка, молча прыгнувшая обратно, — загадка;
 * «у этого типа нет стадии в колонке „На согласовании“» — ответ, по которому
 * видно, что делать.
 *
 * Перенос — нативный HTML5 drag-and-drop, как на доске поручений: новую
 * зависимость ради четырёх обработчиков не тянем.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FileText, ListChecks, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { WorkItem, WorkState } from '@/services/workService'
import { dt, PRIORITY_TONE } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

const BOARD_LIMIT = 200

export function WorkBoardPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [dragged, setDragged] = useState<WorkItem | null>(null)
  const [over, setOver] = useState<WorkState | null>(null)

  const kind = params.get('kind') ?? ''
  const set = (kv: Record<string, string | null>) => setParams((p) => {
    const next = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) next.set(k, v); else next.delete(k) }
    return next
  }, { replace: true })

  const q = useQuery({
    queryKey: ['work-board', company.id, kind],
    queryFn: () => workService.listWork(company.id, {
      scope: 'open', kind: (kind || undefined) as 'doc' | 'task' | undefined,
      limit: BOARD_LIMIT, sort: 'due',
    }),
    placeholderData: keepPreviousData,
  })

  const move = useMutation({
    mutationFn: (v: { item: WorkItem; state: WorkState }) =>
      workService.moveWork(v.item.kind, v.item.id, company.id, v.state),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['work-board'] })
      void qc.invalidateQueries({ queryKey: ['work'] })
      void qc.invalidateQueries({ queryKey: ['work-summary'] })
    },
    // Причина отказа — главное, что человек должен увидеть: иначе карточка
    // просто вернулась на место, и почему — неизвестно.
    onError: (e) => toast.error((e as Error).message, { duration: 6000 }),
  })

  const items = q.data?.work ?? []
  const columns = q.data?.columns ?? []

  const drop = (state: WorkState) => {
    const item = dragged
    setDragged(null); setOver(null)
    if (!item || item.state === state) return
    move.mutate({ item, state })
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">Доска работы</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Колонки общие для документов и поручений. Перенос выполняет движок
            предмета: маршрут у поручения, круг виз у документа.
          </p>
        </div>
        <Select value={kind || 'all'}
          onValueChange={(v) => set({ kind: v === 'all' ? null : v })}>
          <SelectTrigger className="h-8 w-[150px] text-xs">
            <SelectValue placeholder="Род" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всё вместе</SelectItem>
            <SelectItem value="doc">Документы</SelectItem>
            <SelectItem value="task">Поручения</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" className="h-8"
          onClick={() => void q.refetch()} disabled={q.isFetching}>
          <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', q.isFetching && 'animate-spin')} />
          Обновить
        </Button>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираем доску…
        </div>
      ) : q.isError ? (
        <QueryError message="Доска не загрузилась" onRetry={() => void q.refetch()} />
      ) : (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
          {columns.map((col) => {
            const cards = items.filter((i) => i.state === col.code)
            const droppable = !!dragged && dragged.state !== col.code
            return (
              <div key={col.code}
                onDragOver={(e) => { e.preventDefault(); setOver(col.code) }}
                onDragLeave={() => setOver((c) => (c === col.code ? null : c))}
                onDrop={() => drop(col.code)}
                className={cn(
                  'flex w-[280px] shrink-0 flex-col rounded-xl border bg-muted/30 transition-colors',
                  over === col.code && droppable
                    && 'border-primary bg-primary/5 ring-1 ring-primary/30')}>
                <div className="flex items-center gap-2 px-3 py-2.5">
                  <span className="text-[13px] font-medium">{col.name}</span>
                  <span className={cn('ml-auto rounded-full px-1.5 py-0.5 text-[11px] tabular-nums',
                    cards.length ? 'bg-background text-muted-foreground'
                      : 'text-muted-foreground/50')}>
                    {cards.length}
                  </span>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
                  {cards.map((item) => (
                    <Card key={`${item.kind}-${item.id}`} item={item}
                      dragging={dragged?.id === item.id}
                      onDragStart={() => setDragged(item)}
                      onDragEnd={() => { setDragged(null); setOver(null) }}
                      onOpen={() => navigate(workService.workHref(item))} />
                  ))}
                  {cards.length === 0 && (
                    <div className="px-2 py-6 text-center text-[11px] text-muted-foreground/70">
                      Пусто
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Card({ item, dragging, onDragStart, onDragEnd, onOpen }: {
  item: WorkItem; dragging: boolean
  onDragStart: () => void; onDragEnd: () => void; onOpen: () => void
}) {
  const Icon = item.kind === 'doc' ? FileText : ListChecks
  return (
    <div draggable onDragStart={onDragStart} onDragEnd={onDragEnd} onClick={onOpen}
      className={cn('group cursor-grab rounded-lg border bg-card px-2.5 py-2 text-xs shadow-sm transition-all active:cursor-grabbing',
        'hover:-translate-y-px hover:border-primary/40 hover:shadow-md',
        dragging && 'opacity-40 shadow-none',
        item.overdue && 'border-red-500/40 bg-red-500/5')}>
      <div className="flex items-start gap-1.5">
        <Icon className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground"
          aria-label={item.kind === 'doc' ? 'документ' : 'поручение'} />
        <span className={cn('flex-1 font-medium leading-snug',
          item.priority && PRIORITY_TONE[item.priority])}>
          {item.title}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">
          {item.key}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
        {item.stage && <span>{item.stage}</span>}
        {item.responsible && <span>{item.responsible}</span>}
        {item.due_at && (
          <span className={cn(item.overdue && 'text-red-600 dark:text-red-400')}>
            {dt(item.due_at)}
          </span>
        )}
      </div>
    </div>
  )
}

export default WorkBoardPage
