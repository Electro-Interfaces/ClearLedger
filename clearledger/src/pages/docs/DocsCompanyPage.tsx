/**
 * Раздел «Компания»: где стоит работа целиком.
 *
 * То же, что в «На мне», но по всем: доска документов отвечает на вопрос «где
 * застряло согласование и кого ждут», поручения — на вопрос «чем занята
 * компания», приём — на вопрос «что нам прислала головная».
 */
import { lazy, Suspense, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import * as docsService from '@/services/docsService'
import { DocsInboxPanel } from '@/components/docs/DocsInboxPanel'
import { DocsArchiveQueue } from '@/components/docs/DocsArchiveQueue'
import { useDocsView } from './DocsLayout'
import { DocsErrorState, DocsLoadingState } from '@/components/docs/DocsQueryState'

const TasksCompanyPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((m) => ({ default: m.TasksCompanyPage })))
const TasksBoardPage = lazy(() => import('@/pages/tasks/TasksBoardPage')
  .then((m) => ({ default: m.TasksBoardPage })))

function Loading() {
  return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
}

function reportMetricLabel(value: docsService.DocBoardReportMetric): string {
  return {
    started: 'запущено', completed: 'завершено', returned: 'возвращено',
    cancelled: 'отменено', first_pass: 'с первого круга',
    decisions: 'решения сотрудника', late_decisions: 'поздние решения сотрудника',
  }[value]
}

export function DocsCompanyPage() {
  const { company } = useCompany()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs/company')
  const companyId = company?.id ?? ''
  const kindId = params.get('kind_id') ?? undefined
  const assigneeId = params.get('assignee_id') ?? undefined
  const pendingOnly = params.get('pending') === '1'
  const overdueOnly = params.get('overdue') === '1'
  const cohortFrom = params.get('date_from') ?? undefined
  const cohortTo = params.get('date_to') ?? undefined
  const metricValue = params.get('report_metric')
  const reportMetric = metricValue && [
    'started', 'completed', 'returned', 'cancelled', 'first_pass',
    'decisions', 'late_decisions',
  ].includes(metricValue)
    ? metricValue as docsService.DocBoardReportMetric : undefined
  const decisionBy = params.get('decision_by') ?? undefined
  const pageValue = params.get('page') ?? '1'
  const page = /^\d+$/.test(pageValue) ? Math.max(1, Number(pageValue)) : 1
  const filtered = !!kindId || !!assigneeId || pendingOnly || overdueOnly || !!reportMetric

  const boardQ = useQuery({
    queryKey: ['docs-board', companyId, kindId, assigneeId, pendingOnly, overdueOnly,
      cohortFrom, cohortTo, reportMetric, decisionBy, page],
    queryFn: () => docsService.board(companyId, {
      kindId, assigneeId, pendingOnly, overdueOnly, cohortFrom, cohortTo,
      reportMetric, decisionBy, page,
    }),
    enabled: !!companyId && view === 'docs',
  })

  useEffect(() => {
    if (!boardQ.data || boardQ.data.page === page) return
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (boardQ.data.page > 1) next.set('page', String(boardQ.data.page))
      else next.delete('page')
      return next
    }, { replace: true })
  }, [boardQ.data, page, setParams])

  if (!companyId) return null

  if (view === 'errands') {
    return <Suspense fallback={<Loading />}>
      <TasksCompanyPage embeddedView="registry" />
    </Suspense>
  }
  if (view === 'board') {
    return <Suspense fallback={<Loading />}><TasksBoardPage /></Suspense>
  }
  if (view === 'inbox') {
    return <div className="px-4 py-4"><DocsInboxPanel /></div>
  }
  if (view === 'archive') {
    return <DocsArchiveQueue companyId={companyId} />
  }

  const columns = boardQ.data?.columns ?? []
  const changePage = (nextPage: number) => setParams((current) => {
    const next = new URLSearchParams(current)
    if (nextPage > 1) next.set('page', String(nextPage))
    else next.delete('page')
    return next
  })

  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Документы на доске</h1>
        <p className="text-xs text-muted-foreground">
          Колонка — шаг маршрута согласования. Пусто в колонке значит, что на этом
          шаге никто не стоит.
        </p>
      </div>

      {filtered && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
          <span>
            Отбор из отчёта:
            {overdueOnly ? ' просроченные визы' : pendingOnly ? ' активные визы' : ''}
            {assigneeId ? ` согласующий: ${boardQ.data?.filter.assignee_name ?? 'выбранный участник'}` : ''}
            {kindId ? ' выбранный вид документа' : ''}
            {reportMetric ? ` показатель «${reportMetricLabel(reportMetric)}»` : ''}
            {decisionBy ? ` — ${boardQ.data?.filter.decision_name ?? 'выбранный участник'}` : ''}
            {cohortFrom && cohortTo ? ` за ${cohortFrom} — ${cohortTo}` : ''}
          </span>
          <button type="button" className="font-medium text-primary hover:underline"
            onClick={() => setParams({ view: 'docs' }, { replace: true })}>
            Сбросить отбор
          </button>
        </div>
      )}

      {boardQ.isLoading && (
        <DocsLoadingState>
          Загружаем доску…
        </DocsLoadingState>
      )}
      {boardQ.isError && (
        <DocsErrorState error={boardQ.error} title="Не удалось загрузить доску"
          detail="Пустой результат не подставлен."
          onRetry={() => { void boardQ.refetch() }} />
      )}

      {!boardQ.isLoading && !boardQ.isError && <div className="flex gap-3 overflow-x-auto pb-2">
        {columns.map((c) => (
          <div key={c.key} className="w-72 shrink-0">
            <div className="flex items-center justify-between px-1 pb-1.5">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
                {c.docs.length}
              </span>
            </div>
            <div className="space-y-2">
              {c.docs.map((d) => (
                <Link key={d.id} to={`/docs?view=all&doc=${d.id}`}
                  className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <Card className="p-2.5 transition-colors hover:bg-accent/40">
                    <div className="text-[13px]">{d.title}</div>
                    <div className="pt-0.5 text-[11px] text-muted-foreground">
                      {d.reg_number ?? 'без номера'}
                      {d.waiting ? ` · ждут ${d.waiting}` : ''}
                    </div>
                    {d.waiting_people.length > 0 && (
                      <div className="pt-1 text-[11px] text-muted-foreground">
                        {d.waiting_people.map((person) => person.name).join(', ')}
                        {d.approval_due_at && (
                          <span className={d.approval_overdue ? ' font-medium text-destructive' : ''}>
                            {` · виза до ${d.approval_due_at.slice(0, 10)}`}
                          </span>
                        )}
                      </div>
                    )}
                  </Card>
                </Link>
              ))}
              {c.docs.length === 0 && (
                <div className="rounded-md border border-dashed border-border px-2 py-6 text-center text-xs text-muted-foreground">
                  пусто
                </div>
              )}
            </div>
          </div>
        ))}
        {columns.length === 0 && (
          <div className="w-full py-10 text-center text-sm text-muted-foreground">
            {filtered
              ? 'По выбранному отбору документов нет.'
              : 'Согласований пока нет. Маршрут задаётся у вида документа в «Настройке».'}
          </div>
        )}
      </div>}

      {boardQ.data && boardQ.data.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            Показано {(boardQ.data.page - 1) * boardQ.data.page_size + 1}–
            {Math.min(boardQ.data.page * boardQ.data.page_size, boardQ.data.total)} из {boardQ.data.total}
          </span>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" disabled={boardQ.data.page <= 1}
              onClick={() => changePage(boardQ.data.page - 1)}>Назад</Button>
            <Button type="button" size="sm" variant="outline"
              disabled={boardQ.data.page >= boardQ.data.pages}
              onClick={() => changePage(boardQ.data.page + 1)}>Дальше</Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default DocsCompanyPage
