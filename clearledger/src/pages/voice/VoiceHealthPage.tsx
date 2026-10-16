/**
 * «Состояние узла» — из чего узел состоит и что с каждой частью сейчас, с историей.
 *
 * Шапка — `/node`: заказчик, линии и их часы, версии узла, Asterisk и протокола КЦ,
 * действующие версии настроек. Части — `/health`: транк, Asterisk, связь с КЦ и база
 * обязательны (лежит любая — линия не принимается как надо), остальные предупреждают.
 * Узел сам проверяет части раз в 30 с; экран спрашивает раз в 30 с, пока открыт.
 * История — `/health/history`: когда падал транк, когда отставало распознавание, запуски
 * и остановки узла. Запуск без остановки перед ним — процесс упал; звонки, прерванные
 * перезапуском, — в журнале с исходом «прерван перезапуском».
 */
import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, CheckCircle2, MinusCircle, RefreshCw, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { СОСТОЯНИЕ_ЧАСТИ, ЧАСТЬ, дата, когда, началоДня, объём, сек } from './format'
import { Heading, NodeError } from './parts'

/** Порядок частей на экране: сначала обязательные. */
const ПОРЯДОК: voice.HealthPartName[] = ['trunk', 'ari', 'cc', 'db', 'asr', 'llm', 'disk', 'cert', 'backup']

const ЧТО_ДЕЛАЕТ: Record<voice.HealthPartName, string> = {
  trunk: 'по нему звонки приходят от оператора связи',
  ari: 'принимает звонки и управляет ими',
  cc: 'поток событий и звонков в контакт-центр',
  db: 'журнал звонков, настройки и журнал доступа',
  asr: 'расшифровка разговоров и подсказки оператору',
  llm: 'подсказывает поля итога; без неё — только правила',
  disk: 'где лежат записи разговоров',
  cert: 'mTLS с пространством, кромка и WSS Asterisk',
  backup: 'ночная копия базы, настроек и записей',
}

const ВОЗМОЖНОСТЬ: Record<string, string> = {
  operatorChannel: 'окно оператора КЦ',
  asr: 'распознавание',
  llm: 'языковая модель',
  sounds: 'звуки из пространства',
  webhooks: 'получатели событий',
  trunkState: 'состояние транка',
  backupMark: 'отметка бэкапа',
  spaceMtls: 'mTLS с пространством',
}

function Значок({ s, className }: { s: string; className?: string }) {
  const c = cn('h-4 w-4 shrink-0', className)
  if (s === 'up' || s === 'started') return <CheckCircle2 className={cn(c, 'text-success')} aria-hidden />
  if (s === 'warn') return <AlertTriangle className={cn(c, 'text-warning')} aria-hidden />
  if (s === 'down' || s === 'stopped') return <XCircle className={cn(c, s === 'down' ? 'text-destructive' : 'text-muted-foreground')} aria-hidden />
  return <MinusCircle className={cn(c, 'text-muted-foreground')} aria-hidden />
}

/** Число части с единицей: база — мс ответа, диск — % свободного, сертификаты — дней, бэкап — часов назад. */
function величина(p: voice.HealthPart) {
  if (p.value == null) return null
  switch (p.unit) {
    case 'ms': return `ответ ${p.value} мс`
    case '%': return `свободно ${Math.round(p.value)} %`
    case 'days': return `до ближайшего конца ${p.value} дн.`
    case 'h': return `удачный ${p.value} ч назад`
    default: return String(p.value)
  }
}

function сведения(имя: voice.HealthPartName, p: voice.HealthPart) {
  const i = p.info ?? {}
  const ч: string[] = []
  if (имя === 'ari' && typeof i.asterisk === 'string') ч.push(`Asterisk ${i.asterisk}`)
  if (имя === 'ari' && typeof i.reloadedAt === 'string') ч.push(`перечитан ${когда(i.reloadedAt)}`)
  if (имя === 'trunk' && typeof i.endpoint === 'string') ч.push(`endpoint ${i.endpoint}`)
  if (имя === 'disk' && typeof i.freeBytes === 'number' && typeof i.totalBytes === 'number') ч.push(`${объём(i.freeBytes)} из ${объём(i.totalBytes)}`)
  if (имя === 'backup' && typeof i.lastOkAt === 'string') ч.push(`последний удачный ${когда(i.lastOkAt)}`)
  if (имя === 'backup' && typeof i.thresholdH === 'number') ч.push(`тревога после ${i.thresholdH} ч`)
  return ч
}

/** Сколько длится состояние: «3 ч 10 мин», дольше двух суток — «5 дн. 4 ч». */
function длится(since: string | null | undefined, сейчас: number) {
  if (!since) return null
  const s = Math.max(0, (сейчас - Date.parse(since)) / 1000)
  if (s < 2 * 86400) return сек(s)
  return `${Math.floor(s / 86400)} дн. ${Math.floor((s % 86400) / 3600)} ч`
}

const раз = (n: number) => (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? `${n} раза` : `${n} раз`)

const ПЕРИОДЫ = [
  { key: 'day', name: 'Сутки', дней: 1 },
  { key: 'week', name: '7 дней', дней: 7 },
  { key: 'month', name: '30 дней', дней: 30 },
] as const

export default function VoiceHealthPage() {
  const { companyId } = useCompany()
  const узел = useQuery({ queryKey: ['voice-node', companyId], queryFn: () => voice.nodeInfo(companyId), refetchInterval: 5 * 60_000 })
  const здоровье = useQuery({ queryKey: ['voice-health', companyId], queryFn: () => voice.health(companyId), refetchInterval: 30_000 })
  const [сейчас] = useState(() => Date.now())

  const h = здоровье.data
  const момент = h?.at ? Date.parse(h.at) : сейчас

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Состояние узла" подпись="Из чего состоит узел и что с каждой частью сейчас. Узел проверяет себя раз в 30 секунд.">
        <Button variant="outline" size="sm" onClick={() => { void здоровье.refetch(); void узел.refetch() }} disabled={здоровье.isFetching}>
          <RefreshCw className={cn(здоровье.isFetching && 'animate-spin')} />Проверить
        </Button>
      </Heading>

      {узел.isError && <NodeError ошибка={узел.error} что="прочитать сведения об узле" />}
      {узел.data && <NodeCard n={узел.data} />}

      {здоровье.isLoading && <p role="status" className="text-sm">Спрашиваем узел о частях…</p>}
      {здоровье.isError && <NodeError ошибка={здоровье.error} что="узнать состояние частей узла" />}
      {h && (
        <div className={cn('flex items-start gap-2 rounded-lg border p-3 text-sm',
          h.status === 'down' ? 'border-destructive/40 bg-destructive/5' : h.status === 'degraded' ? 'border-warning/50 bg-warning/5' : 'border-border bg-card')}>
          <Значок s={h.status === 'down' ? 'down' : h.status === 'degraded' ? 'warn' : 'up'} className="mt-0.5" />
          <p>
            {h.status === 'down' ? 'Не работает обязательная часть: линия не принимается как надо.'
              : h.status === 'degraded' ? 'Линия принимается, но часть узла требует внимания.'
                : 'Все части работают.'}
            {h.at && <span className="text-muted-foreground"> Проверено {когда(h.at)}.</span>}
          </p>
        </div>
      )}
      {h?.parts && (
        <ul className="grid gap-2 md:grid-cols-2" aria-label="Части узла">
          {ПОРЯДОК.filter(k => h.parts![k]).map(k => <PartCard key={k} имя={k} p={h.parts![k]} сейчас={момент} />)}
        </ul>
      )}

      <History />
      <Interrupted />
    </div>
  )
}

function NodeCard({ n }: { n: voice.NodeInfo }) {
  const [сейчас] = useState(() => Date.now())
  const вкл = Object.entries(n.features).filter(([, v]) => v).map(([k]) => ВОЗМОЖНОСТЬ[k] ?? k)
  const выкл = Object.entries(n.features).filter(([, v]) => !v).map(([k]) => ВОЗМОЖНОСТЬ[k] ?? k)
  return (
    <section aria-label="Узел" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div>
        <h2 className="font-headline text-base font-semibold">{n.customer}</h2>
        <p className="text-xs text-muted-foreground">
          Работает с {когда(n.startedAt)} ({длится(n.startedAt, сейчас)}), часовой пояс {n.tz}.
        </p>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Узел</dt><dd className="font-mono text-xs leading-5">{n.nodeVersion}{n.build && ` · сборка ${n.build}`}</dd>
        <dt className="text-muted-foreground">Asterisk</dt><dd className="font-mono text-xs leading-5">{n.asterisk ?? 'не отвечает'}</dd>
        <dt className="text-muted-foreground">Протокол КЦ</dt><dd className="font-mono text-xs leading-5">{n.protocol ?? '—'}</dd>
        <dt className="text-muted-foreground">Действуют</dt>
        <dd>
          <Link to="/voice/versions?kind=passport" className="text-primary hover:underline">паспорт r{n.active.passport}</Link>,{' '}
          <Link to="/voice/versions?kind=reception" className="text-primary hover:underline">правила приёма r{n.active.reception}</Link>,{' '}
          <Link to="/voice/versions?kind=policy" className="text-primary hover:underline">политика хранения r{n.active.policy}</Link>
        </dd>
        {!!вкл.length && <><dt className="text-muted-foreground">Включено</dt><dd>{вкл.join(', ')}</dd></>}
        {!!выкл.length && <><dt className="text-muted-foreground">Выключено</dt><dd className="text-muted-foreground">{выкл.join(', ')}</dd></>}
      </dl>
      {!!n.lines.length && (
        <ul className="space-y-1 border-t border-border/60 pt-2 text-sm">
          {n.lines.map(l => (
            <li key={l.lineId} className="flex flex-wrap gap-x-2">
              <span className="font-medium">{l.name}</span>
              <span className={l.inHours ? 'text-success' : 'text-muted-foreground'}>{l.inHours ? 'рабочее время' : 'вне часов'}</span>
              <span className="text-muted-foreground">
                цель SLA {l.slaTargetSec} с
                {!!l.hours.length && ` · ${l.hours.map(ч => [ч.days, ч.from && ч.to ? `${ч.from}–${ч.to}` : null].filter(Boolean).join(' ')).join('; ')}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function PartCard({ имя, p, сейчас }: { имя: voice.HealthPartName; p: voice.HealthPart; сейчас: number }) {
  const доп = [величина(p), ...сведения(имя, p)].filter(Boolean)
  return (
    <li className={cn('space-y-1 rounded-xl border bg-card p-3 text-sm',
      p.state === 'down' && p.critical ? 'border-destructive/40' : p.state === 'down' || p.state === 'warn' ? 'border-warning/50' : 'border-border')}>
      <div className="flex items-start gap-2">
        <Значок s={p.state} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {ЧАСТЬ[имя]}
            {p.critical && <span className="ml-2 rounded-md border border-border px-1.5 text-xs font-normal text-muted-foreground">обязательная</span>}
          </p>
          <p className="text-xs text-muted-foreground">{ЧТО_ДЕЛАЕТ[имя]}</p>
        </div>
      </div>
      <p className={cn(p.state === 'down' && 'text-destructive', p.state === 'warn' && 'text-warning')}>
        {СОСТОЯНИЕ_ЧАСТИ[p.state] ?? p.state}
        {p.since && <span className="text-muted-foreground"> · {длится(p.since, сейчас)}, с {когда(p.since)}</span>}
      </p>
      {p.state !== 'up' && p.detail && <p>{p.detail}</p>}
      {!!доп.length && <p className="text-xs text-muted-foreground">{доп.join(' · ')}</p>}
      {имя === 'cert' && !!p.items?.length && (
        <ul className="space-y-0.5 pt-1 text-xs">
          {p.items.map(c => (
            <li key={`${c.source}-${c.name}`} className="flex flex-wrap items-center gap-x-1.5">
              <Значок s={c.state} className="h-3 w-3" />
              <span className="font-mono">{c.name}</span>
              {c.subject && <span className="text-muted-foreground">CN {c.subject}</span>}
              <span className="text-muted-foreground">
                {c.notAfter ? `до ${дата(c.notAfter)}${c.daysLeft != null ? `, ${c.daysLeft} дн.` : ''}` : c.detail ?? 'не прочитан'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function History() {
  const { companyId } = useCompany()
  const [часть, setЧасть] = useState<voice.HealthEvent['part'] | ''>('')
  const [период, setПериод] = useState<(typeof ПЕРИОДЫ)[number]['key']>('week')
  const п = ПЕРИОДЫ.find(x => x.key === период) ?? ПЕРИОДЫ[1]
  const from = началоДня(-(п.дней - 1))
  const история = useInfiniteQuery({
    queryKey: ['voice-health-history', companyId, часть, from],
    queryFn: ({ pageParam }) => voice.healthHistory(companyId, { part: часть, from, cursor: pageParam || undefined, limit: 200 }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const строки = история.data?.pages.flatMap(x => x.items) ?? []

  // Запуск узла без остановки перед ним (строки — новые первыми) — процесс упал, а не перезапущен.
  const упал = new Set<string>()
  const узла = строки.filter(r => r.part === 'node')
  узла.forEach((r, i) => { if (r.state === 'started' && узла[i + 1]?.state === 'started') упал.add(r.id) })

  // Сколько раз часть падала за период — то, о чём спрашивают первым.
  const падений = new Map<string, number>()
  for (const r of строки) if (r.part !== 'node' && r.state === 'down') падений.set(r.part, (падений.get(r.part) ?? 0) + 1)
  const запусков = узла.filter(r => r.state === 'started').length

  return (
    <section aria-label="История" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-headline text-base font-semibold">История</h2>
        <div className="flex gap-1 rounded-md border border-border p-0.5">
          {ПЕРИОДЫ.map(x => (
            <button key={x.key} type="button" onClick={() => setПериод(x.key)} aria-pressed={период === x.key}
              className={cn('min-h-8 rounded px-3 text-sm transition-colors',
                период === x.key ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
              {x.name}
            </button>
          ))}
        </div>
        <select value={часть} onChange={e => setЧасть(e.target.value as voice.HealthEvent['part'] | '')} aria-label="Часть узла"
          className="h-9 rounded-md border border-input bg-card px-2 text-sm">
          <option value="">все части</option>
          {[...ПОРЯДОК, 'node' as const].map(k => <option key={k} value={k}>{ЧАСТЬ[k]}</option>)}
        </select>
      </div>
      {история.isSuccess && (!!падений.size || !!запусков) && (
        <p className="text-sm">
          {[...падений].map(([k, n]) => `${ЧАСТЬ[k]} — не работал ${раз(n)}`).concat(запусков ? [`узел запускался ${раз(запусков)}${упал.size ? `, из них после падения — ${упал.size}` : ''}`] : []).join('; ')}.
          {!история.hasNextPage ? '' : ' Посчитано по загруженному.'}
        </p>
      )}
      {история.isError && <NodeError ошибка={история.error} что="прочитать историю узла" />}
      {история.isSuccess && !строки.length && (
        <EmptyBlock иконка={Activity} текст="За этот период части не меняли состояние" подсказка="Строка появляется, когда часть падает, поднимается или узел перезапускается." />
      )}
      {!!строки.length && (
        <ol className="space-y-1 text-sm">
          {строки.map(r => (
            <li key={r.id} className="flex flex-wrap items-start gap-x-2">
              <span className="w-32 shrink-0 text-muted-foreground">{когда(r.at)}</span>
              <Значок s={r.state} className="mt-0.5" />
              <span className="font-medium">{ЧАСТЬ[r.part] ?? r.part}</span>
              <span>{r.part === 'node' && r.state === 'started' && упал.has(r.id) ? 'запущен после падения' : СОСТОЯНИЕ_ЧАСТИ[r.state] ?? r.state}</span>
              {r.part === 'node' && r.code && <span className="font-mono text-xs leading-5 text-muted-foreground">{r.code}</span>}
              {r.part !== 'node' && r.detail && <span className="text-muted-foreground">{r.detail}</span>}
            </li>
          ))}
        </ol>
      )}
      {история.hasNextPage && (
        <Button variant="outline" size="sm" onClick={() => история.fetchNextPage()} disabled={история.isFetchingNextPage}>
          {история.isFetchingNextPage ? 'Читаем…' : 'Показать ещё'}
        </Button>
      )}
      <p className="text-xs text-muted-foreground">История хранится год.</p>
    </section>
  )
}

/** Звонки, прерванные перезапуском узла за 30 дней: исход `interrupted` журнала. */
function Interrupted() {
  const { companyId } = useCompany()
  const [from] = useState(() => началоДня(-29))
  const прерванные = useQuery({
    queryKey: ['voice-calls', companyId, 'interrupted', from],
    queryFn: () => voice.calls(companyId, { from, outcome: 'interrupted', limit: 50 }),
  })
  const r = прерванные.data?.items ?? []
  return (
    <section aria-label="Прерванные перезапуском" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Звонки, прерванные перезапуском узла</h2>
      {прерванные.isError && <NodeError ошибка={прерванные.error} что="прочитать журнал звонков" />}
      {прерванные.isSuccess && !r.length && <p className="text-sm text-muted-foreground">За 30 дней не было.</p>}
      {!!r.length && (
        <>
          <p className="text-sm">За 30 дней: {r.length}{прерванные.data?.next ? ' и больше' : ''}.</p>
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
            {r.map(c => (
              <li key={c.contactId}>
                <Link to={`/voice/calls?id=${encodeURIComponent(c.contactId)}`} className="text-primary hover:underline">{когда(c.startedAt)}</Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
