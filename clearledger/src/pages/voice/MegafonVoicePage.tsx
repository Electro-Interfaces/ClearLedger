import { VOICE_MEGAFON_TABS } from './views'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, PhoneCall, RefreshCw, Search } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ViewParamsBar } from '@/components/workspace/ViewParamsBar'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import {
  getMegafonCall, getMegafonVoice, megafonParamsFromUrl, megafonPeriodBounds,
  type MegafonCall, type MegafonPeriod, type MegafonVoiceData,
} from '@/services/megafonVoiceService'

const VIEWS = VOICE_MEGAFON_TABS
const PERIODS = [{ value: 'today', label: 'Сегодня' }, { value: '7d', label: '7 дней' }, { value: '30d', label: '30 дней' }]
// Пустое значение — реальный отбор «не указан»; отсутствие параметра — все значения.
const ALL = '__megafon_all__'
const DATE = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
const NUMBER = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const dateTime = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? DATE.format(new Date(value)) : '—'
const count = (value: number | null) => value == null ? '—' : NUMBER.format(value)
const seconds = (value: number | null) => value == null ? '—' : `${NUMBER.format(value)} с`
const direction = (value: MegafonCall['direction']) => value === 'inbound' ? 'Входящий' : value === 'outbound' ? 'Исходящий' : '—'

export default function MegafonVoicePage({ section }: { section?: 'calls' | 'stats' }) {
  const { companyId } = useCompany()
  return <MegafonCompanyPage key={companyId} companyId={companyId} section={section} />
}

function MegafonCompanyPage({ companyId, section }: { companyId: string; section?: 'calls' | 'stats' }) {
  const [url, setUrl] = useSearchParams()
  const [anchor] = useState(() => new Date())
  const params = megafonParamsFromUrl(url, anchor)
  const companyChanged = url.has('voice_company') && url.get('voice_company') !== companyId
  const selected = companyChanged ? null : url.get('call')
  const view = VIEWS.some(item => item.k === url.get('view')) ? url.get('view')! : section === 'stats' ? 'operators' : 'calls'
  const requestedPeriod = url.get('period')
  const expectedPeriod = megafonPeriodBounds(requestedPeriod === '7d' || requestedPeriod === '30d' ? requestedPeriod : 'today', anchor)
  const period = params.from === expectedPeriod.from && params.to === expectedPeriod.to ? requestedPeriod ?? 'today' : 'custom'
  const [searchDraft, setSearchDraft] = useState(url.get('search') ?? '')
  const digits = searchDraft.replace(/\D/g, '')
  const invalidSearch = !!searchDraft.trim() && digits.length < 4
  const invalidUrlSearch = !!url.get('search') && (url.get('search') ?? '').replace(/\D/g, '').length < 4

  // Фиксируем фактический интервал: карточка, reload и «Назад» сохраняют выборку.
  useEffect(() => {
    if (!companyId) return
    // При переключении источника старый экран ещё может завершать эффект.
    // Явный выбор узла нельзя переписать нормализацией URL истории.
    if (section && url.get('source') === 'node') return
    if (url.get('from') === params.from && url.get('to') === params.to && url.get('voice_company') === companyId && (!section || url.get('source') === 'megafon')) return
    const next = new URLSearchParams(url)
    next.set('voice_company', companyId)
    if (section) next.set('source', 'megafon')
    if (companyChanged) {
      for (const key of ['operator', 'group', 'line', 'missed', 'direction', 'search', 'page', 'call']) next.delete(key)
    }
    next.set('from', params.from)
    next.set('to', params.to)
    setUrl(next, { replace: true })
  }, [url, setUrl, params.from, params.to, companyId, companyChanged, section])
  const urlSearch = url.get('search') ?? ''
  useEffect(() => { setSearchDraft(urlSearch) }, [urlSearch])

  const query = useQuery({
    queryKey: ['voice-megafon', companyId, params],
    queryFn: () => getMegafonVoice(companyId, params),
    enabled: !!companyId && !companyChanged && !invalidUrlSearch,
    refetchInterval: state => Math.max(30, state.state.data?.connection.poll_interval_seconds ?? 300) * 1000,
    retry: false,
  })
  const data = query.data
  function change(values: Record<string, string | null>, resetPage = true) {
    setUrl(previous => {
      const next = new URLSearchParams(previous)
      for (const [key, value] of Object.entries(values)) {
        if (value !== null) next.set(key, value)
        else next.delete(key)
      }
      if (resetPage) { next.delete('page'); next.delete('call') }
      return next
    })
  }
  function selectPeriod(value: string) {
    if (value !== 'custom') change({ period: value, ...megafonPeriodBounds(value as MegafonPeriod) })
  }
  function search(event: FormEvent) {
    event.preventDefault()
    if (!invalidSearch) change({ search: digits || null })
  }
  function reset() {
    setSearchDraft('')
    change({ operator: null, group: null, line: null, missed: null, direction: null, search: null })
  }
  const hasFilters = ['operator', 'group', 'line', 'missed', 'direction', 'search'].some(key => url.has(key))
  const filter = (key: string, value: string) => change({ [key]: value === ALL ? null : value })

  return <main className="flex min-w-0 flex-col gap-4 p-3 md:p-5" aria-label={section === 'calls' ? 'Журнал звонков' : section === 'stats' ? 'Статистика' : 'МегаФон ВАТС'}>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="font-headline text-lg font-semibold">{section === 'calls' ? 'Журнал звонков' : section === 'stats' ? 'Статистика' : 'МегаФон ВАТС'}</h1>
        <p className="text-sm text-muted-foreground">{section ? 'МегаФон ВАТС · история звонков и работа операторов' : 'История звонков и работа операторов'}</p>
      </div>
      <Button variant="outline" size="sm" disabled={query.isFetching || invalidUrlSearch || !companyId} onClick={() => void query.refetch()}>
        <RefreshCw data-icon="inline-start" />{query.isFetching ? 'Обновляем…' : 'Обновить'}
      </Button>
    </header>
    <ViewParamsBar label={null}>
      <SelectFilter label="Период" value={period} options={period === 'custom' ? [{ value: 'custom', label: 'Период из ссылки' }, ...PERIODS] : PERIODS} onChange={selectPeriod} />
      <p className="text-xs text-muted-foreground">{dateTime(params.from)} — {dateTime(params.to)} (до, не включая) · {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
    </ViewParamsBar>
    {!companyId ? <p role="status">Выберите компанию в шапке пространства.</p> : null}
    {query.isLoading ? <Loading label="Загружаем историю МегаФона…" /> : null}
    {query.isError ? <ErrorMessage error={query.error} retry={() => void query.refetch()} /> : null}
    {data && !query.isError && !invalidUrlSearch ? <>
      <SourceAndLine data={data} checkedAt={query.dataUpdatedAt} />
      <section aria-label="Сводка за выбранный период" className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        {([
          ['Всего звонков', count(data.summary.total)], ['Входящие', count(data.summary.inbound)],
          ['Исходящие', count(data.summary.outbound)], ['Отвечено', count(data.summary.answered)],
          ['Пропущено', count(data.summary.missed)], ['Среднее ожидание', seconds(data.summary.avg_wait_sec)],
          ['Средний разговор', seconds(data.summary.avg_talk_sec)], ['С записью', count(data.summary.recordings)],
          ['Операторов', count(data.summary.operator_count)],
        ] as const).map(([label, value]) => <div key={label} className="flex min-w-0 flex-col gap-1 rounded-lg border bg-card p-3">
          <span className="text-xs text-muted-foreground">{label}</span><strong className="text-lg font-semibold tabular-nums">{value}</strong>
        </div>)}
      </section>
    </> : null}
    <section aria-label="Фильтры истории" className="flex min-w-0 flex-col gap-2">
      <ViewParamsBar label={null}>
        <SelectFilter label="Оператор" value={params.operator ?? ALL} onChange={value => filter('operator', value)}
          options={filterOptions(data?.filters.operators.map(item => ({ value: item.key === '' ? '' : item.name, label: item.name })), params.operator)} all="Все операторы" />
        <SelectFilter label="Группа" value={params.group ?? ALL} onChange={value => filter('group', value)}
          options={filterOptions(data?.filters.groups.map(item => ({ value: item.key === '' ? '' : item.name, label: item.name })), params.group)} all="Все группы" />
        <SelectFilter label="Линия" value={params.line ?? ALL} onChange={value => filter('line', value)}
          options={filterOptions(data?.filters.lines.map(item => ({ value: item.number, label: [item.name, item.number].filter(Boolean).join(' · ') })), params.line)} all="Все линии" />
        <SelectFilter label="Направление" value={params.direction ?? ALL} onChange={value => filter('direction', value)}
          options={[{ value: 'inbound', label: 'Входящие' }, { value: 'outbound', label: 'Исходящие' }]} all="Все направления" />
        <SelectFilter label="Пропуск" value={params.missed ?? ALL} onChange={value => filter('missed', value)}
          options={[{ value: 'true', label: 'Пропущенные' }, { value: 'false', label: 'Без пропуска' }]} all="Все звонки" />
        {hasFilters ? <Button variant="outline" size="sm" onClick={reset}>Сбросить фильтры</Button> : null}
      </ViewParamsBar>
      <form onSubmit={search} className="flex flex-wrap items-center gap-2">
        <Input aria-label="Поиск по номеру" aria-invalid={invalidSearch} aria-describedby="megafon-search-hint" inputMode="tel"
          value={searchDraft} onChange={event => setSearchDraft(event.target.value)} placeholder="Номер или последние цифры" className="w-full sm:w-72" />
        <Button type="submit" variant="outline" size="sm" disabled={invalidSearch}><Search data-icon="inline-start" />Найти</Button>
        {url.has('search') ? <Button type="button" variant="outline" size="sm" onClick={() => { setSearchDraft(''); change({ search: null }) }}>Снять поиск</Button> : null}
        <p id="megafon-search-hint" className="text-xs text-muted-foreground">Для поиска нужны хотя бы 4 цифры номера.</p>
      </form>
      {invalidUrlSearch ? <p role="alert" className="text-sm text-destructive">В ссылке слишком короткий номер. Введите хотя бы 4 цифры или снимите поиск.</p> : null}
    </section>
    <section aria-label="Данные истории" className="min-w-0">
      <PanelViewTabs tabs={VIEWS} value={view} onChange={value => change({ view: value }, false)} label={null} ariaLabel="Разрезы истории МегаФона" />
      {data && !query.isError && !invalidUrlSearch ? <>
        {view === 'calls' ? <CallJournal data={data} selected={selected} open={id => change({ call: id }, false)} page={params.page}
          setPage={page => change({ page: String(page), call: null }, false)} /> : null}
        {view === 'operators' ? <Operators data={data} /> : null}
        {view === 'groups' ? <Groups data={data} /> : null}
      </> : null}
    </section>
    {selected && companyId ? <CallDialog key={`${companyId}:${selected}`} companyId={companyId} id={selected} close={() => change({ call: null }, false)} /> : null}
  </main>
}

function filterOptions(options: { value: string; label: string }[] = [], selected?: string) {
  const unique = [...new Map(options.map(item => [item.value, item])).values()]
  return selected !== undefined && !unique.some(item => item.value === selected)
    ? [{ value: selected, label: selected || 'Не указан' }, ...unique] : unique
}

function SelectFilter({ label, value, options, onChange, all }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; all?: string
}) {
  return <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2 text-xs text-muted-foreground">
    {label}<select value={value} onChange={event => onChange(event.target.value)} aria-label={label}
      className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-card px-2 text-sm text-foreground sm:max-w-64">
      {all ? <option value={ALL}>{all}</option> : null}
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </label>
}

function SourceAndLine({ data, checkedAt }: { data: MegafonVoiceData; checkedAt: number }) {
  const { connection, line } = data
  const stale = !connection.last_sync_at || !Number.isFinite(Date.parse(connection.last_sync_at))
    || checkedAt - Date.parse(connection.last_sync_at) > connection.poll_interval_seconds * 2 * 1000
  const status = !connection.configured ? 'Не настроено' : ({ active: 'Подключено', paused: 'Приостановлено', not_configured: 'Не настроено', connected: 'Подключено', ok: 'Подключено', error: 'Ошибка', syncing: 'Синхронизация', disconnected: 'Отключено' }[connection.status] ?? 'Состояние уточняется')
  return <div className="grid min-w-0 gap-3 lg:grid-cols-2">
    <Card className="min-w-0 gap-3 py-4">
      <CardHeader className="px-4"><CardTitle>Источник и свежесть</CardTitle><CardDescription>МегаФон ВАТС · история завершённых звонков</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-2 px-4 text-sm">
        <div className="flex flex-wrap items-center gap-2"><Badge variant={connection.last_error ? 'destructive' : 'outline'}>{status}</Badge>
          <Badge variant="outline">{stale ? 'Свежесть не подтверждена' : 'Синхронизация актуальна'}</Badge></div>
        <p>Последняя синхронизация: <span className="tabular-nums">{dateTime(connection.last_sync_at)}</span></p>
        <p className="text-xs text-muted-foreground">Проверка обновлений каждые {count(connection.poll_interval_seconds)} с. Это история, состояния текущих разговоров здесь нет.</p>
        {connection.last_error ? <p role="alert" className="break-words text-destructive">{connection.last_error}</p> : null}
        {!connection.configured ? <p className="text-xs text-muted-foreground">Подключение МегаФона для этой компании ещё не настроено.</p> : null}
      </CardContent>
    </Card>
    <Card className="min-w-0 gap-3 py-4">
      <CardHeader className="px-4"><CardTitle>Линия и переадресация</CardTitle><CardDescription>{line.name || 'Название линии не задано'}</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-2 px-4 text-sm">
        <p>Публичный номер в настройке: <span className="font-mono">{line.public_number || '—'}</span></p>
        <p>Переадресация на: <span className="font-mono">{line.forwarding_number || '—'}</span></p>
        <p className="text-xs text-muted-foreground">Публичный номер указан в настройке переадресации. История МегаФона не содержит исходный номер 8 800 и не подтверждает его для отдельного звонка.</p>
      </CardContent>
    </Card>
  </div>
}

function CallJournal({ data, selected, open, page, setPage }: {
  data: MegafonVoiceData; selected: string | null; open: (id: string) => void; page: number; setPage: (page: number) => void
}) {
  const calls = data.calls
  const pages = Math.max(1, Math.ceil(calls.total / calls.page_size))
  return <div className="flex min-w-0 flex-col gap-3">
    <h2 className="text-sm font-medium">Журнал звонков · {count(calls.total)}</h2>
    {calls.items.length === 0 ? <EmptyBlock иконка={PhoneCall} текст="Звонков по выбранным условиям нет"
      подсказка="Выберите другой период или снимите фильтры. История появится после синхронизации МегаФона." /> :
      <div className="min-w-0 rounded-lg border"><Table aria-label="Журнал звонков МегаФона">
        <TableHeader><TableRow>{['Начало', 'Номер клиента', 'Направление', 'Пропуск', 'Оператор', 'Группа', 'Линия', 'Ожидание', 'Разговор', 'Запись'].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader>
        <TableBody>{calls.items.map(call => <TableRow key={call.id} data-state={selected === call.id ? 'selected' : undefined}>
          <TableCell className="tabular-nums">{dateTime(call.started_at)}</TableCell>
          <TableCell><Button variant="link" size="sm" className="px-0 font-mono" onClick={() => open(call.id)} aria-label={`Открыть звонок ${call.client_phone || call.id}`}>
            {call.client_phone || 'Номер не указан'}
          </Button></TableCell>
          <TableCell>{direction(call.direction)}</TableCell>
          <TableCell><Badge variant={call.missed ? 'destructive' : 'outline'}>{call.missed ? 'Пропущен' : 'Без пропуска'}</Badge></TableCell>
          <TableCell>{call.operator_name || call.operator_login || '—'}</TableCell><TableCell>{call.group_name || '—'}</TableCell>
          <TableCell><span className="font-mono text-xs">{call.line_number || '—'}</span>{call.line_name ? <p className="text-xs text-muted-foreground">{call.line_name}</p> : null}</TableCell>
          <TableCell>{seconds(call.wait_sec)}</TableCell><TableCell>{seconds(call.duration_sec)}</TableCell><TableCell>{call.has_recording ? 'Есть' : 'Нет'}</TableCell>
        </TableRow>)}</TableBody>
      </Table></div>}
    <nav aria-label="Страницы журнала" className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground">Страница {count(page)} из {count(pages)} · по {count(calls.page_size)} звонков</p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft data-icon="inline-start" />Назад</Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Далее<ChevronRight data-icon="inline-end" /></Button>
      </div>
    </nav>
  </div>
}

function Operators({ data }: { data: MegafonVoiceData }) {
  if (!data.operators.length) return <EmptyBlock иконка={PhoneCall} текст="Операторов по выбранным условиям нет" />
  return <div className="min-w-0 rounded-lg border"><Table aria-label="Операторы МегаФона">
    <TableHeader><TableRow>{['Оператор', 'Логин', 'Внутренний', 'Всего', 'Входящие отвеченные', 'Исходящие', 'Пропущено', 'Средний разговор', 'Среднее ожидание'].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader>
    <TableBody>{data.operators.map(operator => <TableRow key={operator.key}>
      <TableCell>{operator.name || 'Без оператора'}</TableCell><TableCell>{operator.login || '—'}</TableCell><TableCell className="font-mono">{operator.extension || '—'}</TableCell>
      <TableCell>{count(operator.total)}</TableCell><TableCell>{count(operator.inbound_answered)}</TableCell><TableCell>{count(operator.outbound)}</TableCell>
      <TableCell>{count(operator.missed)}</TableCell><TableCell>{seconds(operator.avg_talk_sec)}</TableCell><TableCell>{seconds(operator.avg_wait_sec)}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div>
}

function Groups({ data }: { data: MegafonVoiceData }) {
  if (!data.groups.length) return <EmptyBlock иконка={PhoneCall} текст="Групп по выбранным условиям нет" />
  const known = data.groups.filter(group => group.name).reduce((total, group) => total + group.total, 0)
  return <div className="flex min-w-0 flex-col gap-3">
    <p role="note" className="text-sm text-muted-foreground">МегаФон указал группу для {count(known)} из {count(data.summary.total)} звонков в выборке. Остальные отражены в строке «Группа не указана». Эти данные не описывают полную нагрузку смен.</p>
    <div className="min-w-0 rounded-lg border"><Table aria-label="Группы МегаФона">
    <TableHeader><TableRow>{['Группа', 'Всего', 'Отвечено', 'Пропущено'].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader>
    <TableBody>{data.groups.map(group => <TableRow key={group.name}>
      <TableCell>{group.name || 'Группа не указана'}</TableCell><TableCell>{count(group.total)}</TableCell><TableCell>{count(group.answered)}</TableCell><TableCell>{count(group.missed)}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div></div>
}

function CallDialog({ companyId, id, close }: { companyId: string; id: string; close: () => void }) {
  const query = useQuery({ queryKey: ['voice-megafon-call', companyId, id], queryFn: () => getMegafonCall(companyId, id), retry: false })
  const call = query.data?.call
  return <Dialog open onOpenChange={open => { if (!open) close() }}>
    <DialogContent className="flex max-h-[90dvh] w-[calc(100%-1.5rem)] max-w-2xl flex-col overflow-hidden" showCloseButton={false}>
      <DialogHeader className="shrink-0"><DialogTitle>Карточка звонка</DialogTitle><DialogDescription>МегаФон ВАТС · данные истории</DialogDescription></DialogHeader>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
      {query.isLoading ? <Loading label="Загружаем звонок…" /> : null}
      {query.isError ? <ErrorMessage error={query.error} retry={() => void query.refetch()} /> : null}
      {call && !query.isError ? <>
        <dl className="grid min-w-0 gap-x-4 gap-y-3 text-sm sm:grid-cols-2">
          <Fact label="Номер клиента">{call.client_phone}</Fact><Fact label="Начало">{dateTime(call.started_at)}</Fact>
          <Fact label="Направление">{direction(call.direction)}</Fact><Fact label="Пропуск">{call.missed ? 'Да' : 'Нет'}</Fact>
          <Fact label="Оператор">{call.operator_name}</Fact><Fact label="Логин оператора">{call.operator_login}</Fact>
          <Fact label="Группа">{call.group_name}</Fact><Fact label="Линия в истории">{[call.line_name, call.line_number].filter(Boolean).join(' · ')}</Fact>
          <Fact label="Ожидание">{seconds(call.wait_sec)}</Fact><Fact label="Разговор">{seconds(call.duration_sec)}</Fact>
          <Fact label="Запись">{call.has_recording ? 'Есть' : 'Нет'}</Fact><Fact label="Источник">МегаФон ВАТС</Fact>
          <Fact label="Номер звонка в МегаФоне">{call.call_id}</Fact>
        </dl>
        <p className="text-xs text-muted-foreground">Наличие записи показано по истории МегаФона. Прослушивание здесь не подключено. Исходный публичный номер для этого звонка не подтверждён.</p>
      </> : null}
      </div>
      <Button variant="outline" className="shrink-0" onClick={close}>К журналу</Button>
    </DialogContent>
  </Dialog>
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-words">{children || '—'}</dd></div>
}
function Loading({ label }: { label: string }) {
  return <div role="status" className="flex flex-col gap-3"><p className="text-sm">{label}</p><Skeleton className="h-24 w-full" /><Skeleton className="h-16 w-full" /></div>
}
function ErrorMessage({ error, retry }: { error: unknown; retry: () => void }) {
  return <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 p-4">
    <div className="flex min-w-0 flex-col gap-1"><p className="text-sm font-medium">Не удалось загрузить данные МегаФона</p>
      <p className="break-words text-sm text-muted-foreground">{error instanceof Error ? error.message : 'Попробуйте обновить данные.'}</p></div>
    <Button variant="outline" size="sm" onClick={retry}>Повторить</Button>
  </div>
}
