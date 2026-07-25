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

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'online', label: 'В сети' },
  { key: 'partners', label: 'Внешние' },
  { key: 'noAccess', label: 'Без доступа' },
  { key: 'neverSeen', label: 'Не заходили' },
]

export function SpaceMap({ companyId }: { companyId?: string }) {
  const q = useQuery({
    queryKey: ['space-map', companyId ?? 'all'],
    queryFn: () => getSpaceMap(companyId),
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
      <p className="text-sm text-muted-foreground">
        Обзор пространства за последние {map.windowDays} дней: состав людей, их доступы,
        активность и события. Управление — в соответствующих разделах.
      </p>

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
  const apps = company.apps.filter((a) => a.enabled)

  const people = useMemo(() => {
    switch (filter) {
      case 'online': return company.people.filter((p) => p.online)
      case 'partners': return company.people.filter((p) => p.partyType === 'partner')
      case 'noAccess': return company.people.filter((p) => p.apps.length === 0)
      case 'neverSeen': return company.people.filter((p) => !p.lastSeenAt)
      default: return company.people
    }
  }, [company.people, filter])

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

      {/* Матрица «человек × приложение»: одним взглядом видно, кто куда допущен и
          где доступа нет вообще — в списках это приходится проверять по одному. */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Человек</th>
              <th className="px-2 py-2 text-left font-medium">Кто это</th>
              {apps.map((a) => (
                <th key={a.code} className="px-2 py-2 text-center font-medium" title={a.name}>
                  {a.name.length > 12 ? `${a.name.slice(0, 12)}…` : a.name}
                </th>
              ))}
              <th className="px-2 py-2 text-right font-medium">Был</th>
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
      {appCodes.map((code) => (
        <td key={code} className="px-2 py-2 text-center">
          {allowed.has(code)
            ? <Check className={`mx-auto size-4 ${person.fullAccess ? 'text-primary' : 'text-emerald-600'}`} />
            : <Minus className="mx-auto size-4 text-muted-foreground/40" />}
        </td>
      ))}
      <td className="px-2 py-2 text-right text-xs text-muted-foreground">
        {person.online
          ? <span className="font-medium text-emerald-600 dark:text-emerald-500">в сети</span>
          : person.lastSeenAt
            ? new Date(person.lastSeenAt).toLocaleDateString('ru-RU')
            : <span className="text-amber-600 dark:text-amber-500">никогда</span>}
      </td>
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
