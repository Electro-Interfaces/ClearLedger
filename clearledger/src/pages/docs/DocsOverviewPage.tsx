/**
 * Обзор «Трека»: как идут документы и поручения.
 *
 * Два взгляда на одно рабочее место. По документам считаем то, за чем приходит
 * делопроизводитель: сколько без номера, сколько стоит на визах и у кого горит
 * срок. По поручениям показываем готовую сводку трекера — второй такой считать
 * незачем.
 */
import { lazy, Suspense, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card } from '@/components/ui/card'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY } from '@/services/docsService'
import { useDocsView } from './DocsLayout'

const TasksOverviewPage = lazy(() => import('@/pages/tasks/TasksOverviewPage')
  .then((m) => ({ default: m.TasksOverviewPage })))

export function DocsOverviewPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const view = useDocsView('/docs/overview')
  const companyId = company?.id ?? ''

  const listQ = useQuery({
    queryKey: ['docs-overview', companyId],
    queryFn: () => docsService.listDocs(companyId, { limit: 500 }),
    enabled: !!companyId && view === 'docs',
  })
  const boardQ = useQuery({
    queryKey: ['docs-board', companyId, 'overview'],
    queryFn: () => docsService.board(companyId),
    enabled: !!companyId && view === 'docs',
  })

  const stats = useMemo(() => {
    const docs = listQ.data?.docs ?? []
    const today = new Date().toISOString().slice(0, 10)
    return {
      total: docs.length,
      draft: docs.filter((d) => !d.reg_number).length,
      approving: docs.filter((d) => d.approval_status === 'pending').length,
      returned: docs.filter((d) => d.approval_status === 'rejected').length,
      overdue: docs.filter((d) => d.due_at && d.due_at.slice(0, 10) < today
        && !['executed', 'archived', 'cancelled'].includes(d.status)).length,
      byFamily: Object.entries(
        docs.reduce<Record<string, number>>((acc, d) => {
          acc[d.family] = (acc[d.family] ?? 0) + 1
          return acc
        }, {})).sort((a, b) => b[1] - a[1]),
    }
  }, [listQ.data])

  if (view === 'errands') {
    return (
      <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Загрузка…</div>}>
        <TasksOverviewPage />
      </Suspense>
    )
  }

  const columns = boardQ.data?.columns ?? []

  return (
    <div className="space-y-4 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Документы</h1>
        <p className="text-xs text-muted-foreground">
          {listQ.isLoading ? 'Загрузка…' : `Всего в работе: ${stats.total}`}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Без номера" value={stats.draft}
          hint="заведены, но не зарегистрированы"
          onClick={() => navigate('/docs?view=all')} />
        <Tile label="На визах" value={stats.approving}
          hint="идёт согласование"
          onClick={() => navigate('/docs/work?view=approvals')} />
        <Tile label="Возвращены" value={stats.returned}
          hint="отказ с замечанием, ждут доработки"
          onClick={() => navigate('/docs?view=all')} />
        <Tile label="Просрочены" value={stats.overdue}
          hint="срок исполнения прошёл"
          onClick={() => navigate('/docs?view=all')} />
      </div>

      <Card className="p-4">
        <div className="text-sm font-medium">По потокам</div>
        <div className="mt-2 space-y-1">
          {stats.byFamily.map(([family, count]) => (
            <div key={family} className="flex items-center justify-between text-[13px]">
              <span className="text-muted-foreground">
                {DOC_FAMILY[family] ?? family}
              </span>
              <span className="font-medium">{count}</span>
            </div>
          ))}
          {stats.byFamily.length === 0 && (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Документов пока нет
            </div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <div className="text-sm font-medium">Где стоит согласование</div>
        <p className="text-[11px] text-muted-foreground">
          Колонка — шаг маршрута. Вопрос «где документ застрял» это вопрос о шаге
          и о том, кого ждут.
        </p>
        <div className="mt-2 space-y-1">
          {columns.map((c) => (
            <div key={c.key} className="flex items-center justify-between text-[13px]">
              <span className="text-muted-foreground">{c.name}</span>
              <span className="font-medium">{c.docs.length}</span>
            </div>
          ))}
          {columns.length === 0 && (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Согласований пока нет
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

function Tile({ label, value, hint, onClick }: {
  label: string; value: number; hint: string; onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick}
      className="rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-accent/40">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="pt-0.5 text-2xl font-semibold">{value}</div>
      <div className="pt-0.5 text-[11px] text-muted-foreground">{hint}</div>
    </button>
  )
}

export default DocsOverviewPage
