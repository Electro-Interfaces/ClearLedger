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
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY } from '@/services/docsService'
import { useDocsView } from './DocsLayout'
import { useDocsScope } from '@/hooks/useDocsScope'
import { formatPeriod } from '@/lib/formatDate'
import { DocsErrorState, DocsLoadingState } from '@/components/docs/DocsQueryState'

const TasksOverviewPage = lazy(() => import('@/pages/tasks/TasksOverviewPage')
  .then((m) => ({ default: m.TasksOverviewPage })))

const BUSINESS_TIME_ZONE = 'Europe/Moscow'

function businessDate(offsetDays = 0): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: BUSINESS_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date())
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const date = new Date(Date.UTC(Number(value.year), Number(value.month) - 1,
    Number(value.day) + offsetDays))
  return date.toISOString().slice(0, 10)
}

function formatHours(value: number): string {
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)} ч`
}

function formatAsOf(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: BUSINESS_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function disciplineDetailUrl(
  report: docsService.ApprovalDisciplineReport,
  metric: docsService.DocBoardReportMetric,
  extra: Record<string, string> = {},
): string {
  const params = new URLSearchParams({
    view: 'docs', report_metric: metric,
    date_from: report.period.date_from, date_to: report.period.date_to,
    ...extra,
  })
  return `/docs/company?${params.toString()}`
}

export function DocsOverviewPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const view = useDocsView('/docs/overview')
  const scope = useDocsScope()
  const [params, setParams] = useSearchParams()
  const companyId = company?.id ?? ''
  const dateFrom = params.get('date_from') ?? scope.period.from
  const dateTo = params.get('date_to') ?? scope.period.to
  const setPeriodValue = (key: 'date_from' | 'date_to', value: string) => setParams((current) => {
    const next = new URLSearchParams(current)
    if (value) next.set(key, value)
    else next.delete(key)
    return next
  }, { replace: true })
  const dateError = useMemo(() => {
    if (!dateFrom || !dateTo) return 'Укажите начало и окончание периода'
    if (dateFrom > dateTo) return 'Дата начала позже даты окончания'
    const days = (Date.parse(dateTo) - Date.parse(dateFrom)) / 86_400_000
    return days > 366 ? 'Период не может превышать 367 дней' : ''
  }, [dateFrom, dateTo])

  const listQ = useQuery({
    queryKey: ['docs-overview', companyId, dateFrom, dateTo, scope.objectFilter],
    queryFn: () => docsService.listDocs(companyId, {
      limit: 500, date_from: dateFrom, date_to: dateTo,
      object_ids: scope.objectFilter,
    }),
    enabled: !!companyId && view === 'docs' && scope.ready,
  })
  const boardQ = useQuery({
    queryKey: ['docs-board', companyId, 'overview'],
    queryFn: () => docsService.board(companyId),
    enabled: !!companyId && view === 'docs' && scope.ready,
  })
  const disciplineQ = useQuery({
    queryKey: ['docs-discipline', companyId, dateFrom, dateTo],
    queryFn: () => docsService.approvalDiscipline(
      companyId, dateFrom || undefined, dateTo || undefined),
    enabled: !!companyId && view === 'discipline' && !dateError,
  })

  const stats = useMemo(() => {
    const docs = listQ.data?.docs ?? []
    const today = businessDate()
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
      fetching={disciplineQ.isFetching} failed={disciplineQ.isError}
      retry={() => disciplineQ.refetch()} dateError={dateError}
      dateFrom={dateFrom} dateTo={dateTo}
      setDateFrom={(value) => setPeriodValue('date_from', value)}
      setDateTo={(value) => setPeriodValue('date_to', value)} />
  }

  const columns = boardQ.data?.columns ?? []

  return (
    <div className="space-y-4 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Документы</h1>
        <p className="text-xs text-muted-foreground">
          {!scope.ready ? 'Рабочий контур ещё не применён'
            : listQ.isLoading || boardQ.isLoading ? 'Загрузка…' : `Всего в периоде: ${stats.total}`}
        </p>
      </div>

      {(listQ.isError || boardQ.isError) && (
        <DocsErrorState error={listQ.error ?? boardQ.error} title="Обзор не загрузился"
          detail="Показатели не заменены нулями. Проверьте соединение и повторите запрос."
          onRetry={() => { void listQ.refetch(); void boardQ.refetch() }} />
      )}

      {(!scope.ready || listQ.isLoading || boardQ.isLoading)
        && !scope.failed && !(listQ.isError || boardQ.isError) && (
        <DocsLoadingState>
          Собираем документы и текущие согласования…
        </DocsLoadingState>
      )}

      {scope.ready && listQ.isSuccess && boardQ.isSuccess && <>
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
        <p className="text-xs text-muted-foreground">
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
      </>}
    </div>
  )
}

function Discipline({ report, loading, fetching, failed, retry, dateError,
  dateFrom, dateTo, setDateFrom, setDateTo }: {
  report: docsService.ApprovalDisciplineReport | undefined
  loading: boolean
  fetching: boolean
  failed: boolean
  retry: () => void
  dateError: string
  dateFrom: string
  dateTo: string
  setDateFrom: (value: string) => void
  setDateTo: (value: string) => void
}) {
  const summary = report?.summary
  const estimated = report?.people.reduce((sum, row) => sum + row.estimated_decisions, 0) ?? 0
  return (
    <div className="flex flex-col gap-4 px-4 py-4" aria-busy={loading || fetching}>
      <div>
        <h1 className="text-base font-semibold">Исполнительская дисциплина</h1>
        <p id="discipline-period-hint" className="max-w-3xl text-xs text-muted-foreground">
          Период отбирает документы по первому запуску согласования, московское время.
          Текущие ожидания и просрочки показываются по всей компании вне периода.
        </p>
      </div>

      <div className="flex flex-wrap gap-3" aria-describedby="discipline-period-hint">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          С
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)}
            max={dateTo} className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground" />
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          По
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)}
            min={dateFrom} className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground" />
        </label>
        {fetching && report && (
          <span className="self-center text-xs text-muted-foreground" aria-live="polite">
            Обновляем данные…
          </span>
        )}
      </div>

      {dateError && (
        <Card role="alert" className="p-4 text-sm text-destructive">{dateError}</Card>
      )}
      {failed && !dateError && (
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">Не удалось собрать отчёт</div>
            <div className="text-xs text-muted-foreground">
              Данные не заменены нулями. Проверьте соединение и повторите запрос.
            </div>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={retry}>
            Повторить
          </Button>
        </Card>
      )}
      {loading && !report && !dateError && (
        <Card className="p-6 text-sm text-muted-foreground" aria-live="polite">
          Собираем решения и сроки согласований…
        </Card>
      )}

      {report && !dateError && !failed && <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          <Metric label="Запущено в период" value={summary?.documents ?? 0}
            hint={formatPeriod(report.period.date_from, report.period.date_to)}
            to={(summary?.documents ?? 0) > 0 ? disciplineDetailUrl(report, 'started') : undefined} />
          <Metric label="Завершено" value={summary?.completed ?? 0}
            hint="финально согласовано"
            to={(summary?.completed ?? 0) > 0 ? disciplineDetailUrl(report, 'completed') : undefined} />
          <Metric label="Возвращено" value={summary?.returned ?? 0}
            hint="последний круг отклонён"
            to={(summary?.returned ?? 0) > 0 ? disciplineDetailUrl(report, 'returned') : undefined} />
          <Metric label="Отменено" value={summary?.cancelled ?? 0}
            hint="нет положительного исхода"
            to={(summary?.cancelled ?? 0) > 0 ? disciplineDetailUrl(report, 'cancelled') : undefined} />
          <Metric label="Сейчас ждут" value={report.backlog.pending}
            hint="весь текущий backlog компании"
            to={report.backlog.pending > 0 ? '/docs/company?view=docs&pending=1' : undefined} />
          <Metric label="Сейчас просрочено" value={report.backlog.overdue}
            hint="активная виза позже SLA" tone={report.backlog.overdue > 0 ? 'danger' : undefined}
            to={report.backlog.overdue > 0 ? '/docs/company?view=docs&overdue=1' : undefined} />
          <Metric label="С первого круга"
            value={(summary?.first_pass_sample ?? 0) > 0 ? `${summary?.first_pass_rate}%` : '—'}
            hint={(summary?.first_pass_sample ?? 0) > 0
              ? `${summary?.first_pass_documents} из ${summary?.first_pass_sample}`
              : 'нет завершённых первых кругов'}
            to={(summary?.first_pass_documents ?? 0) > 0
              ? disciplineDetailUrl(report, 'first_pass') : undefined} />
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Скорость по видам</CardTitle>
              <CardDescription>
                От первого запуска до финального решения, включая повторные круги
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="min-w-[560px] w-full text-sm">
                  <caption className="sr-only">Длительность согласования по видам документов</caption>
                  <thead className="text-xs text-muted-foreground">
                    <tr><th scope="col" className="pb-2 text-left font-medium">Вид</th>
                      <th scope="col" className="pb-2 text-right font-medium">Док.</th>
                      <th scope="col" className="pb-2 text-right font-medium">Среднее</th>
                      <th scope="col" className="pb-2 text-right font-medium">Медиана</th>
                      <th scope="col" className="pb-2 text-right font-medium">P90</th></tr>
                  </thead>
                  <tbody>
                    {report.by_kind.map((row) => (
                      <tr key={row.kind_id} className="border-t border-border">
                        <td className="max-w-64 break-words py-2 pe-3">
                          <Link className="font-medium text-primary hover:underline"
                            to={disciplineDetailUrl(report, 'completed', { kind_id: row.kind_id })}>
                            {row.kind}
                          </Link>
                        </td>
                        <td className="py-2 text-right tabular-nums">{row.documents}</td>
                        <td className="py-2 text-right tabular-nums">{formatHours(row.average_hours)}</td>
                        <td className="py-2 text-right tabular-nums">{formatHours(row.median_hours)}</td>
                        <td className="py-2 text-right font-medium tabular-nums">{formatHours(row.p90_hours)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!report.by_kind.length && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  В выбранной когорте нет завершённых согласований
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Кого сейчас ждут</CardTitle>
              <CardDescription>
                Активные визы по всей компании на {formatAsOf(report.backlog.as_of)}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="min-w-[420px] w-full text-sm">
                  <caption className="sr-only">Текущие ожидания и просрочки по назначенным согласующим</caption>
                  <thead className="text-xs text-muted-foreground">
                    <tr><th scope="col" className="pb-2 text-left font-medium">Человек</th>
                      <th scope="col" className="pb-2 text-right font-medium">Ждут</th>
                      <th scope="col" className="pb-2 text-right font-medium">Просрочено</th></tr>
                  </thead>
                  <tbody>
                    {report.backlog.people.map((row) => (
                      <tr key={row.user_id} className="border-t border-border">
                        <td className="max-w-64 break-words py-2 pe-3">
                          <Link className="font-medium text-primary hover:underline"
                            to={`/docs/company?view=docs&assignee_id=${row.user_id}`}>
                            {row.name}
                          </Link>
                        </td>
                        <td className="py-2 text-right tabular-nums">{row.pending}</td>
                        <td className={`py-2 text-right tabular-nums ${row.overdue ? 'font-medium text-destructive' : ''}`}>
                          {row.overdue ? (
                            <Link className="hover:underline"
                              to={`/docs/company?view=docs&assignee_id=${row.user_id}&overdue=1`}>
                              {row.overdue}
                            </Link>
                          ) : 0}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!report.backlog.people.length && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  Активных виз сейчас нет
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="min-w-0 xl:col-span-2">
            <CardHeader>
              <CardTitle>Скорость решений</CardTitle>
              <CardDescription>
                Фактически принявшие решение в выбранной когорте; замещения учитываются отдельно
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="min-w-[720px] w-full text-sm">
                  <caption className="sr-only">Скорость решений по фактическим согласующим</caption>
                  <thead className="text-xs text-muted-foreground">
                    <tr><th scope="col" className="pb-2 text-left font-medium">Человек</th>
                      <th scope="col" className="pb-2 text-right font-medium">Док.</th>
                      <th scope="col" className="pb-2 text-right font-medium">Решений</th>
                      <th scope="col" className="pb-2 text-right font-medium">Поздних док.</th>
                      <th scope="col" className="pb-2 text-right font-medium">В замещении</th>
                      <th scope="col" className="pb-2 text-right font-medium">Среднее</th>
                      <th scope="col" className="pb-2 text-right font-medium">Медиана</th>
                      <th scope="col" className="pb-2 text-right font-medium">P90</th></tr>
                  </thead>
                  <tbody>
                    {report.people.map((row) => (
                      <tr key={row.user_id} className="border-t border-border">
                        <td className="max-w-64 break-words py-2 pe-3">{row.name}</td>
                        <td className="py-2 text-right tabular-nums">
                          <Link className="font-medium text-primary hover:underline"
                            to={disciplineDetailUrl(report, 'decisions', { decision_by: row.user_id })}>
                            {row.documents}
                          </Link>
                        </td>
                        <td className="py-2 text-right tabular-nums">{row.decisions}</td>
                        <td className={`py-2 text-right tabular-nums ${row.late_documents ? 'font-medium text-destructive' : ''}`}>
                          {row.late_documents ? (
                            <Link className="hover:underline" to={disciplineDetailUrl(
                              report, 'late_decisions', { decision_by: row.user_id })}>
                              {row.late_documents}
                            </Link>
                          ) : 0}
                        </td>
                        <td className="py-2 text-right tabular-nums">{row.delegated_decisions}</td>
                        <td className="py-2 text-right tabular-nums">{formatHours(row.average_hours)}</td>
                        <td className="py-2 text-right tabular-nums">{formatHours(row.median_hours)}</td>
                        <td className="py-2 text-right font-medium tabular-nums">{formatHours(row.p90_hours)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!report.people.length && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  В выбранной когорте решений нет
                </p>
              )}
              {estimated > 0 && (
                <p className="pt-3 text-xs text-muted-foreground">
                  Для {estimated} исторических решений момент активации оценён по запуску круга:
                  до обновления система не фиксировала его отдельно.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </>}
    </div>
  )
}

function Metric({ label, value, hint, tone, to }: {
  label: string
  value: number | string
  hint?: string
  tone?: 'danger'
  to?: string
}) {
  const card = (
    <Card className={`h-full ${to ? 'transition-colors group-hover:bg-accent/40' : ''}`}>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`text-2xl tabular-nums ${tone === 'danger' ? 'text-destructive' : ''}`}>
          {value}
        </CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  )
  return to ? (
    <Link to={to} className="group rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {card}
    </Link>
  ) : card
}

function Tile({ label, value, hint, onClick }: {
  label: string; value: number; hint: string; onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick}
      className="rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-accent/40">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="pt-0.5 text-2xl font-semibold">{value}</div>
      <div className="pt-0.5 text-xs text-muted-foreground">{hint}</div>
    </button>
  )
}

export default DocsOverviewPage
