import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, CalendarDays, Eye, ListChecks, Loader2, MessagesSquare, RefreshCw, Search } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/common/EmptyState'
import {
  getManagementOverview, managementAvailable, managementQueryKey, ManagementError,
  type ManagementItem, type ManagementKind, type ManagementParams, type ManagementSource,
} from '@/services/managementService'
import { initialManagementPeriod, managementDate, managementDateTimestamp, managementStatusLabel, managementTimeZone, safeManagementHref, validManagementPeriod } from './management/managementHelpers'
import { useManagementStatus } from './management/useManagementStatus'

const VIEWS = [
  { kind: 'chats', title: 'Чаты', icon: MessagesSquare },
  { kind: 'tasks', title: 'Задачи', icon: ListChecks },
  { kind: 'calendar', title: 'Календарь', icon: CalendarDays },
] as const
const SOURCE_STATES: Record<ManagementSource['state'], string> = {
  ok: 'Получено', error: 'Не удалось получить данные', forbidden: 'Доступ не предоставлен',
  not_configured: 'Подключение не настроено',
}

function ManagementRow({ item, timeZone }: { item: ManagementItem; timeZone: string }) {
  const href = safeManagementHref(item.href)
  const statusLabel = managementStatusLabel(item.kind, item.status)
  return <li className="flex min-w-0 flex-col gap-2 border-b border-border p-4 last:border-0 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {href ? <a href={href} className="min-w-0 break-words text-sm font-medium text-foreground underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {item.title || 'Без названия'}<ArrowUpRight className="ml-1 inline size-4" aria-hidden="true" />
        </a> : <span className="break-words text-sm font-medium">{item.title || 'Без названия'}</span>}
        {item.kind === 'chats' && (item.unread_count ?? 0) > 0
          ? <Badge variant="secondary">Непрочитано: {item.unread_count}</Badge> : null}
      </div>
      <p className="break-words text-xs text-muted-foreground">{item.source.name} · {item.source.company_name}</p>
      {item.subtitle && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{item.subtitle}</p>}
      {(item.author_name || item.assignee_name || item.project_name) && <p className="break-words text-xs text-muted-foreground">
        {[item.project_name, item.author_name && `Автор: ${item.author_name}`, item.assignee_name && `Исполнитель: ${item.assignee_name}`].filter(Boolean).join(' · ')}
      </p>}
      {!href && <p className="text-xs text-muted-foreground">Ссылка на оригинал недоступна</p>}
    </div>
    <div className="flex shrink-0 flex-col gap-1.5 text-xs text-muted-foreground sm:max-w-72 sm:items-end sm:text-right">
      {statusLabel && <span className="break-words text-foreground">{statusLabel}</span>}
      {item.kind === 'calendar' && item.starts_at && <p>Начало: {managementDate(item.starts_at, timeZone)}</p>}
      {item.kind === 'calendar' && item.ends_at && <p>Окончание: {managementDate(item.ends_at, timeZone)}</p>}
      {item.due_at && <p>Срок: {managementDate(item.due_at, timeZone)}</p>}
      {item.kind === 'calendar' && !item.starts_at && !item.due_at && <p>Дата не указана</p>}
      {item.updated_at && <p>Изменено: {managementDate(item.updated_at, timeZone)}</p>}
    </div>
  </li>
}

function SourceStatus({ sources, timeZone }: { sources: ManagementSource[]; timeZone: string }) {
  return <details className="rounded-lg border border-border bg-card">
    <summary className="cursor-pointer px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      Источники: {sources.length} · С данными: {sources.filter((s) => s.state === 'ok').length}
    </summary>
    <ul className="border-t border-border px-4">
      {sources.map((source) => <li key={source.code} className="flex flex-col gap-1 border-b border-border py-3 text-xs last:border-0 sm:flex-row sm:justify-between sm:gap-4">
        <span className="break-words font-medium">{source.name}</span>
        <span className="flex flex-col gap-1 text-muted-foreground sm:text-right">
          <span>{SOURCE_STATES[source.state]}{source.truncated ? ' · Выдача ограничена' : ''}</span>
          <span>Получено: {managementDate(source.fetched_at, timeZone)}</span>
        </span>
      </li>)}
    </ul>
  </details>
}

/** Ключ remount сбрасывает отбор до первого запроса новой компании, без кадра старых данных. */
export function ManagementOverviewPage() {
  const { companyId } = useCompany()
  const { user } = useAuth()
  return <ManagementOverview key={`${user?.id}:${companyId}`} companyId={companyId} userId={user?.id ?? ''} />
}

function ManagementOverview({ companyId, userId }: { companyId: string; userId: string }) {
  const qc = useQueryClient()
  const [denial, setDenial] = useState<{ key: string; error: ManagementError } | null>(null)
  const [timeZone] = useState(() => managementTimeZone())
  const [period, setPeriod] = useState(() => initialManagementPeriod(timeZone))
  const [kind, setKind] = useState<ManagementKind>('chats')
  const [space, setSpace] = useState('all')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const isCalendar = kind === 'calendar'
  const periodValid = !isCalendar || validManagementPeriod(period.from, period.to)
  const params: ManagementParams = {
    kind, space, query, limit: 100,
    ...(isCalendar ? { date_from: period.from, date_to: period.to, time_zone: timeZone } : {}),
  }
  const available = managementAvailable()
  const status = useManagementStatus()
  const requestKey = JSON.stringify(managementQueryKey(companyId, userId, params))
  const denied = denial?.key === requestKey ? denial : null
  const overview = useQuery({
    queryKey: managementQueryKey(companyId, userId, params),
    queryFn: async () => {
      try { return await getManagementOverview(params) } catch (error) {
        if (error instanceof ManagementError && [401, 403, 404].includes(error.status)) {
          setDenial({ key: requestKey, error })
        }
        throw error
      }
    },
    enabled: available && status.data?.enabled === true && !status.isError && !denied && !!companyId && !!userId && periodValid,
    gcTime: 0, staleTime: 0, retry: false, placeholderData: undefined,
  })
  const accessError = overview.error instanceof ManagementError && [401, 403, 404].includes(overview.error.status)
    ? overview.error : null
  useEffect(() => {
    if (accessError || status.isError || (status.isSuccess && !status.data.enabled)) {
      qc.removeQueries({ queryKey: ['management-overview', companyId, userId] })
    }
  }, [accessError, requestKey, status.isError, status.isSuccess, status.data?.enabled, companyId, userId, qc])
  const error = denied?.error ?? overview.error
  const snapshot = status.data?.enabled && !status.isError && !accessError && !denied ? overview.data : undefined
  const data = snapshot?.enabled ? snapshot : undefined
  const sources = data?.sources ?? []
  const failed = sources.filter((s) => s.state !== 'ok')
  const hasHealthy = sources.some((s) => s.state === 'ok')
  const truncated = data?.truncated || sources.some((s) => s.truncated)
  const items = data?.items.filter((item) => item.kind === kind) ?? []
  const view = VIEWS.find((v) => v.kind === kind)!
  const resetFilters = () => { setSpace('all'); setQuery(''); setSearch('') }
  const submit = (event: FormEvent) => { event.preventDefault(); setQuery(search.trim()) }
  const retryOverview = () => { if (denied) setDenial(null); else void overview.refetch() }
  const refresh = async () => {
    const checked = await status.refetch()
    if (!checked.error && checked.data?.enabled) retryOverview()
  }
  const calendarGroups = [
    { title: 'Встречи', items: items.filter((item) => item.starts_at) },
    { title: 'Сроки', items: items.filter((item) => !item.starts_at && item.due_at) },
    { title: 'Без даты', items: items.filter((item) => !item.starts_at && !item.due_at) },
  ]

  return <section className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-5 pb-4" aria-labelledby="management-title">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex min-w-0 flex-col gap-2">
        <h1 id="management-title" className="font-headline text-lg font-semibold">Управляющее пространство</h1>
        <p className="text-sm text-muted-foreground">Чаты, задачи и календарь доступных вам пространств.</p>
        <Badge variant="outline"><Eye aria-hidden="true" />Только просмотр</Badge>
      </div>
      <Button variant="outline" disabled={!available || !companyId || !periodValid || overview.isFetching || status.isFetching}
        onClick={() => void refresh()}>
        {overview.isFetching ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
        Обновить
      </Button>
    </header>

    <Tabs value={kind} onValueChange={(value) => setKind(value as ManagementKind)} className="gap-4">
      <TabsList className="w-full sm:w-fit" aria-label="Разделы обзора">
        {VIEWS.map(({ kind: value, title, icon: Icon }) => <TabsTrigger key={value} value={value}><Icon aria-hidden="true" />{title}</TabsTrigger>)}
      </TabsList>
      <form onSubmit={submit} className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-end" aria-label="Фильтры обзора">
        <div className="flex flex-col gap-1.5 sm:w-56">
          <Label htmlFor="management-space">Пространство</Label>
          <Select value={space} onValueChange={setSpace}>
            <SelectTrigger id="management-space" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup>
              <SelectItem value="all">Все доступные</SelectItem>
              {sources.map((source) => <SelectItem key={source.code} value={source.code}>{source.name}</SelectItem>)}
              {space !== 'all' && !sources.some((s) => s.code === space) && <SelectItem value={space}>Выбранное пространство</SelectItem>}
            </SelectGroup></SelectContent>
          </Select>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <Label htmlFor="management-search">Поиск</Label>
          <Input id="management-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск по названию" />
        </div>
        <Button type="submit" variant="outline"><Search aria-hidden="true" />Найти</Button>
        {(query || space !== 'all') && <Button type="button" variant="outline" onClick={resetFilters}>Сбросить</Button>}
      </form>
      {isCalendar && <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-0 flex-col gap-1.5"><Label htmlFor="management-from">С даты</Label>
            <Input id="management-from" type="date" value={period.from} aria-invalid={!periodValid} aria-describedby="management-period-note"
              onChange={(event) => setPeriod((p) => ({ ...p, from: event.target.value }))} /></div>
          <div className="flex min-w-0 flex-col gap-1.5"><Label htmlFor="management-to">По дату включительно</Label>
            <Input id="management-to" type="date" value={period.to} aria-invalid={!periodValid} aria-describedby="management-period-note"
              onChange={(event) => setPeriod((p) => ({ ...p, to: event.target.value }))} /></div>
        </div>
        <p id="management-period-note" className="text-xs text-muted-foreground">
          {periodValid ? `Период включает обе даты. Даты и время: ${timeZone}.` : 'Укажите обе даты. Дата окончания должна быть не раньше начала.'}
        </p>
      </div>}
      <TabsContent value={kind} className="flex flex-col gap-4" aria-busy={overview.isFetching}>
        {!available ? <EmptyState icon={view.icon} title="Обзор не подключён"
          description="Для просмотра нужен вход в пространство с подключённым API. Подключение ведёт администратор." />
          : !companyId ? <EmptyState icon={view.icon} title="Выберите организацию" description="Выберите доступную организацию в шапке пространства." />
            : status.isPending ? <p role="status" className="text-sm text-muted-foreground">Проверяем доступность обзора…</p>
              : status.isError ? <EmptyState icon={view.icon} title="Не удалось проверить доступность обзора" description="Повторите запрос. Настройки подключения не изменятся."
                action={{ label: 'Повторить', onClick: () => { void status.refetch() } }} />
                : !status.data?.enabled ? <EmptyState icon={view.icon} title="Обзор отключён" description="Управляющее пространство отключено администратором. После включения обновите обзор." />
            : !periodValid ? null
              : overview.isPending && !error ? <div role="status" aria-label="Загрузка обзора" className="flex flex-col gap-3"><span className="text-sm text-muted-foreground">Получаем обзор…</span>{[0, 1, 2].map((n) => <Skeleton key={n} className="h-20 w-full" />)}</div>
                : <>
                  {error && <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-border bg-card p-4">
                    <p className="text-sm">{error.message}</p>
                    {data && <p className="text-xs text-muted-foreground">Показан предыдущий ответ. Сведения могли измениться.</p>}
                    <Button variant="outline" disabled={overview.isFetching} onClick={retryOverview}>Повторить</Button>
                  </div>}
                  {snapshot && !snapshot.enabled ? <EmptyState icon={view.icon} title="Обзор отключён" description="Управляющее пространство отключено администратором. После включения обновите обзор." />
                    : data && <>
                      {failed.length > 0 && <div role="status" className="rounded-lg border border-border bg-card p-4 text-sm">
                        <p className="font-medium">{hasHealthy ? 'Часть источников недоступна' : 'Источники недоступны'}</p>
                        <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">{failed.map((source) => <li key={source.code}>{source.name}: {SOURCE_STATES[source.state]}</li>)}</ul>
                      </div>}
                      {truncated && <p role="status" className="text-sm text-muted-foreground">Показана часть результатов. Сузьте поиск, пространство или период.</p>}
                      {sources.length > 0 && <SourceStatus sources={sources} timeZone={timeZone} />}
                      {sources.length === 0 ? <EmptyState icon={view.icon} title="Нет подключённых источников" description="Подключение источников ведёт администратор пространства." />
                        : items.length === 0 ? <EmptyState icon={view.icon} title={failed.length ? 'В доступной части обзора записей нет' : 'Записей не найдено'}
                          description={query || space !== 'all' ? 'Измените поиск или выберите другое пространство.' : 'По выбранным условиям источники не вернули записей.'} />
                          : <div className="flex flex-col gap-4">
                            <p className="text-xs text-muted-foreground">В ответе: {items.length}{truncated || failed.length ? ' · Неполная выдача' : ''} · Получено: {managementDate(data.fetched_at, timeZone)} · {timeZone}</p>
                            {isCalendar ? calendarGroups.filter((g) => g.items.length).map((group) => <section key={group.title} className="overflow-hidden rounded-lg border border-border bg-card">
                              <h2 className="border-b border-border px-4 py-3 text-sm font-semibold">{group.title}</h2>
                              <ul>{[...group.items].sort((a, b) => managementDateTimestamp(a.starts_at || a.due_at) - managementDateTimestamp(b.starts_at || b.due_at)).map((item) => <ManagementRow key={item.id} item={item} timeZone={timeZone} />)}</ul>
                            </section>) : <ul className="overflow-hidden rounded-lg border border-border bg-card">{items.map((item) => <ManagementRow key={item.id} item={item} timeZone={timeZone} />)}</ul>}
                          </div>}
                    </>}
                </>}
      </TabsContent>
    </Tabs>
  </section>
}
