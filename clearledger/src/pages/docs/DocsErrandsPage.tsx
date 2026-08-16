/**
 * Раздел «Поручения» внутри «Трека»: список, доска по стадиям и доска по срокам.
 *
 * Экраны переиспользуются целиком: движок работы тот же, что и был, переехало
 * только место — человек больше не ходит в отдельный трекер. Пункт раздела
 * выбирает представление, как и везде в пространстве.
 */
import { lazy, Suspense } from 'react'
import { useDocsView } from './DocsLayout'

const TasksWorkPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((m) => ({ default: m.TasksWorkPage })))
const TasksCompanyPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((m) => ({ default: m.TasksCompanyPage })))
const TasksBoardPage = lazy(() => import('@/pages/tasks/TasksBoardPage')
  .then((m) => ({ default: m.TasksBoardPage })))

function Loading() {
  return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
}

export function DocsErrandsPage() {
  const view = useDocsView('/docs/errands')

  return (
    <Suspense fallback={<Loading />}>
      {view === 'board' ? <TasksBoardPage />
        : view === 'all' ? <TasksCompanyPage />
          : <TasksWorkPage />}
    </Suspense>
  )
}

export default DocsErrandsPage
