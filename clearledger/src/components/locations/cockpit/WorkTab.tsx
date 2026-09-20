/**
 * «Работа станции» — вкладка инженера в карточке.
 *
 * Отвечает на вопрос «что тут происходит», по которому инженер и открывает
 * станцию. Три слоя сверху вниз:
 *
 * 1. **как работает** — приезды клиентов, сколько уехало ни с чем, попытки на
 *    приезд, нагрузка на порт; рядом перерывы — когда станция стояла;
 * 2. **почему пробуют снова** — раскладка приездов по картинам: зарядился сразу /
 *    схватилось не с первого раза / помог другой коннектор / долбился и уехал /
 *    уехал после первой же неудачи. Без неё «попыток на приезд 2,8» — просто
 *    число: непонятно, это замок не держит или станция вовсе не даёт ток, а
 *    претензия производителю пишется по-разному;
 * 3. **на чём ломается** — разбивка по коннекторам: у проблемных станций один
 *    разъём даёт 100 % ошибок при живом соседнем;
 * 4. **ход каждого приезда** — раскрывающаяся лента: во сколько человек приехал,
 *    сколько раз втыкал разъём, чем кончилась каждая попытка.
 *
 * Последнее и есть главное. Итог «90 % отказов» говорит, что станция плохая;
 * ряд «семь попыток по 1,6 минуты подряд, все с ошибкой, ноль энергии» говорит,
 * ЧТО с ней: обрыв на рукопожатии, а не отсутствие питания.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, PlugZap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import { getStationHistory, getStationVisits, type StationVisit } from '@/services/opsService'
import type { ServiceLocation } from '@/types/location'
import { ScrollTab, SectionCard, InfoRow } from './shared'

const nf = new Intl.NumberFormat('ru-RU')
const ОКНА = [30, 90, 180] as const

function время(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Цвет исхода попытки: глазами читается быстрее, чем слово. */
const ЦВЕТ_ИСХОДА: Record<string, string> = {
  'зарядка': 'text-emerald-600 dark:text-emerald-400',
  'зарядка с ошибкой': 'text-amber-600 dark:text-amber-400',
  'ошибка': 'text-red-600 dark:text-red-400',
  'без энергии': 'text-amber-600 dark:text-amber-400',
}

/** Картины приезда: от благополучной к худшей. Цвет — чтобы читалось глазами. */
const ЦВЕТ_КАРТИНЫ: Record<string, string> = {
  ok: 'text-emerald-600 dark:text-emerald-400',
  retry_same: 'text-amber-600 dark:text-amber-400',
  retry_other: 'text-amber-600 dark:text-amber-400',
  left_after_tries: 'text-red-600 dark:text-red-400',
  left_first: 'text-red-600 dark:text-red-400',
}

function VisitRow({ визит }: { визит: StationVisit }) {
  const [открыт, setОткрыт] = useState(false)
  return (
    <div className={cn('border-b border-border/40 last:border-0',
      !визит.charged && 'bg-red-500/5')}>
      <button type="button" onClick={() => setОткрыт((v) => !v)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-accent/30">
        {открыт ? <ChevronDown className="size-3.5 shrink-0 opacity-60" />
          : <ChevronRight className="size-3.5 shrink-0 opacity-60" />}
        <span className="w-28 shrink-0 tabular-nums text-muted-foreground">
          {время(визит.startedAt)}
        </span>
        <span className={cn('w-32 shrink-0 font-medium',
          визит.charged ? 'text-emerald-600 dark:text-emerald-400'
            : 'text-red-600 dark:text-red-400')}>
          {визит.charged ? 'зарядился' : 'уехал ни с чем'}
        </span>
        <span className="w-24 shrink-0 tabular-nums text-muted-foreground">
          {визит.attempts} {визит.attempts === 1 ? 'попытка' : 'попыток'}
        </span>
        <span className="w-24 shrink-0 tabular-nums text-muted-foreground">
          {визит.minutesAtStation != null ? `${визит.minutesAtStation} мин` : '—'}
        </span>
        <span className="w-24 shrink-0 tabular-nums">
          {визит.energyKwh > 0 ? `${визит.energyKwh} кВтч` : '—'}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {визит.clientName || визит.client || ''}
          {визит.clientType ? ` · ${визит.clientType}` : ''}
        </span>
      </button>
      {открыт && (
        <div className="space-y-1 px-2 pb-2 pl-8">
          {визит.steps.map((ш) => (
            <div key={`${ш.seq}-${ш.at}`} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="w-6 shrink-0 tabular-nums text-muted-foreground">{ш.seq}.</span>
              <span className="w-12 shrink-0 tabular-nums">{ш.at.slice(11, 16)}</span>
              <span className="w-32 shrink-0 text-muted-foreground">
                коннектор {ш.connector ?? '—'}
                {ш.connectorType ? ` · ${ш.connectorType}` : ''}
              </span>
              <span className={cn('w-36 shrink-0 font-medium', ЦВЕТ_ИСХОДА[ш.outcome])}>
                {ш.outcome}
              </span>
              <span className="w-20 shrink-0 tabular-nums text-muted-foreground">
                {ш.minutes != null ? `${ш.minutes} мин` : '—'}
              </span>
              <span className="w-24 shrink-0 tabular-nums">
                {ш.energyKwh > 0 ? `${ш.energyKwh} кВтч` : '0 кВтч'}
              </span>
              {ш.amount > 0 && (
                <span className="tabular-nums text-muted-foreground">{ш.amount} ₽</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function WorkTab({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  const [окно, setОкно] = useState<number>(90)
  const [толькоОтказы, setТолькоОтказы] = useState(false)

  const история = useQuery({
    queryKey: ['station-history', companyId, location.id, окно],
    queryFn: () => getStationHistory(companyId, location.id, окно),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  const визиты = useQuery({
    queryKey: ['station-visits', companyId, location.id, окно, толькоОтказы],
    queryFn: () => getStationVisits(companyId, location.id,
      { days: окно, onlyFailed: толькоОтказы }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  if (история.isLoading || визиты.isLoading) {
    return <ScrollTab><div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div></ScrollTab>
  }

  const h = история.data
  const v = визиты.data
  const w = h?.work

  return (
    <ScrollTab>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {ОКНА.map((о) => (
            <Button key={о} size="sm" variant={окно === о ? 'default' : 'outline'}
              className="h-7 px-2 text-xs" onClick={() => setОкно(о)}>
              {о} дн
            </Button>
          ))}
          {h && (
            <span className="text-xs text-muted-foreground">
              данные по {время(h.asOf)}
            </span>
          )}
        </div>

        {w && v && (
          <SectionCard title="Как работает" icon={PlugZap}>
            <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
              <InfoRow label="Приездов клиентов" value={nf.format(v.totals.visits)} />
              <InfoRow label="Уехали ни с чем"
                value={`${nf.format(v.totals.failed)} · ${v.totals.failedPct} %`} />
              <InfoRow label="Попыток на приезд" value={String(v.totals.attemptsPerVisit)} />
              <InfoRow label="Отпущено энергии" value={`${nf.format(w.energyKwh)} кВтч`} />
              <InfoRow label="Клиентов" value={nf.format(w.clients)} />
              <InfoRow label="Нагрузка на порт"
                value={w.sessionsPerPortDay != null
                  ? `${w.sessionsPerPortDay} сессий в сутки` : 'портов не знаем'} />
              <InfoRow label="Средняя сессия"
                value={w.avgMinutes != null ? `${w.avgMinutes} мин` : '—'} />
              <InfoRow label="Последняя зарядка"
                value={h.station.silentDays == null ? 'не было ни разу'
                  : h.station.silentDays === 0 ? 'сегодня'
                    : `${h.station.silentDays} дн назад`} />
              <InfoRow label="Выручка" value={`${nf.format(Math.round(w.revenue))} ₽`} />
            </div>
          </SectionCard>
        )}

        {h && h.breaks.length > 0 && (
          <SectionCard title={`Перерывы в работе · ${h.breaksTotal}`} icon={AlertTriangle}>
            <div className="space-y-1 text-sm">
              {h.breaks.slice(0, 8).map((b) => (
                <div key={b.from} className="flex flex-wrap items-center gap-2">
                  <span className="tabular-nums text-muted-foreground">
                    {время(b.from)} →
                  </span>
                  <span className="tabular-nums">
                    {b.ongoing ? 'идёт сейчас' : время(b.to!)}
                  </span>
                  <Badge variant={b.ongoing ? 'destructive' : 'secondary'} className="text-[11px]">
                    {b.days >= 1 ? `${b.days} дн` : `${b.hours} ч`}
                  </Badge>
                </div>
              ))}
            </div>
          </SectionCard>
        )}

        {v && v.totals.visits > 0 && (
          <SectionCard title="Почему приходится пробовать снова" icon={AlertTriangle}>
            <div className="space-y-1.5">
              {v.patterns.filter((к) => к.visits > 0).map((к) => (
                <div key={к.key} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                  <span className={cn('w-56 shrink-0 text-sm font-medium', ЦВЕТ_КАРТИНЫ[к.key])}>
                    {к.label}
                  </span>
                  <span className="w-28 shrink-0 tabular-nums text-sm">
                    {nf.format(к.visits)} · {к.pct} %
                  </span>
                  <span className="min-w-0 flex-1 text-xs text-muted-foreground">{к.hint}</span>
                </div>
              ))}
            </div>
            {v.empty.attempts > 0 && (
              <div className="mt-3 border-t border-border/40 pt-2 text-xs text-muted-foreground">
                Попыток без энергии {nf.format(v.empty.attempts)}: из них{' '}
                <b className="text-foreground">{nf.format(v.empty.instant)}</b> оборвались
                быстрее минуты, <b className="text-foreground">{nf.format(v.empty.stuck)}</b>{' '}
                тянулись дольше пяти. {v.empty.hint}
              </div>
            )}
          </SectionCard>
        )}

        {v && v.connectors.length > 0 && (
          <SectionCard title="На чём ломается" icon={PlugZap}>
            <div className="space-y-1 text-sm">
              {v.connectors.map((c) => (
                <div key={c.connector} className="flex flex-wrap items-center gap-3">
                  <span className="w-32 shrink-0">
                    коннектор {c.connector}
                    {c.type && <span className="ml-1 text-xs text-muted-foreground">{c.type}</span>}
                  </span>
                  <span className="w-28 tabular-nums text-muted-foreground">
                    {nf.format(c.attempts)} попыток
                  </span>
                  <span className={cn('w-28 tabular-nums font-medium',
                    c.failedPct >= 50 && 'text-red-600 dark:text-red-400')}>
                    с ошибкой {c.failedPct} %
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {nf.format(c.energyKwh)} кВтч
                  </span>
                </div>
              ))}
            </div>
          </SectionCard>
        )}

        {v && (
          <SectionCard title={`Приезды клиентов · показано ${v.returned}`} icon={PlugZap}>
            <div className="mb-2 flex items-center gap-2">
              <Button size="sm" variant={толькоОтказы ? 'outline' : 'default'}
                className="h-7 px-2 text-xs" onClick={() => setТолькоОтказы(false)}>
                Все
              </Button>
              <Button size="sm" variant={толькоОтказы ? 'default' : 'outline'}
                className="h-7 px-2 text-xs" onClick={() => setТолькоОтказы(true)}>
                Только «ни с чем»
              </Button>
              <span className="text-xs text-muted-foreground">{v.note}</span>
            </div>
            <div className="overflow-x-auto rounded border border-border/60">
              {v.visits.map((визит) => (
                <VisitRow key={визит.visitKey} визит={визит} />
              ))}
              {!v.visits.length && (
                <div className="p-6 text-center text-sm text-muted-foreground">
                  {толькоОтказы ? 'Приездов «ни с чем» за окно нет'
                    : 'За это окно на станцию никто не приезжал'}
                </div>
              )}
            </div>
          </SectionCard>
        )}
      </div>
    </ScrollTab>
  )
}
