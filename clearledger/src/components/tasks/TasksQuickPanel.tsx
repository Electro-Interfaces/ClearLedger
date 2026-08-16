/**
 * Быстрый взгляд на задачи из шапки — как окно чата рядом: что на мне сейчас, что
 * горит, и одним кликом в саму задачу. Полная работа (типы, маршруты, история, чужие
 * задачи) живёт в «Треке» (`/docs`), сюда её не тащим.
 */
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, ListChecks } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import * as tasksService from '@/services/tasksService'

/** Срок словами: «сегодня» / «завтра» / «просрочена на 3 дн» — точная дата тут лишняя. */
function dueText(due: string | null, overdue: boolean): string | null {
  if (!due) return null
  const days = Math.round((new Date(due).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000)
  if (days < 0) return `просрочена на ${-days} дн`
  // Срок сегодня, но час уже прошёл: бэкенд пометил задачу просроченной, а разница
  // в днях ещё ноль — «просрочена на 0 дн» тут и вылезала.
  if (overdue) return 'срок истёк'
  if (days === 0) return 'срок сегодня'
  if (days === 1) return 'срок завтра'
  return `срок через ${days} дн`
}

export function TasksQuickPanel() {
  const navigate = useNavigate()
  const { companyId } = useCompany()
  const { closeInteraction } = useSupportContext()
  // Тот же ключ, что у списка в приложении (`['tasks', companyId, scope, objectId,
  // typeId]`) и у счётчика на кнопке: открыв «Задачи» следом, человек видит готовый
  // список, а не второй запрос за теми же строками.
  const { data, isLoading } = useQuery({
    queryKey: ['tasks', companyId, 'mine', '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, 'mine'),
    enabled: !!companyId,
  })
  const tasks = useMemo(() => (data?.tasks || []).filter((t) => t.status === 'open'), [data])
  const overdue = tasks.filter((t) => t.overdue).length

  const open = (id?: string) => {
    closeInteraction()
    navigate(id ? `/docs/work?view=errands&task=${id}` : '/docs/work?view=errands')
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="text-sm text-muted-foreground">
          {isLoading ? 'Загружаю…' : (
            <>
              На мне <span className="font-semibold text-foreground">{tasks.length}</span>
              {overdue > 0 && <> · просрочено <span className="font-semibold text-red-600">{overdue}</span></>}
            </>
          )}
        </div>
        <Button size="sm" variant="outline" className="gap-1.5" onClick={() => open()}>
          Открыть «Трек»
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Button>
      </div>

      {!isLoading && tasks.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 dark:bg-primary/20">
            <ListChecks className="h-7 w-7 text-primary" />
          </div>
          <p className="max-w-sm text-sm text-muted-foreground">
            На вас сейчас ничего не назначено. Поставить задачу себе или коллеге можно
            в приложении «Задачи».
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-2">
          {tasks.map((t) => (
            <button
              key={t.id}
              onClick={() => open(t.id)}
              className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-accent"
            >
              <span className="mt-0.5 shrink-0 font-mono text-xs text-muted-foreground">№{t.number}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-foreground">{t.title}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                  {t.stage && <span>{t.stage}</span>}
                  {t.object && <span>· {t.object}</span>}
                  {dueText(t.due_at, t.overdue) && (
                    <span className={t.overdue ? 'text-red-600' : ''}>· {dueText(t.due_at, t.overdue)}</span>
                  )}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
