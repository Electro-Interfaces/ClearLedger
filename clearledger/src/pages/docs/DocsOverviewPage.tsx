/**
 * Обзор «Трека»: как идут документы и поручения.
 *
 * Два взгляда на одно рабочее место. По документам считаем то, за чем приходит
 * делопроизводитель: сколько без номера, сколько стоит на визах и у кого горит
 * срок. По поручениям показываем готовую сводку трекера — второй такой считать
 * незачем.
 */
import { lazy, Suspense, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

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
  const disciplineQ = useQuery({
    queryKey: ['docs-discipline', companyId, dateFrom, dateTo],
    queryFn: () => docsService.approvalDiscipline(
      companyId, dateFrom || undefined, dateTo || undefined),
    enabled: !!companyId && view === 'discipline',
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
  if (view === 'discipline') {
    return <Discipline report={disciplineQ.data} loading={disciplineQ.isLoading}
      dateFrom={dateFrom} dateTo={dateTo} setDateFrom={setDateFrom} setDateTo={setDateTo} />
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

function Discipline({ report, loading, dateFrom, dateTo, setDateFrom, setDateTo }: {
  report: docsService.ApprovalDisciplineReport | undefined
  loading: boolean
  dateFrom: string
  dateTo: string
  setDateFrom: (value: string) => void
  setDateTo: (value: string) => void
}) {
  const summary = report?.summary
  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Исполнительская дисциплина</h1>
        <p className="text-xs text-muted-foreground">
          {loading ? 'Загрузка…' : 'Скорость согласования считается от запуска до последней визы.'}
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          С
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground" />
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          По
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground" />
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Документов с визами" value={summary?.documents ?? 0} />
        <Metric label="Завершено" value={summary?.completed ?? 0} />
        <Metric label="Сейчас ждут" value={summary?.pending ?? 0} />
        <Metric label="С первого круга" value={`${summary?.first_pass_rate ?? 0}%`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Скорость по видам</CardTitle>
            <CardDescription>Среднее время полного согласования документа</CardDescription>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="pb-2 text-left font-medium">Вид</th>
                  <th className="pb-2 text-right font-medium">Документов</th>
                  <th className="pb-2 text-right font-medium">Часов</th></tr>
              </thead>
              <tbody>
                {(report?.by_kind ?? []).map((row) => (
                  <tr key={row.kind} className="border-t border-border">
                    <td className="py-2">{row.kind}</td>
                    <td className="py-2 text-right">{row.documents}</td>
                    <td className="py-2 text-right font-medium">{row.average_hours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !report?.by_kind.length && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                Завершённых согласований пока нет
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>По согласующим</CardTitle>
            <CardDescription>Просроченные визы и среднее время решения</CardDescription>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="pb-2 text-left font-medium">Человек</th>
                  <th className="pb-2 text-right font-medium">Ждут</th>
                  <th className="pb-2 text-right font-medium">Просрочено</th>
                  <th className="pb-2 text-right font-medium">Часов</th></tr>
              </thead>
              <tbody>
                {(report?.people ?? []).map((row) => (
                  <tr key={row.user_id} className="border-t border-border">
                    <td className="py-2">{row.name}</td>
                    <td className="py-2 text-right">{row.pending}</td>
                    <td className="py-2 text-right">{row.overdue}</td>
                    <td className="py-2 text-right font-medium">{row.average_hours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !report?.people.length && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                Виз пока нет
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
    </Card>
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
