/**
 * Доска: стадии маршрута колонками, карточка переносится мышью.
 *
 * Доска строится ПО ТИПУ: у разных типов разные маршруты, и смешав их в одной
 * доске, получаешь колонки, в которые половина карточек не может попасть.
 *
 * Перенос — то же действие, что кнопка стадии в карточке (`/action`), поэтому и
 * след в ленте одинаковый: человек не должен угадывать, чем «перетащил»
 * отличается от «нажал».
 *
 * Перенос сделан нативным HTML5 drag-and-drop — новую зависимость ради четырёх
 * обработчиков не тянем. На планшете пальцем DnD не работает, поэтому у карточки
 * есть и кнопка «дальше по маршруту».
 */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { RouteStage, SpaceTask } from '@/services/tasksService'
import { TaskCard } from '@/components/tasks/TaskCard'
import { PRIORITY_TONE, PRIORITY_LABEL, dt } from '@/components/tasks/taskWords'

export function TasksBoardPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const typeId = params.get('type') ?? ''
  const openId = params.get('task')
  const [dragged, setDragged] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)

  const set = (kv: Record<string, string | null>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    return n
  }, { replace: true })

  const typesQ = useQuery({
    queryKey: ['task-types', company.id],
    queryFn: () => tasksService.listTaskTypes(company.id),
    staleTime: 5 * 60 * 1000,
  })
  const listQ = useQuery({
    queryKey: ['tasks', company.id, 'board', typeId],
    queryFn: () => tasksService.listTasks(company.id, 'open', {
      typeId: typeId || undefined, limit: 500,
    }),
    placeholderData: keepPreviousData,
  })
  const move = useMutation({
    mutationFn: (v: { id: string; stageCode: string }) =>
      tasksService.taskAction(v.id, { companyId: company.id, stageCode: v.stageCode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      void listQ.refetch()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const types = typesQ.data?.types ?? []
  const selected = types.find((t) => t.id === typeId)
  // Тип не выбран — доска идёт по маршруту поручения: задачи без типа тоже
  // должны где-то жить, а пустой экран с просьбой «выберите тип» — не работа.
  const route: RouteStage[] = selected?.route ?? typesQ.data?.default_route ?? []
  const tasks = (listQ.data?.tasks ?? []).filter(
    (t) => (typeId ? t.type_id === typeId : !t.type_id))

  const drop = (stage: string) => {
    setOver(null)
    const id = dragged
    setDragged(null)
    if (!id) return
    const t = tasks.find((x) => x.id === id)
    if (t && t.stage_code !== stage) move.mutate({ id, stageCode: stage })
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Доска</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Колонки — стадии маршрута. Карточка переносится мышью; на планшете —
            стрелкой «дальше» на самой карточке.
          </p>
        </div>
        <Select value={typeId || 'none'}
          onValueChange={(v) => set({ type: v === 'none' ? null : v })}>
          <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Поручения (без типа)</SelectItem>
            {types.filter((t) => t.is_active).map((t) => (
              <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {listQ.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка доски…
        </div>
      ) : listQ.isError ? (
        <QueryError message="Не удалось загрузить доску" onRetry={() => void listQ.refetch()} />
      ) : (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
          {route.map((s) => {
            const column = tasks.filter((t) => t.stage_code === s.code)
            const nextStage = route[route.findIndex((x) => x.code === s.code) + 1]
            return (
              // Пустая колонка не схлопывается: в неё нужно уметь перетащить.
              <div key={s.code}
                onDragOver={(e) => { e.preventDefault(); setOver(s.code) }}
                onDragLeave={() => setOver((c) => (c === s.code ? null : c))}
                onDrop={() => drop(s.code)}
                className={cn('flex w-[280px] shrink-0 flex-col rounded-lg border bg-card/40',
                  over === s.code && 'border-primary bg-primary/5')}>
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <span className="text-xs font-medium">{s.name}</span>
                  <span className="text-[11px] text-muted-foreground">{column.length}</span>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto p-2">
                  {column.map((t) => (
                    <BoardCard key={t.id} task={t} nextStage={nextStage}
                      onOpen={() => set({ task: t.id })}
                      onDragStart={() => setDragged(t.id)}
                      onNext={() => nextStage && move.mutate({ id: t.id, stageCode: nextStage.code })} />
                  ))}
                  {column.length === 0 && (
                    <p className="px-1 py-4 text-center text-[11px] text-muted-foreground">
                      пусто
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <Sheet open={!!openId} onOpenChange={(v) => { if (!v) set({ task: null }) }}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-2xl">
          <SheetTitle className="sr-only">Карточка задачи</SheetTitle>
          <SheetDescription className="sr-only">Работа, атрибуты и лента</SheetDescription>
          {openId && (
            <TaskCard id={openId} companyId={company.id}
              onChanged={() => void listQ.refetch()} onOpenOther={(id) => set({ task: id })} />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function BoardCard({ task, nextStage, onOpen, onDragStart, onNext }: {
  task: SpaceTask; nextStage?: RouteStage
  onOpen: () => void; onDragStart: () => void; onNext: () => void
}) {
  return (
    <div draggable onDragStart={onDragStart} onClick={onOpen}
      className={cn('cursor-pointer rounded-md border bg-card px-2.5 py-2 text-xs shadow-sm transition-colors hover:border-primary/40',
        task.overdue && 'border-red-500/40 bg-red-500/5')}>
      <div className="flex items-start gap-1.5">
        <span className="shrink-0 font-medium text-muted-foreground">№{task.number}</span>
        <span className="flex-1 font-medium text-foreground">{task.title}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <span>{task.assignee ?? 'не назначен'}</span>
        {task.due_at && (
          <span className={cn(task.overdue && 'font-medium text-red-600 dark:text-red-400')}>
            · {task.overdue ? 'просрочена' : dt(task.due_at)}
          </span>
        )}
        {(task.priority === 'high' || task.priority === 'critical') && (
          <span className={PRIORITY_TONE[task.priority]}>· {PRIORITY_LABEL[task.priority]}</span>
        )}
        {task.checklist.total > 0 && (
          <span>· {task.checklist.done}/{task.checklist.total}</span>
        )}
      </div>
      {nextStage && (
        <button type="button" title={`Дальше: ${nextStage.name}`}
          onClick={(e) => { e.stopPropagation(); onNext() }}
          className="mt-1.5 inline-flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
          <ArrowRight className="h-3 w-3" />{nextStage.name}
        </button>
      )}
    </div>
  )
}

export default TasksBoardPage
