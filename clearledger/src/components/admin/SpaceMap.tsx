/**
 * Карта пространства — обзорный экран Центра управления.
 *
 * Списки отвечают на вопрос «что настроено». Карта — на вопрос «что здесь происходит»:
 * сколько людей и сколько из них внешних, кто куда допущен (матрица человек × приложение),
 * кто ни разу не заходил, чем занимались за последний месяц и что случилось только что.
 *
 * Всё только для чтения: карта — инструмент наблюдения, правки делаются в своих разделах.
 * Поэтому её можно открыть в любой момент, ничего не сломав.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, Building2, Check, Cpu, Library, Loader2, MapPin, Minus, ShieldCheck, Users, Clock, Wifi,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PartyBadge } from '@/components/chat/PartyBadge'
import { PresenceDot } from '@/components/chat/PresenceDot'
import { getSpaceMap, type SpaceMapCompany, type SpaceMapPerson } from '@/services/spaceMapService'

type Filter = 'all' | 'online' | 'partners' | 'noAccess' | 'neverSeen'

/** «31.07, 14:02» — последний вход с точностью до минуты: по голой дате не видно,
 * человек работал час назад или мельком заглянул утром. */
const seenLabel = (iso: string) => new Date(iso).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'online', label: 'В сети' },
  { key: 'partners', label: 'Внешние' },
  { key: 'noAccess', label: 'Без доступа' },
  { key: 'neverSeen', label: 'Не заходили' },
]

/**
 * `isSuperadmin` даёт переключатель охвата вместо второго раздела: раньше «Карта» стояла
 * и в организации, и в контейнере — один компонент с `companyId` и без него, то есть два
 * пункта меню на одну и ту же страницу.
 */
export function SpaceMap({ companyId, isSuperadmin = false }: {
  companyId?: string; isSuperadmin?: boolean
}) {
  const [wide, setWide] = useState(false)
  const scoped = wide ? undefined : companyId
  const q = useQuery({
    queryKey: ['space-map', scoped ?? 'all'],
    queryFn: () => getSpaceMap(scoped),
    staleTime: 60_000,
    // Присутствие живёт минутами: без автообновления карта показывала бы «в сети» тех,
    // кто уже ушёл.
    refetchInterval: 60_000,
  })

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 py-10 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Собираем карту…
      </div>
    )
  }
  if (q.isError) {
    return <div className="py-10 text-center text-sm text-destructive">Не удалось собрать карту: {(q.error as Error).message}</div>
  }

  const map = q.data!
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Обзор пространства за последние {map.windowDays} дней: состав людей, их доступы,
          активность и события. Управление — в соответствующих разделах.
        </p>
        {isSuperadmin && companyId && (
          <div className="flex items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">Охват:</span>
            <Button size="sm" variant={wide ? 'ghost' : 'secondary'} className="h-7 px-2 text-xs"
              onClick={() => setWide(false)}>Организация</Button>
            <Button size="sm" variant={wide ? 'secondary' : 'ghost'} className="h-7 px-2 text-xs"
              onClick={() => setWide(true)}>Весь контейнер</Button>
          </div>
        )}
      </div>

      {map.companies.map((c) => <CompanyCard key={c.id} company={c} windowDays={map.windowDays} />)}

      {map.recentEvents.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Clock className="size-4 text-primary" /> Последние события
          </div>
          <div className="divide-y rounded-xl border border-border">
            {map.recentEvents.map((e, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <span className="w-[130px] shrink-0 font-mono text-xs text-muted-foreground">
                  {e.at ? new Date(e.at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'}
                </span>
                <Badge variant="secondary" className="shrink-0 font-mono text-[10px]">{e.action}</Badge>
                <span className="min-w-0 flex-1 truncate">{e.userName}</span>
                {e.summary && <span className="truncate text-xs text-muted-foreground">{e.summary}</span>}
                <span className="shrink-0 text-xs text-muted-foreground">{e.company}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function CompanyCard({ company, windowDays }: { company: SpaceMapCompany; windowDays: number }) {
  const [filter, setFilter] = useState<Filter>('all')
  // Сортировка по последнему входу — клик по заголовку «Был»: недавние сверху,
  // вторым кликом — давние и «никогда» сверху (кого пора тормошить).
  const [seenSort, setSeenSort] = useState<'desc' | 'asc' | null>(null)
  const apps = company.apps.filter((a) => a.enabled)

  const people = useMemo(() => {
    let list = company.people
    switch (filter) {
      case 'online': list = list.filter((p) => p.online); break
      case 'partners': list = list.filter((p) => p.partyType === 'partner'); break
      case 'noAccess': list = list.filter((p) => p.apps.length === 0); break
      case 'neverSeen': list = list.filter((p) => !p.lastSeenAt); break
    }
    if (seenSort) {
      const ts = (p: SpaceMapPerson) =>
        p.online ? Number.MAX_SAFE_INTEGER : p.lastSeenAt ? Date.parse(p.lastSeenAt) : 0
      list = [...list].sort((a, b) => seenSort === 'desc' ? ts(b) - ts(a) : ts(a) - ts(b))
    }
    return list
  }, [company.people, filter, seenSort])

  return (
    <section className="space-y-3 rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Building2 className="size-4 text-primary" />
        <span className="font-semibold">{company.name}</span>
        <span className="font-mono text-xs text-muted-foreground">{company.slug}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <Stat icon={Users} label="людей" value={company.counts.people}
          hint={`своих ${company.counts.internal}, внешних ${company.counts.partners}`} />
        <Stat icon={Wifi} label="сейчас в системе" value={company.counts.online} tone="ok" />
        <Stat icon={MapPin} label="объектов" value={company.counts.objects} />
        <Stat icon={Library} label="организаций" value={company.counts.organizations} />
        <Stat icon={Cpu} label="оборудования" value={company.counts.equipment} />
        <Stat icon={Activity} label={`событий за ${windowDays} дн.`} value={company.counts.events} />
        {company.counts.noAccess > 0 && (
          <Stat icon={Minus} label="без доступа" value={company.counts.noAccess} tone="warn" />
        )}
        {company.counts.neverSeen > 0 && (
          <Stat icon={Clock} label="не заходили" value={company.counts.neverSeen} tone="warn" />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {FILTERS.map((f) => (
          <Button key={f.key} size="sm" variant={filter === f.key ? 'default' : 'outline'}
            className="h-7 text-xs" onClick={() => setFilter(f.key)}>
            {f.label}
          </Button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">показано: {people.length}</span>
      </div>

      <p className="text-[11px] text-muted-foreground">
        «Заходил(а)» — дата и время последнего входа, сортируется нажатием на заголовок.
        Галочка в колонке приложения — доступ открыт, прочерк — доступа нет.
      </p>

      {/* Матрица «человек × приложение»: одним взглядом видно, кто куда допущен и
          где доступа нет вообще — в списках это приходится проверять по одному. */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Человек</th>
              <th className="px-2 py-2 text-left font-medium">Кто это</th>
              {/* «Заходил» — слева, до приложений: колонок доступа полтора десятка,
                  и всё, что правее них, живёт за горизонтальным скроллом — время
                  последнего входа там никто не находил. */}
              <th className="px-2 py-2 text-left font-medium">
                <button type="button" title="Сортировать по последнему входу"
                  className="inline-flex items-center gap-0.5 hover:text-foreground"
                  onClick={() => setSeenSort((s) => (s === 'desc' ? 'asc' : 'desc'))}>
                  Заходил(а) {seenSort === 'desc' ? '↓' : seenSort === 'asc' ? '↑' : ''}
                </button>
              </th>
              {apps.map((a) => (
                <th key={a.code} className="px-2 py-2 text-center font-medium" title={a.name}>
                  {a.name.length > 12 ? `${a.name.slice(0, 12)}…` : a.name}
                </th>
              ))}
              <th className="px-2 py-2 text-right font-medium">Событий</th>
            </tr>
          </thead>
          <tbody>
            {people.map((p) => <PersonRow key={p.id} person={p} appCodes={apps.map((a) => a.code)} />)}
            {people.length === 0 && (
              <tr><td colSpan={apps.length + 4} className="px-3 py-6 text-center text-sm text-muted-foreground">
                Никого по этому признаку
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {company.topActions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Чем занимались:</span>
          {company.topActions.map((a) => (
            <Badge key={a.action} variant="secondary" className="font-mono text-[10px]">
              {a.action} · {a.count}
            </Badge>
          ))}
        </div>
      )}
    </section>
  )
}

function PersonRow({ person, appCodes }: { person: SpaceMapPerson; appCodes: string[] }) {
  const allowed = new Set(person.apps)
  return (
    <tr className="border-t border-border/60">
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          {/* Тот же язык индикаторов, что в чате: зелёный — работает сейчас, серый —
              нет. Карта серверная, поэтому состояние берётся из отметки присутствия. */}
          <PresenceDot className="size-2" state={person.online ? 'online' : 'offline'}
            lastSeenAt={person.lastSeenAt} />
          <span className="font-medium">{person.name}</span>
          {person.isSuperadmin && (
            <Badge variant="outline" className="gap-1 text-[10px]"><ShieldCheck className="size-3" /> супер</Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground">{person.email}</div>
      </td>
      <td className="px-2 py-2">
        <PartyBadge party={person} />
      </td>
      <td className="px-2 py-2 text-left text-xs text-muted-foreground">
        {person.online
          ? <span className="font-medium text-emerald-600 dark:text-emerald-500">сейчас в сети</span>
          : person.lastSeenAt
            ? <span className="whitespace-nowrap tabular-nums"
                title={new Date(person.lastSeenAt).toLocaleString('ru-RU')}>
                {seenLabel(person.lastSeenAt)}
              </span>
            : <span className="text-amber-600 dark:text-amber-500">ни разу</span>}
      </td>
      {/* Один цвет у всех галочек: раньше полный доступ был синим, настроенный —
          зелёным, и двухцветную матрицу читали как «заходил / не заходил». Цвет
          здесь ничего не кодирует: галочка — доступ есть, прочерк — нет. */}
      {appCodes.map((code) => (
        <td key={code} className="px-2 py-2 text-center">
          {allowed.has(code)
            ? <Check className="mx-auto size-4 text-primary" />
            : <Minus className="mx-auto size-4 text-muted-foreground/40" />}
        </td>
      ))}
      <td className="px-2 py-2 text-right text-xs tabular-nums text-muted-foreground">{person.events}</td>
    </tr>
  )
}

function Stat({ icon: Icon, label, value, hint, tone }: {
  icon: typeof Users; label: string; value: number; hint?: string; tone?: 'warn' | 'ok'
}) {
  const border = tone === 'warn' ? 'border-amber-500/40 bg-amber-500/5'
    : tone === 'ok' ? 'border-emerald-500/40 bg-emerald-500/5'
    : 'border-border bg-muted/30'
  const iconTone = tone === 'warn' ? 'text-amber-600 dark:text-amber-500'
    : tone === 'ok' ? 'text-emerald-600 dark:text-emerald-500' : 'text-primary'
  return (
    <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${border}`}>
      <Icon className={`size-4 ${iconTone}`} />
      <div className="leading-tight">
        <div className="text-sm font-semibold tabular-nums">{value}</div>
        <div className="text-[11px] text-muted-foreground">{label}</div>
      </div>
      {hint && <div className="ml-1 max-w-[130px] text-[11px] leading-tight text-muted-foreground">{hint}</div>}
    </div>
  )
}
