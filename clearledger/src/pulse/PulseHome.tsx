import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ArrowUpRight, CalendarDays, RefreshCw, Settings2, Video, WifiOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EventDialog } from '@/components/calendar/EventDialog'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { useSupportContext } from '@/contexts/SupportContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { useOpenApp } from '@/hooks/useOpenApp'
import { getRooms, isMuted } from '@/services/chatService'
import { getMeetingsConfig } from '@/services/conferenceService'
import { listEvents, myWork, myWorkHref, todayKey, type CalendarEvent } from '@/services/workService'
import { listSsoApps, type SsoApp } from '@/services/ssoService'
import { getPulseDay, type PulseKpi } from './pulseService'
import { KpiTile } from './parts'
import { HOME_SECTIONS, getHomeSettings, saveHomeSettings, type HomeConfig, type HomeSection, type HomeSettings } from './pulseHomeService'
import { availablePulseViews } from './PulseLayout'

const refreshInterval = 60_000
const liveQuery = { staleTime: 30_000, refetchInterval: refreshInterval, refetchOnWindowFocus: true }
const rowClass = 'flex min-h-12 w-full items-center justify-between gap-3 border-b py-3 text-left last:border-0 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

export function PulseHome() {
  const { companyId } = useCompany()
  const { user } = useAuth()
  return <Home key={`${companyId}:${user?.id}`} />
}

function Home() {
  const { company, companyId, canModule, canApp } = useCompany()
  const trackOn = useDocsApp()
  const { open, busy } = useOpenApp()
  const [params] = useSearchParams()
  const [editing, setEditing] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update) }
  }, [])
  const settings = useQuery({ queryKey: ['pulse-home-settings', companyId], queryFn: () => getHomeSettings(companyId), ...liveQuery })
  const catalog = useQuery({ queryKey: ['sso-apps', companyId], queryFn: () => listSsoApps(companyId), staleTime: refreshInterval })
  const apps = (catalog.data?.apps ?? []).filter((app) =>
    !catalog.data?.allowed_apps || catalog.data.allowed_apps.includes(app.code))
  const conferenceOn = canApp('conf')
  const conf = useQuery({ queryKey: ['pulse-conference-config', companyId], queryFn: getMeetingsConfig, enabled: conferenceOn, staleTime: refreshInterval })
  const sections = settings.data?.effective.sections ?? []
  const metricsOn = canModule('pulse', 'today')
  const metrics = useQuery({ queryKey: ['pulse-day', companyId, params.get('as')],
    queryFn: () => getPulseDay(companyId, params.get('as')),
    enabled: metricsOn && (sections.includes('metrics') || editing), ...liveQuery })
  const refresh = () => {
    void settings.refetch()
    void catalog.refetch()
    if (metricsOn && sections.includes('metrics')) void metrics.refetch()
  }
  const available = (section: HomeSection) =>
    !((section === 'work' || section === 'meetings') && !trackOn) && !(section === 'metrics' && !metricsOn)
  const visible = sections.filter(available)

  return <div className="mx-auto max-w-6xl space-y-6 pb-6" data-pulse-home>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-xl font-semibold">Мой пульт</h1>
        <p className="mt-1 break-words text-sm text-muted-foreground">{company.name} · {new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</p>
      </div>
      <Button variant="outline" className="min-h-11 min-w-11 gap-2" disabled={!settings.data || settings.isError}
        onClick={() => setEditing(!editing)} aria-expanded={editing} aria-label={editing ? 'Закрыть настройку' : 'Настроить пульт'}><Settings2 className="size-4" /><span className="hidden sm:inline">{editing ? 'Закрыть настройку' : 'Настроить пульт'}</span></Button>
    </header>
    {!online && <p role="status" className="flex items-start gap-2 rounded-lg border p-3 text-sm"><WifiOff className="size-5 shrink-0" />Нет сети. Показаны последние полученные сведения; действия потребуют подключения.</p>}
    {/* Из четырёх кнопок осталась одна (замечание МАГа 06.09.2026): «Чат», «Трек» и
        «Приложения» стоят в нижней панели пульта и в шапке — второй раз называть их
        здесь значит отодвигать работу вниз. Конференция остаётся: в нижнюю панель
        шестой пункт не влезает, а в мобильной шапке шестая кнопка наезжала на бургер. */}
    {conferenceOn && (
      <nav aria-label="Быстрые действия пульта" className="flex">
        <Button variant="outline" className="min-h-12 justify-start gap-2 sm:w-auto"
          disabled={!online || !conf.data?.enabled || !!busy}
          onClick={() => void open('conf')}><Video className="size-5" />{busy === 'conf' ? 'Создаём…' : 'Конференция'}</Button>
      </nav>
    )}
    {conferenceOn && !conf.isPending && (!conf.data?.enabled || conf.isError) && <p className="text-sm text-muted-foreground">
      {conf.isError ? 'Не удалось проверить доступность конференций.' : 'Конференции пока не настроены в пространстве.'}
      {conf.isError && <Button variant="link" className="min-h-11" onClick={() => void conf.refetch()}>Повторить</Button>}
    </p>}
    <QueryState query={settings} />
    {editing && settings.data && <HomeEditor settings={settings.data} apps={apps} metrics={metrics.data?.kpi ?? []}
      catalogReady={catalog.isSuccess} metricsReady={metrics.isSuccess}
      allowedSections={(Object.keys(HOME_SECTIONS) as HomeSection[]).filter(available)} onClose={() => setEditing(false)} />}
    {settings.data && <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <span>{settings.data.personal ? 'Ваш личный экран' : 'Экран пространства'}</span>
        <Button variant="ghost" className="min-h-11 gap-2" disabled={settings.isFetching || catalog.isFetching} onClick={refresh}><RefreshCw className="size-4" />Обновить настройки</Button>
      </div>
      <div className="grid items-start gap-x-8 gap-y-7 lg:grid-cols-2">
        {visible.map((section) => {
          if (section === 'work') return <WorkBlock key={section} />
          if (section === 'chats') return <ChatsBlock key={section} />
          if (section === 'meetings') return <MeetingsBlock key={section} />
          if (section === 'metrics') return <MetricsBlock key={section} query={metrics} selected={settings.data.effective.metric_keys} />
          return <AppList key={section} query={catalog} favorites={settings.data.effective.favorite_apps} compact />
        })}
      </div>
      {!visible.length && <p className="rounded-lg border p-4 text-sm text-muted-foreground">На пульте оставлены быстрые действия. Добавьте нужные блоки через «Настроить пульт».</p>}
    </>}
    <AnalyticsLinks />
  </div>
}

function QueryState({ query }: { query: Pick<UseQueryResult, 'isPending' | 'isError' | 'isFetching' | 'dataUpdatedAt' | 'refetch'> }) {
  if (query.isPending) return <p role="status" className="py-3 text-sm text-muted-foreground">Загружаем…</p>
  if (query.isError) return <div role="alert" className="py-2 text-sm text-destructive">Не удалось обновить данные.
    {query.dataUpdatedAt > 0 && <span> Ниже — сведения на {new Date(query.dataUpdatedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}.</span>}
    <Button variant="link" className="min-h-11" disabled={query.isFetching} onClick={() => void query.refetch()}>Повторить</Button></div>
  return null
}

function Block({ title, action, query, children }: { title: string; action?: ReactNode; query: UseQueryResult; children: ReactNode }) {
  return <section className="min-w-0" aria-label={title}>
    <div className="flex min-h-11 items-center justify-between gap-2 border-b pb-1"><h2 className="font-semibold">{title}</h2>{action}</div>
    <QueryState query={query} />{children}
    {query.dataUpdatedAt > 0 && <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Получено {new Date(query.dataUpdatedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span>
      <Button variant="ghost" className="min-h-11 px-2" aria-label={`Обновить: ${title}`} disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw className="size-4" /></Button>
    </div>}
  </section>
}

function WorkBlock() {
  const { companyId } = useCompany()
  const query = useQuery({ queryKey: ['work-mine', companyId], queryFn: () => myWork(companyId), ...liveQuery })
  const items = (query.data?.mine ?? []).filter((item) => !item.hidden).sort((a, b) =>
    Number(b.overdue) - Number(a.overdue) || (a.due_at ?? '9999').localeCompare(b.due_at ?? '9999'))
  return <Block title="На мне" query={query} action={<Button variant="link" className="min-h-11" asChild><Link to="/docs/work?view=today">Открыть Трек</Link></Button>}>
    {query.data && <p className="pt-3 text-sm text-muted-foreground">В очереди: {items.length} · Просрочено: {items.filter((item) => item.overdue).length}</p>}
    {items.slice(0, 4).map((item) => <Link key={`${item.kind}:${item.id}:${item.reason}`} to={myWorkHref(item)} className={rowClass}>
      <span className="min-w-0"><span className="block break-words text-sm font-medium">{item.title || item.key}</span><span className="text-xs text-muted-foreground">{item.reason_name}{item.due_at ? ` · до ${new Date(item.due_at).toLocaleDateString('ru-RU')}` : ''}</span></span>
      {item.overdue ? <span className="text-xs text-destructive">Просрочено</span> : <ArrowUpRight className="size-4 shrink-0" />}
    </Link>)}
    {query.data && !items.length && <Empty>Сейчас нет работы, ожидающей вашего действия.</Empty>}
  </Block>
}

function ChatsBlock() {
  const { companyId } = useCompany()
  const { openInteraction } = useSupportContext()
  const query = useQuery({ queryKey: ['chat-rooms', companyId, false, 'all'], queryFn: () => getRooms(false), ...liveQuery })
  const rooms = [...(query.data ?? [])].sort((a, b) => Number(b.isPinned) - Number(a.isPinned) || (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''))
  return <Block title="Чаты" query={query} action={<Button variant="link" className="min-h-11" onClick={() => openInteraction('chat')}>Все чаты</Button>}>
    {query.data && <p className="pt-3 text-sm text-muted-foreground">Непрочитанных сообщений: {rooms.reduce((n, room) => n + (isMuted(room) ? 0 : room.unreadCount), 0)}</p>}
    {rooms.slice(0, 4).map((room) => <button type="button" key={room.id} className={rowClass} onClick={() => openInteraction('chat', `room:${room.id}`)}>
      <span className="min-w-0"><span className="block truncate text-sm font-medium">{room.name || 'Личный чат'}</span><span className="block truncate text-xs text-muted-foreground">{room.lastMessage || 'Сообщений пока нет'}</span></span>
      {room.unreadCount > 0 && <span className="text-sm font-medium" aria-label={`${room.unreadCount} непрочитанных`}>{room.unreadCount}</span>}
    </button>)}
    {query.data && !rooms.length && <Empty>Здесь появятся ваши чаты пространства.</Empty>}
  </Block>
}

function MeetingsBlock() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<CalendarEvent | null>(null)
  const from = todayKey()
  const toDate = new Date(); toDate.setDate(toDate.getDate() + 7)
  const query = useQuery({ queryKey: ['pulse-my-meetings', companyId, from], queryFn: () => listEvents(companyId, from, todayKey(toDate), { scope: 'mine' }), ...liveQuery })
  const events = (query.data?.events ?? []).filter((event) => event.status === 'planned' && event.my_response !== 'declined' && Date.parse(event.ends_at) > Date.now())
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
  return <Block title="Встречи на 7 дней" query={query} action={<Button variant="link" className="min-h-11" asChild><Link to="/docs/work?view=calendar">Календарь</Link></Button>}>
    {events.slice(0, 4).map((event) => <button type="button" key={event.id} onClick={() => setSelected(event)} className={rowClass}>
      <span className="min-w-0"><span className="block break-words text-sm font-medium">{event.title}</span><span className="text-xs text-muted-foreground">{new Date(event.starts_at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', ...(event.all_day ? {} : { hour: '2-digit', minute: '2-digit' }) })}{event.all_day ? ' · весь день' : ''}{event.conference_url ? ' · онлайн' : ''}</span></span><CalendarDays className="size-4 shrink-0" />
    </button>)}
    {query.data && !events.length && <Empty>В ближайшие 7 дней встреч не запланировано.</Empty>}
    {selected && <EventDialog companyId={companyId} event={selected} startAt={null} onClose={() => setSelected(null)} onChanged={() => {
      void query.refetch()
      void qc.invalidateQueries({ queryKey: ['calendar', companyId] })
      void qc.invalidateQueries({ queryKey: ['events', companyId] })
    }} />}
  </Block>
}

function MetricsBlock({ query, selected }: { query: UseQueryResult<Awaited<ReturnType<typeof getPulseDay>>>; selected: string[] | null }) {
  const navigate = useNavigate()
  const metrics = (query.data?.kpi ?? []).filter((k) => selected === null || selected.includes(k.key)).slice(0, 12)
  return <Block title="Показатели пространства" query={query} action={<Button variant="link" className="min-h-11" asChild><Link to="/pulse?view=today">Экран дня</Link></Button>}>
    {query.data && <>
      <p className="py-3 text-xs text-muted-foreground">{query.data.as_of ? `Данные сети на ${new Date(query.data.as_of).toLocaleDateString('ru-RU')}. ` : ''}Период и источник указаны у показателей.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{metrics.map((k) => <KpiTile key={k.key} k={k} onOpen={k.link ? () => navigate(k.link!) : undefined} />)}</div>
      {!metrics.length && <Empty>Нет выбранных показателей, доступных вашей роли.</Empty>}
      {query.data.cards.length > 0 && <Button variant="link" className="mt-2 min-h-11" asChild><Link to="/pulse?view=today">Требуют внимания: {query.data.cards.length}</Link></Button>}
    </>}
  </Block>
}

export function PulseApps() {
  const { companyId } = useCompany()
  const query = useQuery({ queryKey: ['sso-apps', companyId], queryFn: () => listSsoApps(companyId), staleTime: refreshInterval })
  return <div className="mx-auto max-w-3xl space-y-4"><h1 className="text-xl font-semibold">Приложения пространства</h1><p className="text-sm text-muted-foreground">Рабочие места, доступные вам в этом пространстве.</p><AppList query={query} favorites={[]} /><Button variant="outline" className="min-h-11" asChild><Link to="/pulse">Вернуться к пульту</Link></Button></div>
}

function AppList({ query, favorites, compact = false }: { query: UseQueryResult<Awaited<ReturnType<typeof listSsoApps>>>; favorites: string[]; compact?: boolean }) {
  const { openApp, busy } = useOpenApp()
  const [search, setSearch] = useState('')
  const apps = (query.data?.apps ?? []).filter((app) => !['pulse', 'chat', 'conf'].includes(app.code) &&
    (!query.data?.allowed_apps || query.data.allowed_apps.includes(app.code)))
  const ordered = favorites.length ? favorites.flatMap((code) => apps.filter((app) => app.code === code)) : apps
  const visible = compact ? (favorites.length ? ordered : ordered.slice(0, 6)) : apps.filter((app) => `${app.name} ${app.description ?? ''}`.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')))
  return <Block title={compact ? 'Мои приложения' : 'Доступные приложения'} query={query}
    action={compact && <Button variant="link" className="min-h-11" asChild><Link to="/pulse?view=apps">Все</Link></Button>}>
    {!compact && <Input className="my-3 min-h-11" aria-label="Найти приложение" placeholder="Найти приложение" value={search} onChange={(event) => setSearch(event.target.value)} />}
    {visible.map((app) => <button type="button" key={app.code} className={rowClass} disabled={!!busy} onClick={() => void openApp(app)}>
      <span className="min-w-0"><span className="block text-sm font-medium">{app.name}</span><span className="block text-xs text-muted-foreground">{app.description}</span></span><ArrowUpRight className="size-4 shrink-0" />
    </button>)}
    {query.data && !visible.length && <Empty>{search.trim() ? 'По этому запросу приложения не найдены.' : favorites.length && compact ? 'Закреплённые приложения сейчас недоступны. Выберите другие в настройке пульта.' : 'Доступных приложений пока нет.'}</Empty>}
  </Block>
}

function HomeEditor({ settings, apps, metrics, catalogReady, metricsReady, allowedSections, onClose }: { settings: HomeSettings; apps: SsoApp[]; metrics: PulseKpi[]; catalogReady: boolean; metricsReady: boolean; allowedSections: HomeSection[]; onClose: () => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [scope, setScope] = useState<'personal' | 'space'>('personal')
  const personalDraft = () => ({ ...structuredClone(settings.effective), sections: settings.effective.sections.filter((key) => allowedSections.includes(key)) })
  const [draft, setDraft] = useState<HomeConfig>(personalDraft)
  const [revision, setRevision] = useState(settings.personal_revision)
  const mutation = useMutation({ mutationFn: (config: HomeConfig | null) => saveHomeSettings(companyId, scope, revision, config),
    onSuccess: (data) => { qc.setQueryData(['pulse-home-settings', companyId], data); toast.success(scope === 'space' ? 'Стартовый экран пространства сохранён' : 'Ваш пульт сохранён'); onClose() },
    onError: (error) => toast.error(error.message) })
  const toggle = (field: 'favorite_apps' | 'metric_keys', key: string, all: string[] = []) => {
    const current = draft[field] ?? all
    setDraft({ ...draft, [field]: current.includes(key) ? current.filter((x) => x !== key) : [...current, key] })
  }
  const move = (index: number, by: number) => {
    const sections = [...draft.sections]
    ;[sections[index], sections[index + by]] = [sections[index + by], sections[index]]
    setDraft({ ...draft, sections })
  }
  return <section aria-label="Настройка пульта" className="space-y-4 rounded-xl border bg-card p-4">
    <h2 className="font-semibold">Настройка пульта</h2>
    <p className="text-sm text-muted-foreground">Порядок блоков, приложения и показатели сохраняются для этого пространства на всех ваших устройствах.</p>
    {settings.can_set_default && <label className="block space-y-2 text-sm">Кому настроить экран
      <select className="block min-h-11 w-full rounded-md border bg-background px-3" value={scope} disabled={mutation.isPending} onChange={(e) => {
        const next = e.target.value as 'personal' | 'space'; setScope(next)
        setDraft(next === 'space' ? structuredClone(settings.default) : personalDraft())
        setRevision(next === 'space' ? settings.space_revision : settings.personal_revision)
      }}><option value="personal">Только мне</option><option value="space">По умолчанию для пространства</option></select>
    </label>}
    {scope === 'space' && <p className="text-sm text-muted-foreground">Общий экран применяется к тем, кто ещё не сохранил личный вариант. Доступ к данным и приложениям определяется правами каждого сотрудника.</p>}
    <fieldset disabled={mutation.isPending} className="space-y-2"><legend className="mb-2 text-sm font-medium">Блоки и их порядок</legend>
      {scope === 'personal' && <p className="text-xs text-muted-foreground">Показаны блоки, доступные вам в этом пространстве.</p>}
      {[...draft.sections, ...(Object.keys(HOME_SECTIONS) as HomeSection[]).filter((key) => !draft.sections.includes(key))].filter((key) => scope === 'space' || allowedSections.includes(key)).map((key) => {
        const index = draft.sections.indexOf(key)
        return <div key={key} className="flex items-center justify-between gap-2">
          <label className="flex min-h-11 flex-1 items-center gap-3 text-sm"><input type="checkbox" className="size-4 accent-primary" checked={index >= 0} onChange={() => setDraft({ ...draft, sections: index >= 0 ? draft.sections.filter((x) => x !== key) : [...draft.sections, key] })} />{HOME_SECTIONS[key]}</label>
          <Button variant="ghost" className="size-11" aria-label={`${HOME_SECTIONS[key]}: выше`} disabled={index <= 0} onClick={() => move(index, -1)}><ArrowUp className="size-4" /></Button>
          <Button variant="ghost" className="size-11" aria-label={`${HOME_SECTIONS[key]}: ниже`} disabled={index < 0 || index === draft.sections.length - 1} onClick={() => move(index, 1)}><ArrowDown className="size-4" /></Button>
        </div>
      })}
    </fieldset>
    <fieldset disabled={!catalogReady || mutation.isPending}><legend className="mb-2 text-sm font-medium">Закреплённые приложения · до 12</legend>
      <p className="mb-2 text-xs text-muted-foreground">Без выбора показываются первые доступные приложения. Порядок закрепления определяет порядок на пульте.</p>
      {apps.filter((app) => !['pulse', 'chat', 'conf'].includes(app.code)).map((app) => <label key={app.code} className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="size-4 accent-primary" checked={draft.favorite_apps.includes(app.code)} disabled={!draft.favorite_apps.includes(app.code) && draft.favorite_apps.length >= 12} onChange={() => toggle('favorite_apps', app.code)} />{app.name}</label>)}
    </fieldset>
    {(scope === 'space' || allowedSections.includes('metrics')) && <fieldset disabled={!metricsReady || mutation.isPending}><legend className="mb-2 text-sm font-medium">Показатели</legend>
      <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="size-4 accent-primary" checked={draft.metric_keys === null} onChange={(e) => setDraft({ ...draft, metric_keys: e.target.checked ? null : [] })} />Все доступные показатели</label>
      {draft.metric_keys !== null && metrics.map((metric) => <label key={metric.key} className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="size-4 accent-primary" checked={draft.metric_keys?.includes(metric.key)} onChange={() => toggle('metric_keys', metric.key)} />{metric.title}</label>)}
    </fieldset>}
    {mutation.isError && <p role="alert" className="text-sm text-destructive">{mutation.error.message}</p>}
    <div className="flex flex-wrap gap-2">
      <Button className="min-h-11" disabled={mutation.isPending} onClick={() => mutation.mutate(draft)}>{mutation.isPending ? 'Сохраняем…' : 'Сохранить'}</Button>
      <Button variant="outline" className="min-h-11" disabled={mutation.isPending} onClick={onClose}>Отмена</Button>
      {scope === 'personal' && settings.personal && <Button variant="ghost" className="min-h-11" disabled={mutation.isPending} onClick={() => mutation.mutate(null)}>Вернуть экран пространства</Button>}
    </div>
  </section>
}

function AnalyticsLinks() {
  const { canModule, company } = useCompany()
  const links = [
    ['today', 'Экран дня', '/pulse?view=today'], ['business', 'Бизнес', '/pulse/business'],
    ['team', 'Команда', '/pulse/team'], ['week', 'Неделя', '/pulse/week'], ['showcase', 'Моя витрина', '/pulse?view=showcase'],
  ].filter(([module, , to]) => ['business', 'team', 'week'].includes(module)
    ? availablePulseViews(to, company.profileId, canModule).length > 0 : canModule('pulse', module))
  return <nav aria-label="Обзоры Пульса" className="flex flex-wrap gap-2 border-t pt-4">{links.map(([key, label, to]) => <Button key={key} variant="outline" className="min-h-11" asChild><Link to={to}>{label}</Link></Button>)}</nav>
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-4 text-sm text-muted-foreground">{children}</p>
}
