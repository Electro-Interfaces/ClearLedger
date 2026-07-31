/**
 * «Управление» → «Обзор». Что происходит в пространстве, а не перечень того, что настроено.
 *
 * Было: версия ядра, издатель SSO, kid, число ключей JWKS и три карточки сервисов — то
 * есть реквизиты конфигурации, которые и так лежат в «Настройках», плюс счётчики компаний
 * и пользователей. Ни одного ответа на вопрос «всё ли в порядке и что делать».
 *
 * Стало: сверху то, что требует внимания (сюда вошёл и отдельный раздел «Оповещения» —
 * он выводил те же два факта из того же запроса), затем живые показатели пространства,
 * состояние сервисов одной строкой и активность людей. Реквизиты остались в «Настройках»:
 * обзор отвечает «как сейчас», настройки — «как настроено».
 *
 * Своего эндпоинта у обзора нет — собирается из готовых `/api/core/status` и
 * `/api/registry/space-map`.
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Loader2, Activity, Users, MapPin, Building2, History, Blocks,
  MessageSquare, Video, Mail, KeyRound, CheckCircle2, XCircle, MinusCircle, Circle,
  AlertTriangle, ClipboardList, UserX, Handshake, Wifi,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useCompany } from '@/contexts/CompanyContext'
import { getCoreStatus, type CoreServiceStatus } from '@/services/coreService'
import { getSpaceMap, type SpaceMapCompany } from '@/services/spaceMapService'
import * as ticketsService from '@/services/ticketsService'
import { ACTION_LABEL } from './AuditLog'

/** Голый IP в подписи события ничего не говорит человеку — уводим в title. */
const looksLikeIp = (s: string | null | undefined) =>
  !!s && /^\d{1,3}(\.\d{1,3}){3}$/.test(s.trim())

const SERVICE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  chat: MessageSquare, conf: Video, mail: Mail,
}

/** Компактный бейдж сервиса: в обзоре важно состояние, а не его параметры. */
function serviceBadge(s: CoreServiceStatus) {
  const Icon = SERVICE_ICON[s.code] ?? Circle
  const base = 'gap-1 bg-transparent text-[11px]'
  switch (s.status) {
    case 'up':
      return <Badge variant="outline" className={`${base} border-emerald-400/50 text-emerald-300/90`}>
        <Icon className="h-3 w-3" /> {s.name} <CheckCircle2 className="h-3 w-3" /></Badge>
    case 'down':
      return <Badge variant="destructive" className="gap-1 text-[11px]">
        <Icon className="h-3 w-3" /> {s.name} <XCircle className="h-3 w-3" /></Badge>
    case 'configured':
      return <Badge variant="outline" className={`${base} border-amber-400/50 text-amber-300/90`}>
        <Icon className="h-3 w-3" /> {s.name}</Badge>
    default:
      return <Badge variant="outline" className={`${base} border-zinc-600 text-zinc-500`}>
        <Icon className="h-3 w-3" /> {s.name} <MinusCircle className="h-3 w-3" /></Badge>
  }
}

function Stat({ icon: Icon, label, value, hint, onClick }: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: React.ReactNode
  hint?: string
  /** Число без перехода — тупик: карточка ведёт в раздел, где эти люди/объекты живут. */
  onClick?: () => void
}) {
  const body = (
    <>
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-semibold leading-tight tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground truncate">{label}</div>
        {hint && <div className="text-[11px] text-muted-foreground/70 truncate">{hint}</div>}
      </div>
    </>
  )
  const cls = 'flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5'
  return onClick
    ? <button type="button" onClick={onClick}
        className={`${cls} text-left transition-colors hover:border-primary/50 hover:bg-accent/40`}>{body}</button>
    : <div className={cls}>{body}</div>
}

/** Счётчики по всем организациям контейнера (у одной организации — её же цифры). */
function totals(companies: SpaceMapCompany[]) {
  const z = {
    people: 0, online: 0, internal: 0, partners: 0, neverSeen: 0, noAccess: 0,
    objects: 0, organizations: 0, equipment: 0, events: 0,
  }
  for (const c of companies) {
    for (const k of Object.keys(z) as (keyof typeof z)[]) z[k] += c.counts[k] ?? 0
  }
  return z
}

export function CoreOverview() {
  const navigate = useNavigate()
  const { company } = useCompany()
  const st = useQuery({
    queryKey: ['core-status'], queryFn: getCoreStatus,
    staleTime: 30_000, refetchInterval: 60_000,
  })
  // Без company_id суперадмин получает весь контейнер.
  const map = useQuery({
    queryKey: ['space-map', 'overview'], queryFn: () => getSpaceMap(),
    staleTime: 30_000, refetchInterval: 60_000,
  })
  // Заявки — главный пульс работы пространства: обзор без них отвечал только
  // «кто есть», но не «что происходит».
  const tickets = useQuery({
    queryKey: ['space-tickets-summary', company.id],
    queryFn: () => ticketsService.ticketsSummary(company.id),
    staleTime: 60_000,
  })

  if (st.isLoading || map.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка состояния…</div>
  }
  if (st.isError || !st.data) {
    return <Card><CardContent className="py-8 text-center text-muted-foreground">
      Не удалось получить состояние Ядра</CardContent></Card>
  }
  const d = st.data
  const companies = map.data?.companies ?? []
  const t = totals(companies)
  const windowDays = map.data?.windowDays ?? 30
  const apps = companies.flatMap((c) => c.apps)
  const appsOn = apps.filter((a) => a.enabled).length

  // Внешний участник без компании: в чатах и заявках он окажется «без стороны», и
  // заметить это можно только здесь.
  const partnersNoOrg = companies
    .flatMap((c) => c.people)
    .filter((p) => p.partyType === 'partner' && !p.orgName).length

  // Что требует внимания — по цене ошибки: сначала сломанное, потом забытое.
  // Каждый сигнал ведёт туда, где вопрос решается: сигнал без адреса — упрёк без дела.
  const alerts: { text: string; icon: React.ComponentType<{ className?: string }>; to?: string }[] = []
  d.services.filter((s) => s.status === 'down')
    .forEach((s) => alerts.push({ text: `Сервис «${s.name}» недоступен`, icon: XCircle,
                                  to: '/admin/eco/settings' }))
  if (!d.sso.enabled) {
    alerts.push({ text: 'Единый вход не настроен — переход между приложениями не работает',
                  icon: KeyRound, to: '/admin/eco/settings' })
  }
  const slaBreached = tickets.data?.sla_breached ?? 0
  if (slaBreached > 0) {
    alerts.push({ text: `Заявки нарушают SLA: ${slaBreached} — работа стоит дольше обещанного`,
                  icon: ClipboardList, to: '/tickets' })
  }
  if (t.noAccess > 0) {
    alerts.push({ text: `Без доступа к приложениям: ${t.noAccess} чел. — роль не назначена`,
                  icon: UserX, to: '/admin/company/members' })
  }
  if (partnersNoOrg > 0) {
    alerts.push({ text: `Внешних участников без компании: ${partnersNoOrg} — в чатах они без стороны`,
                  icon: Handshake, to: '/admin/company/partners' })
  }
  if (t.neverSeen > 0) {
    alerts.push({ text: `Ни разу не заходили: ${t.neverSeen} чел. — приглашение не дошло или пароль забыт`,
                  icon: UserX, to: '/admin/company/members' })
  }

  return (
    <div className="space-y-4">
      {/* 1. Внимание — первым экраном, а не отдельным разделом «Оповещения». */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <AlertTriangle className={`h-4 w-4 ${alerts.length ? 'text-amber-400' : 'text-emerald-400'}`} />
            Требует внимания
            {alerts.length > 0 && <Badge variant="secondary" className="text-[10px]">{alerts.length}</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-emerald-400">
              <CheckCircle2 className="h-4 w-4" /> Всё в порядке: сервисы отвечают, доступы назначены
            </div>
          ) : alerts.map((a, i) => a.to ? (
            <button key={i} type="button" onClick={() => navigate(a.to!)}
              className="flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left text-sm text-amber-300/90 transition-colors hover:bg-amber-500/10">
              <a.icon className="h-3.5 w-3.5 shrink-0" /> {a.text}
              <span className="ml-auto text-[11px] text-muted-foreground">разобрать →</span>
            </button>
          ) : (
            <div key={i} className="flex items-center gap-2 text-sm text-amber-300/90">
              <a.icon className="h-3.5 w-3.5 shrink-0" /> {a.text}
            </div>
          ))}
        </CardContent>
      </Card>

      {/* 2. Живые показатели пространства — каждый ведёт в свой раздел. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <Stat icon={Users} label="Людей в пространстве" value={t.people}
          hint={`своих ${t.internal} · внешних ${t.partners}`}
          onClick={() => navigate('/admin/company/members')} />
        <Stat icon={Wifi} label="Сейчас в системе" value={t.online}
          onClick={() => navigate('/admin/company/map')} />
        <Stat icon={ClipboardList} label="Заявок в работе"
          value={tickets.data ? tickets.data.open : '—'}
          hint={slaBreached ? `${slaBreached} нарушают SLA` : undefined}
          onClick={() => navigate('/tickets')} />
        <Stat icon={MapPin} label="Объектов" value={t.objects}
          onClick={() => navigate('/admin/company/objects')} />
        <Stat icon={Building2} label="Контрагентов" value={t.organizations}
          onClick={() => navigate('/admin/company/counterparties')} />
        <Stat icon={History} label={`События за ${windowDays} дн.`} value={t.events}
          onClick={() => navigate('/admin/company/audit')} />
      </div>

      {/* 3. Сервисы и единый вход — состояние строкой; реквизиты в «Настройках». */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-primary" /> Ядро и сервисы
            <Badge variant="outline" className="font-mono text-[10px]">v{d.version}</Badge>
            <Badge variant="secondary" className="text-[10px]">{d.env}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className={`gap-1 bg-transparent text-[11px] ${
            d.sso.enabled ? 'border-emerald-400/50 text-emerald-300/90' : 'border-zinc-600 text-zinc-500'}`}>
            <KeyRound className="h-3 w-3" /> Единый вход{d.sso.enabled ? '' : ' · выкл'}
          </Badge>
          {d.services.map((s) => <span key={s.code}>{serviceBadge(s)}</span>)}
          <Badge variant="outline" className="gap-1 bg-transparent text-[11px]">
            <Blocks className="h-3 w-3" /> Продуктов подключено {appsOn} из {apps.length || d.registry.apps}
          </Badge>
        </CardContent>
      </Card>

      {/* 4. Организации контейнера — строкой на каждую. При одной организации секции нет:
             цифры выше уже про неё, и вторая таблица была бы тем же самым. */}
      {companies.length > 1 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Building2 className="h-4 w-4 text-primary" /> Организации контейнера
              <span className="text-xs font-normal text-muted-foreground">({companies.length})</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {companies.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium">{c.name}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  людей {c.counts.people} · в сети {c.counts.online} · объектов {c.counts.objects}
                  {' '}· продуктов {c.apps.filter((a) => a.enabled).length} · событий {c.counts.events}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* 5. Работа и жизнь пространства. Слева — заявки («что происходит»), справа —
             последние события по-русски. Частоты сырых кодов аудита отсюда убраны:
             «member.access 18» не отвечает ни на один вопрос руководителя. */}
      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ClipboardList className="h-4 w-4 text-primary" /> Заявки пространства
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {!tickets.data ? (
              <p className="text-sm text-muted-foreground">
                {tickets.isLoading ? 'Загрузка…' : 'Не удалось загрузить заявки'}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
                  <span>в работе <b className="tabular-nums">{tickets.data.open}</b></span>
                  <span className={slaBreached ? 'text-red-500' : ''}>
                    нарушают SLA <b className="tabular-nums">{slaBreached}</b>
                  </span>
                  <span className="text-muted-foreground">
                    за неделю +{tickets.data.created_7d} / −{tickets.data.closed_7d}
                  </span>
                </div>
                {(tickets.data.by.responsibility ?? []).length > 0 && (
                  <div className="space-y-1 border-t border-border/60 pt-2 text-xs">
                    {(tickets.data.by.responsibility ?? []).slice(0, 4).map((r) => (
                      <div key={r.key} className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground">
                          {({ internal: 'у нас', vendor: 'у внешних', external: 'у внешних',
                              customer: 'у заявителя', client: 'у заявителя' } as Record<string, string>)[r.key] ?? r.key}
                        </span>
                        <span className="tabular-nums">{r.count}</span>
                      </div>
                    ))}
                  </div>
                )}
                <button type="button" onClick={() => navigate('/tickets')}
                  className="text-xs text-primary hover:underline">Открыть «Заявки» →</button>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <History className="h-4 w-4 text-primary" /> Последние события
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {(map.data?.recentEvents ?? []).length === 0
              ? <p className="text-sm text-muted-foreground">Событий нет</p>
              : (map.data?.recentEvents ?? []).slice(0, 8).map((e, i) => (
                <div key={i} className="flex flex-wrap items-baseline gap-x-2 text-sm"
                  title={looksLikeIp(e.summary) ? `адрес: ${e.summary}` : undefined}>
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {e.at
                      ? new Date(e.at).toLocaleString('ru-RU', {
                          day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                        })
                      : '—'}
                  </span>
                  {/* По-русски из общего словаря журнала; IP из подписи убран в title. */}
                  <span className="font-medium">{ACTION_LABEL[e.action] ?? e.action}</span>
                  {e.summary && !looksLikeIp(e.summary) && (
                    <span className="truncate text-muted-foreground">{e.summary}</span>
                  )}
                  <span className="text-[11px] text-muted-foreground">· {e.userName}</span>
                </div>
              ))}
            <button type="button" onClick={() => navigate('/admin/company/audit')}
              className="pt-1 text-xs text-primary hover:underline">Весь журнал →</button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
