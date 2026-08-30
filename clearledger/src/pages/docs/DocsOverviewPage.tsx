/**
 * Отчёты «Трека»: как идут документы и поручения.
 *
 * Два взгляда на одно рабочее место. По документам считаем то, за чем приходит
 * делопроизводитель: сколько без номера, сколько стоит на визах и у кого горит
 * срок. По поручениям показываем готовую сводку трекера — второй такой считать
 * незачем.
 *
 * Два правила на весь раздел.
 *
 * Период один и берётся из «Рабочего контура»: три отчёта с тремя своими
 * регуляторами дат заставляли человека выяснять, какой из них он сейчас
 * настроил. Каждый отчёт лишь объясняет, что он этим периодом отбирает.
 *
 * Любая цифра — вход в список с этим же отбором. Цифра, за которой не
 * открывается предмет, отвечает на вопрос «сколько» и не даёт ответить на
 * вопрос «а что с этим делать».
 */
import { lazy, Suspense, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'
import * as workService from '@/services/workService'
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
  const [params] = useSearchParams()
  const companyId = company?.id ?? ''
  // Период раздела. Явные `date_from`/`date_to` в адресе остаются ради ссылок
  // «вернуться к тому же отчёту», но своего регулятора у экрана нет: он один на
  // раздел и стоит в «Рабочем контуре».
  const dateFrom = params.get('date_from') ?? scope.period.from
  const dateTo = params.get('date_to') ?? scope.period.to
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
  // Имена для разреза по ответственным: в реестре лежит только идентификатор.
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId && view === 'docs',
    staleTime: 5 * 60 * 1000,
  })
  const calendarQ = useQuery({
    queryKey: ['calendar-summary', companyId, dateFrom, dateTo],
    queryFn: () => workService.calendarSummary(companyId, dateFrom, dateTo),
    enabled: !!companyId && view === 'calendar' && !dateError,
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

  // Разрезы журнала. Считаются по уже загруженному реестру периода: ходить за
  // ними в базу незачем, а расхождение с цифрой «всего» стало бы возможным.
  const разрезы = useMemo(() => {
    const docs = listQ.data?.docs ?? []
    const имена = new Map((peopleQ.data?.people ?? []).map((p) => [p.id, p.name]))
    const собрать = (ключ: (d: docsService.DocCard) => [string, string] | null) => {
      const acc = new Map<string, { key: string; label: string; count: number }>()
      for (const d of docs) {
        const пара = ключ(d)
        if (!пара) continue
        const [k, label] = пара
        const строка = acc.get(k) ?? { key: k, label, count: 0 }
        строка.count += 1
        acc.set(k, строка)
      }
      return [...acc.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    }
    return {
      kinds: собрать((d) => (d.kind_id ? [d.kind_id, d.kind_name] : null)),
      orgs: собрать((d) => (d.organization_name
        ? [d.organization_name, d.organization_name] : null)),
      parties: собрать((d) => (d.counterparty_name
        ? [d.counterparty_name, d.counterparty_name] : null)),
      people: собрать((d) => (d.responsible_id
        ? [d.responsible_id, имена.get(d.responsible_id) ?? 'не из состава'] : null)),
      sources: собрать((d) => [d.source || 'manual', DOC_SOURCE[d.source] ?? d.source]),
    }
  }, [listQ.data, peopleQ.data])

  if (view === 'errands') {
    return (
      <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Загрузка…</div>}>
        <TasksOverviewPage />
      </Suspense>
    )
  }
  if (view === 'calendar') {
    return <Meetings report={calendarQ.data} loading={calendarQ.isLoading}
      failed={calendarQ.isError} error={calendarQ.error}
      retry={() => calendarQ.refetch()} dateError={dateError}
      dateFrom={dateFrom} dateTo={dateTo} />
  }
  if (view === 'discipline') {
    return <Discipline report={disciplineQ.data} loading={disciplineQ.isLoading}
      fetching={disciplineQ.isFetching} failed={disciplineQ.isError}
      retry={() => disciplineQ.refetch()} dateError={dateError}
      dateFrom={dateFrom} dateTo={dateTo} />
  }

  const columns = boardQ.data?.columns ?? []
  // Список открывается тем же периодом, каким посчитана цифра: иначе реестр
  // покажет другое число, и человек будет искать, кто из двух врёт.
  const вРеестр = (extra: Record<string, string>) => `/docs?${new URLSearchParams({
    view: 'all', date_from: dateFrom, date_to: dateTo, ...extra,
  }).toString()}`
  // «Без согласования» — не шаг маршрута, а его отсутствие: маршрут не
  // запускали. В карточке про визы такая строка перевешивала все настоящие.
  const безМаршрута = columns.find((c) => c.key === 'no_route')
  const шагиМаршрута = columns.filter((c) => c.key !== 'no_route')

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
        <MetricTile label="Без номера" value={stats.draft}
          hint="заведены, но не зарегистрированы"
          onClick={stats.draft > 0
            ? () => navigate(вРеестр({ attention: 'unnumbered' })) : undefined} />
        <MetricTile label="На визах" value={stats.approving}
          hint="идёт согласование"
          onClick={stats.approving > 0
            ? () => navigate(вРеестр({ attention: 'pending' })) : undefined} />
        <MetricTile label="Возвращены" value={stats.returned}
          hint="отказ с замечанием, ждут доработки"
          tone={stats.returned > 0 ? 'warning' : undefined}
          onClick={stats.returned > 0
            ? () => navigate(вРеестр({ attention: 'returned' })) : undefined} />
        <MetricTile label="Просрочены" value={stats.overdue}
          hint="срок исполнения прошёл"
          tone={stats.overdue > 0 ? 'danger' : undefined}
          onClick={stats.overdue > 0
            ? () => navigate(вРеестр({ attention: 'overdue' })) : undefined} />
      </div>

      <Card className="gap-1.5 p-4">
        <div className="text-sm font-medium">По потокам</div>
        <p className="text-xs text-muted-foreground">
          Разрезы журнала: строка открывает свой раздел «Документов»
        </p>
        <div className="mt-2 space-y-0.5">
          {stats.byFamily.map(([family, count]) => (
            <Link key={family} to={`/docs?${new URLSearchParams({
              view: family, date_from: dateFrom, date_to: dateTo }).toString()}`}
              className="-mx-1.5 flex items-center justify-between rounded px-1.5 py-1 text-[13px] transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="text-muted-foreground">
                {DOC_FAMILY[family] ?? family}
              </span>
              <span className="font-medium tabular-nums">{count}</span>
            </Link>
          ))}
          {stats.byFamily.length === 0 && (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Документов пока нет
            </div>
          )}
        </div>
      </Card>

      <Card className="gap-1.5 p-4">
        <div className="text-sm font-medium">Где стоят визы</div>
        <p className="text-xs text-muted-foreground">
          Строка — шаг маршрута. Вопрос «где документ застрял» это вопрос о шаге
          и о том, кого ждут.
        </p>
        <div className="mt-2 space-y-0.5">
          {шагиМаршрута.map((c) => (
            <div key={c.key} className="flex items-center justify-between text-[13px]">
              <span className="text-muted-foreground">{c.name}</span>
              <span className="font-medium tabular-nums">{c.docs.length}</span>
            </div>
          ))}
          {шагиМаршрута.length === 0 && (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Ни один документ сейчас не в маршруте согласования
            </div>
          )}
        </div>
        {!!безМаршрута?.docs.length && (
          <p className="mt-3 border-t border-border/60 pt-2 text-xs text-muted-foreground">
            Ещё {безМаршрута.docs.length}: маршрут согласования не запускали —
            это не шаг, а его отсутствие
          </p>
        )}
        <Link to="/docs/company?view=docs"
          className="mt-3 inline-block text-xs text-primary hover:underline">
          Открыть согласование целиком
        </Link>
      </Card>

      {/* Разрезы журнала: то, чем делопроизводство меряет свой месяц. Строка
          ведёт в реестр с этим же отбором — общее правило раздела. */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Разрез title="По видам" hint="вид задаёт нумерацию и маршрут"
          rows={разрезы.kinds} link={(r) => вРеестр({ kind: r.key })} />
        <Разрез title="По юрлицам" hint="от чьего имени ведётся переписка"
          rows={разрезы.orgs} />
        <Разрез title="По корреспондентам" hint="с кем идёт переписка"
          rows={разрезы.parties} link={(r) => вРеестр({ q: r.label })} />
        <Разрез title="По ответственным" hint="за кем закреплён документ"
          rows={разрезы.people}
          empty="Ответственные не назначены" />
        <Разрез title="Откуда пришли" hint="заведён руками, принят из почты или СЭД"
          rows={разрезы.sources} />
      </div>
      </>}
    </div>
  )
}

function Discipline({ report, loading, fetching, failed, retry, dateError,
  dateFrom, dateTo }: {
  report: docsService.ApprovalDisciplineReport | undefined
  loading: boolean
  fetching: boolean
  failed: boolean
  retry: () => void
  dateError: string
  dateFrom: string
  dateTo: string
}) {
  const navigate = useNavigate()
  const summary = report?.summary
  const estimated = report?.people.reduce((sum, row) => sum + row.estimated_decisions, 0) ?? 0
  /** Показатель — вход в список: без перехода отчёт отвечает «сколько» и не даёт
   *  ответить «что с этим делать». Ноль ведёт никуда: за ним нечего показывать. */
  const вход = (сколько: number, куда: () => string) =>
    (сколько > 0 ? () => navigate(куда()) : undefined)
  return (
    <div className="flex flex-col gap-4 px-4 py-4" aria-busy={loading || fetching}>
      <div>
        <h1 className="text-base font-semibold">Исполнительская дисциплина</h1>
        <p id="discipline-period-hint" className="max-w-3xl text-xs text-muted-foreground">
          Период раздела ({formatPeriod(dateFrom, dateTo)}) отбирает документы по
          первому запуску согласования, московское время. Текущие ожидания и
          просрочки показываются по всей компании вне периода.
        </p>
      </div>

      {fetching && report && (
        <span className="text-xs text-muted-foreground" aria-live="polite">
          Обновляем данные…
        </span>
      )}

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
        {/* Слева — что случилось за период, справа — что происходит сейчас.
            Раньше семь плиток шли одним рядом, и «Сейчас просрочено» читалось
            как часть той же воронки, хотя это другой момент времени. */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Запущено в период" value={summary?.documents ?? 0}
            hint={formatPeriod(report.period.date_from, report.period.date_to)}
            onClick={вход(summary?.documents ?? 0, () => disciplineDetailUrl(report, 'started'))} />
          <MetricTile label="Завершено" value={summary?.completed ?? 0}
            hint="финально согласовано"
            onClick={вход(summary?.completed ?? 0, () => disciplineDetailUrl(report, 'completed'))} />
          <MetricTile label="Возвращено" value={summary?.returned ?? 0}
            hint="последний круг отклонён"
            tone={(summary?.returned ?? 0) > 0 ? 'warning' : undefined}
            onClick={вход(summary?.returned ?? 0, () => disciplineDetailUrl(report, 'returned'))} />
          <MetricTile label="Отменено" value={summary?.cancelled ?? 0}
            hint="нет положительного исхода"
            onClick={вход(summary?.cancelled ?? 0, () => disciplineDetailUrl(report, 'cancelled'))} />
        </div>

        <div>
          <div className="pb-1.5 text-xs text-muted-foreground">
            Сейчас, вне периода — на {formatAsOf(report.backlog.as_of)}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <MetricTile label="Сейчас ждут" value={report.backlog.pending}
              hint="вся очередь виз компании сейчас"
              onClick={вход(report.backlog.pending, () => '/docs/company?view=docs&pending=1')} />
            <MetricTile label="Сейчас просрочено" value={report.backlog.overdue}
              hint="активная виза позже SLA"
              tone={report.backlog.overdue > 0 ? 'danger' : undefined}
              onClick={вход(report.backlog.overdue, () => '/docs/company?view=docs&overdue=1')} />
            <MetricTile label="С первого круга"
              value={(summary?.first_pass_sample ?? 0) > 0 ? `${summary?.first_pass_rate}%` : '—'}
              hint={(summary?.first_pass_sample ?? 0) > 0
                ? `${summary?.first_pass_documents} из ${summary?.first_pass_sample} за период`
                : 'нет завершённых первых кругов'}
              onClick={вход(summary?.first_pass_documents ?? 0,
                () => disciplineDetailUrl(report, 'first_pass'))} />
          </div>
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

/** Откуда документ взялся. Слово вместо кода: `edo` в отчёте не читается. */
const DOC_SOURCE: Record<string, string> = {
  manual: 'заведён руками',
  intake: 'принят из потока',
  mail: 'пришёл почтой',
  chat: 'создан из чата',
  edo: 'принят из СЭД',
  api: 'заведён программой',
}

/** Разрез журнала: строки со счётчиком, каждая — вход в реестр.
 *
 *  Хвост сворачивается: разрез из сорока корреспондентов перестаёт отвечать на
 *  вопрос «с кем мы в основном переписываемся» и становится вторым реестром.
 */
function Разрез({ title, hint, rows, link, empty = 'Данных за период нет', limit = 7 }: {
  title: string
  hint: string
  rows: { key: string; label: string; count: number }[]
  link?: (row: { key: string; label: string; count: number }) => string
  empty?: string
  limit?: number
}) {
  const [весь, показать] = useState(false)
  const видимые = весь ? rows : rows.slice(0, limit)
  return (
    <Card className="gap-1.5 p-4">
      <div className="text-sm font-medium">{title}</div>
      <p className="text-xs text-muted-foreground">{hint}</p>
      <div className="mt-1 space-y-0.5">
        {видимые.map((r) => (
          link ? (
            <Link key={r.key} to={link(r)}
              className="-mx-1.5 flex items-center justify-between gap-3 rounded px-1.5 py-1 text-[13px] transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="min-w-0 truncate text-muted-foreground">{r.label}</span>
              <span className="font-medium tabular-nums">{r.count}</span>
            </Link>
          ) : (
            <div key={r.key} className="flex items-center justify-between gap-3 px-1.5 py-1 text-[13px]">
              <span className="min-w-0 truncate text-muted-foreground">{r.label}</span>
              <span className="font-medium tabular-nums">{r.count}</span>
            </div>
          )
        ))}
        {rows.length === 0 && (
          <div className="py-3 text-center text-sm text-muted-foreground">{empty}</div>
        )}
      </div>
      {rows.length > limit && (
        <button type="button" onClick={() => показать((v) => !v)}
          className="mt-1 self-start text-xs text-primary hover:underline">
          {весь ? 'Свернуть' : `Ещё ${rows.length - limit}`}
        </button>
      )}
    </Card>
  )
}

/** Отчёт по встречам: третий вид работы «Трека».
 *
 *  Час участия и час встречи — разные величины: совещание на пятерых стоит
 *  компании пять человеко-часов, и в разрезе по людям это пять строк. Экран
 *  говорит это словами, иначе сумма по столбцу не сойдётся с итогом сверху.
 */
function Meetings({ report, loading, failed, error, retry, dateError, dateFrom, dateTo }: {
  report: workService.CalendarSummary | undefined
  loading: boolean
  failed: boolean
  error: unknown
  retry: () => void
  dateError: string
  dateFrom: string
  dateTo: string
}) {
  const t = report?.totals
  return (
    <div className="flex flex-col gap-4 px-4 py-4" aria-busy={loading}>
      <div>
        <h1 className="text-base font-semibold">Встречи</h1>
        <p className="max-w-3xl text-xs text-muted-foreground">
          Период раздела ({formatPeriod(dateFrom, dateTo)}) отбирает встречи,
          пересекающиеся с ним. Считается общий календарь компании: закрытые и
          личные встречи в отчёт не входят.
        </p>
      </div>

      {dateError && <Card role="alert" className="p-4 text-sm text-destructive">{dateError}</Card>}
      {failed && !dateError && (
        <DocsErrorState error={error} title="Сводка по встречам не загрузилась"
          detail="Часы не заменены нулями: показать «0 ч» там, где встречи были, хуже, чем не показать ничего."
          onRetry={retry} />
      )}
      {loading && !report && !dateError && (
        <DocsLoadingState>Считаем встречи и участие…</DocsLoadingState>
      )}

      {report && !dateError && !failed && <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Встреч" value={t?.events ?? 0}
            hint={t?.all_day ? `из них на весь день: ${t.all_day}` : 'за период'} />
          <MetricTile label="Часов" value={t?.hours ?? 0}
            hint="без событий на весь день" />
          <MetricTile label="Отменено" value={t?.cancelled ?? 0}
            hint="встреча была назначена и снята"
            tone={t?.cancelled ? 'warning' : undefined} />
          <MetricTile label="Ждут ответа" value={t?.awaiting ?? 0}
            hint="приглашения на будущие встречи"
            tone={t?.awaiting ? 'warning' : undefined} />
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Кто сколько во встречах</CardTitle>
              <CardDescription>
                Участие, а не занятость: совещание на пятерых даёт пять строк
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="min-w-[440px] w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr><th scope="col" className="pb-2 text-left font-medium">Человек</th>
                      <th scope="col" className="pb-2 text-right font-medium">Встреч</th>
                      <th scope="col" className="pb-2 text-right font-medium">Часов</th>
                      <th scope="col" className="pb-2 text-right font-medium">Отказов</th></tr>
                  </thead>
                  <tbody>
                    {report.by_person.map((row) => (
                      <tr key={row.id} className="border-t border-border">
                        <td className="max-w-64 break-words py-2 pe-3">{row.name}</td>
                        <td className="py-2 text-right tabular-nums">{row.events}</td>
                        <td className="py-2 text-right font-medium tabular-nums">{row.hours}</td>
                        <td className="py-2 text-right tabular-nums">{row.declined || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!report.by_person.length && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  За период встреч с участниками не было
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Кто собирает</CardTitle>
              <CardDescription>
                Организаторы: сколько встреч назначено и на сколько часов
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-0.5">
                {report.by_organizer.map((row) => (
                  <div key={row.id ?? row.name}
                    className="flex items-center justify-between gap-3 py-1 text-[13px]">
                    <span className="min-w-0 truncate text-muted-foreground">{row.name}</span>
                    <span className="tabular-nums">
                      {row.events} · <span className="font-medium">{row.hours} ч</span>
                    </span>
                  </div>
                ))}
                {!report.by_organizer.length && (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    За период никто не собирал встреч
                  </p>
                )}
              </div>
              {report.awaiting.length > 0 && (
                <div className="mt-4 border-t border-border/60 pt-3">
                  <div className="text-xs font-medium">Не ответили на приглашение</div>
                  <p className="pb-1 text-xs text-muted-foreground">
                    Только будущие встречи: по прошедшим спрашивать поздно
                  </p>
                  {report.awaiting.map((row) => (
                    <div key={row.id} className="flex items-center justify-between py-0.5 text-[13px]">
                      <span className="truncate text-muted-foreground">{row.name}</span>
                      <span className="font-medium tabular-nums">{row.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </>}
    </div>
  )
}

export default DocsOverviewPage
