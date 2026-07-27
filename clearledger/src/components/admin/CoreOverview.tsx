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
import { useQuery } from '@tanstack/react-query'
import {
  Loader2, Activity, Users, MapPin, Cpu, Building2, History, Blocks,
  MessageSquare, Video, Mail, KeyRound, CheckCircle2, XCircle, MinusCircle, Circle,
  AlertTriangle, UserX, Handshake, Wifi,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { getCoreStatus, type CoreServiceStatus } from '@/services/coreService'
import { getSpaceMap, type SpaceMapCompany } from '@/services/spaceMapService'

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

function Stat({ icon: Icon, label, value, hint }: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: React.ReactNode
  hint?: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-semibold leading-tight tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground truncate">{label}</div>
        {hint && <div className="text-[11px] text-muted-foreground/70 truncate">{hint}</div>}
      </div>
    </div>
  )
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
  const st = useQuery({
    queryKey: ['core-status'], queryFn: getCoreStatus,
    staleTime: 30_000, refetchInterval: 60_000,
  })
  // Без company_id суперадмин получает весь контейнер.
  const map = useQuery({
    queryKey: ['space-map', 'overview'], queryFn: () => getSpaceMap(),
    staleTime: 30_000, refetchInterval: 60_000,
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
  const alerts: { text: string; icon: React.ComponentType<{ className?: string }> }[] = []
  d.services.filter((s) => s.status === 'down')
    .forEach((s) => alerts.push({ text: `Сервис «${s.name}» недоступен`, icon: XCircle }))
  if (!d.sso.enabled) {
    alerts.push({ text: 'Единый вход не настроен — переход между приложениями не работает', icon: KeyRound })
  }
  if (t.noAccess > 0) {
    alerts.push({ text: `Без доступа к приложениям: ${t.noAccess} чел. — роль не назначена`, icon: UserX })
  }
  if (partnersNoOrg > 0) {
    alerts.push({ text: `Внешних участников без компании: ${partnersNoOrg} — в чатах они без стороны`, icon: Handshake })
  }
  if (t.neverSeen > 0) {
    alerts.push({ text: `Ни разу не заходили: ${t.neverSeen} чел.`, icon: UserX })
  }

  // Топ действий контейнера: у каждой организации свой список, складываем по действию.
  const topActions = Object.entries(
    companies.flatMap((c) => c.topActions).reduce<Record<string, number>>((acc, a) => {
      acc[a.action] = (acc[a.action] ?? 0) + a.count
      return acc
    }, {}),
  ).sort(([, a], [, b]) => b - a).slice(0, 6)

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
          ) : alerts.map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-sm text-amber-300/90">
              <a.icon className="h-3.5 w-3.5 shrink-0" /> {a.text}
            </div>
          ))}
        </CardContent>
      </Card>

      {/* 2. Живые показатели пространства. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <Stat icon={Users} label="Людей в пространстве" value={t.people}
          hint={`своих ${t.internal} · внешних ${t.partners}`} />
        <Stat icon={Wifi} label="Сейчас в системе" value={t.online} />
        <Stat icon={MapPin} label="Объектов" value={t.objects} />
        <Stat icon={Cpu} label="Оборудования" value={t.equipment} />
        <Stat icon={Building2} label="Контрагентов" value={t.organizations} />
        <Stat icon={History} label={`События за ${windowDays} дн.`} value={t.events} />
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

      {/* 5. Активность: чем в пространстве вообще занимаются. */}
      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="h-4 w-4 text-primary" /> Чаще всего за {windowDays} дн.
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {topActions.length === 0
              ? <p className="text-sm text-muted-foreground">Действий пока не было</p>
              : topActions.map(([action, count]) => (
                <div key={action} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate text-muted-foreground">{action}</span>
                  <span className="tabular-nums">{count}</span>
                </div>
              ))}
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
                <div key={i} className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {e.at
                      ? new Date(e.at).toLocaleString('ru-RU', {
                          day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                        })
                      : '—'}
                  </span>
                  <span className="font-medium">{e.action}</span>
                  {e.summary && <span className="truncate text-muted-foreground">{e.summary}</span>}
                  <span className="text-[11px] text-muted-foreground">· {e.userName}</span>
                </div>
              ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
