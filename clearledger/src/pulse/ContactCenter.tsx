/**
 * «Пульс» → «Бизнес» → «Обращения»: разговор с потребителем глазами руководителя.
 *
 * Единственный пункт «Бизнеса» со СВОЕЙ витриной. Причина: рабочее место
 * контакт-центра отвечает оператору («что мне взять в работу»), а руководителю
 * нужны четыре других ответа — дозвонились ли до нас, быстро ли ответили, не
 * брошены ли хвосты и не ходит ли клиент по кругу. Лента обращений, карточки
 * контактов, записи разговоров и шаблоны сюда НЕ переезжают: за ними — ссылка
 * в само приложение.
 *
 * Хорошо/плохо определяет не «Пульс», а цели самого контакт-центра
 * (`cc_kpi_targets`): иначе экран ругался бы на цифры, которые операторы своей
 * нормой не считают.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Clock, Headphones } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseContactCenter } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum } from './parts'

/** Час суток → «09:00»: ось профиля читают глазами, а не считают в уме. */
const hh = (h: number) => `${String(h).padStart(2, '0')}`

export function ContactCenterView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-contact-center', company.id],
    queryFn: () => getPulseContactCenter(company.id),
    // Телефония приезжает синхронизацией каждые 5 минут — чаще смысла нет.
    refetchInterval: 5 * 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="обращений" />
  if (q.isError) return <PulseError what="картину обращений" onRetry={() => q.refetch()} />
  if (d && !d.available) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Телефония в пространстве не подключена — показывать пока нечего.
          Контакт-центр включается коннектором в «Управлении».
        </CardContent>
      </Card>
    )
  }
  if (!d) return null

  const maxHour = Math.max(1, ...d.hours.map((h) => h.calls))
  const maxOp = Math.max(1, ...d.operators.map((o) => o.calls))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      {/* Два хвоста одной строкой: цифры уже есть в карточках экрана дня, здесь
          они нужны как контекст, а не как второй набор эскалаций. */}
      {(d.stuck || d.escalations) ? (
        <Card className={cn('py-0', d.escalations && 'border-amber-500/40 bg-amber-500/5')}>
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3 text-xs">
            {!!d.stuck && (
              <span>
                <span className="font-semibold tabular-nums">{fmtNum(d.stuck)}</span>
                {' '}обращений в разборе с просроченным ответом
              </span>
            )}
            {!!d.escalations && (
              <span className="text-amber-700 dark:text-amber-400">
                <span className="font-semibold tabular-nums">{fmtNum(d.escalations)}</span>
                {' '}передано выше по линии и не разобрано
              </span>
            )}
          </CardContent>
        </Card>
      ) : null}

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Когда не отвечают · за 7 дней
          </h2>
          <span className="text-[11px] text-muted-foreground">время московское</span>
        </div>
        {/* Профиль суток отвечает на вопрос, который суточная доля скрывает:
            ночь, обед и утренний пик — это три разных разговора с подрядчиком. */}
        <Card className="py-0">
          <CardContent className="p-3">
            <div className="flex h-28 items-end gap-px">
              {d.hours.map((h) => {
                const answered = h.calls - h.missed
                const share = h.calls ? h.missed / h.calls : 0
                return (
                  <div key={h.hour} className="flex flex-1 flex-col items-center justify-end gap-1"
                    title={`${hh(h.hour)}:00 — ${h.calls} звонков, пропущено ${h.missed}`}>
                    <div className="flex w-full flex-col justify-end"
                      style={{ height: `${Math.max(3, Math.round((h.calls / maxHour) * 84))}px` }}>
                      {/* Пропущенные — верхней частью столбца: видно и объём,
                          и какую его долю мы потеряли. */}
                      <div className={cn('w-full rounded-t',
                        share > 0.3 ? 'bg-red-500/70' : 'bg-amber-500/70')}
                        style={{ height: `${Math.round(share * 100)}%` }} />
                      <div className="w-full bg-primary/50"
                        style={{ height: `${Math.round((answered / (h.calls || 1)) * 100)}%` }} />
                    </div>
                    <span className="text-[10px] tabular-nums text-muted-foreground">
                      {h.hour % 3 === 0 ? hh(h.hour) : ''}
                    </span>
                  </div>
                )
              })}
            </div>
            <div className="mt-2 flex items-center gap-4 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-primary/50" />приняли
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-amber-500/70" />пропустили
              </span>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Кто отвечает · за 7 дней
        </h2>
        {d.operators.length ? (
          <Card className="py-0">
            <CardContent className="divide-y p-0">
              {d.operators.map((o) => (
                <div key={o.name} className="flex items-center gap-3 px-3 py-2">
                  <Headphones className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{o.name}</span>
                  {/* Полоса нагрузки: перекос «один тянет три четверти» виден
                      сразу, а по столбику цифр его пришлось бы вычислять. */}
                  <div className="hidden h-1.5 w-32 shrink-0 rounded bg-muted sm:block">
                    <div className="h-1.5 rounded bg-primary/60"
                      style={{ width: `${(o.calls / maxOp) * 100}%` }} />
                  </div>
                  <span className="w-16 shrink-0 text-right text-sm font-semibold tabular-nums">
                    {fmtNum(o.calls)}
                  </span>
                  <span className="hidden w-24 shrink-0 items-center justify-end gap-1 text-[11px] text-muted-foreground md:flex">
                    <Clock className="h-3 w-3" />
                    {o.talk != null ? `${Math.round(o.talk / 60)} мин` : '—'}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed py-0">
            <CardContent className="p-4 text-xs text-muted-foreground">
              За неделю принятых звонков с указанным оператором не было.
            </CardContent>
          </Card>
        )}
      </section>

      {/* Лестница погружения: дальше — рабочее место контакт-центра, где есть
          лента, записи разговоров и карточка клиента. */}
      <a href="/support/" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Открыть контакт-центр<ArrowUpRight className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}
