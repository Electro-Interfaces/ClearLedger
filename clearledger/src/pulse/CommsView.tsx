/**
 * «Пульс» → «Команда» → «Переписка»: живёт ли общение.
 *
 * Директору нужен не пересказ чужих лент, а три ответа: пишут ли вообще, кто
 * именно из своих держит переписку и не остался ли клиент без ответа.
 *
 * Содержимого сообщений здесь нет и не будет — это разрез активности, а не
 * чтение чужой переписки. Кто с кем и о чём — в самих «Чатах», куда ведёт
 * ссылка внизу.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Mail, MessageSquare, Phone, UserRound } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseComms } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtDate, fmtNum } from './parts'

/** Каналы — словами: `call` в отчёте директору ничего не сообщает. */
const CHANNEL_LABEL: Record<string, string> = {
  call: 'Телефония', email: 'Почта', telegram: 'Telegram',
  whatsapp: 'WhatsApp', web: 'Сайт', chat: 'Чат',
}
const CHANNEL_ICON: Record<string, typeof Phone> = {
  call: Phone, email: Mail,
}

export function CommsView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-comms', company.id],
    queryFn: () => getPulseComms(company.id),
    refetchInterval: 10 * 60_000,
  })
  if (q.isLoading) return <PulseLoading what="переписки" />
  if (q.isError) return <PulseError what="активность переписки" onRetry={() => q.refetch()} />
  const d = q.data
  if (!d) return null

  const maxAuthor = Math.max(1, ...d.authors.map((a) => a.messages))
  const maxChannel = Math.max(1, ...d.channels.map((c) => c.threads))
  // Контур заведён, но им не пользуются — это не поломка и не повод для тревоги,
  // но и делать вид, что «активность есть», нельзя.
  const chatIdle = !d.authors.length

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <div className="grid min-w-0 gap-2 md:grid-cols-2">
        <section className="min-w-0 space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Кто пишет · за 30 дней
          </h2>
          {chatIdle ? (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                В чатах пространства за месяц никто не писал.
                {d.rooms_total > 0 && <> Комнат заведено {d.rooms_total} —
                  они создаются под приложения автоматически, и пока это только
                  каркас, а не переписка.</>}
              </CardContent>
            </Card>
          ) : (
            <Card className="py-0">
              <CardContent className="divide-y divide-border/40 p-0">
                {d.authors.map((a) => (
                  <div key={a.name} className="flex items-center gap-3 px-3 py-2 text-xs">
                    <UserRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-[13px]">{a.name}</span>
                    <div className="hidden h-1.5 w-20 shrink-0 rounded bg-muted sm:block">
                      <div className="h-1.5 rounded bg-primary/60"
                        style={{ width: `${(a.messages / maxAuthor) * 100}%` }} />
                    </div>
                    <span className="w-12 shrink-0 text-right font-semibold tabular-nums">
                      {fmtNum(a.messages)}
                    </span>
                    <span className="hidden w-20 shrink-0 text-right text-muted-foreground sm:block">
                      {a.rooms} комн.
                    </span>
                    <span className="w-16 shrink-0 text-right text-muted-foreground">
                      {fmtDate(a.last)}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </section>

        <section className="min-w-0 space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Чем пишут клиенты
          </h2>
          {d.channels.length ? (
            <Card className="py-0">
              <CardContent className="divide-y divide-border/40 p-0">
                {d.channels.map((c) => {
                  const Icon = CHANNEL_ICON[c.channel] ?? MessageSquare
                  const delta = c.week - c.prev
                  return (
                    <div key={c.channel} className="flex items-center gap-3 px-3 py-2 text-xs">
                      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-[13px]">
                        {CHANNEL_LABEL[c.channel] ?? c.channel}
                      </span>
                      <div className="hidden h-1.5 w-16 shrink-0 rounded bg-muted sm:block">
                        <div className="h-1.5 rounded bg-primary/60"
                          style={{ width: `${(c.threads / maxChannel) * 100}%` }} />
                      </div>
                      <span className="w-16 shrink-0 text-right font-semibold tabular-nums">
                        {fmtNum(c.week)}
                      </span>
                      {/* Поток обращений — контекст, а не оценка: и рост, и спад
                          сами по себе ни хороши, ни плохи. */}
                      <span className="w-16 shrink-0 text-right text-muted-foreground tabular-nums">
                        {delta ? (delta > 0 ? `+${delta}` : delta) : '—'}
                      </span>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          ) : (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                Каналов обращений в пространстве нет — контакт-центр не подключён.
              </CardContent>
            </Card>
          )}
        </section>
      </div>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Почта пространства
        </h2>
        <Card className="py-0">
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3 text-xs">
            <span>
              входящих <span className="font-semibold tabular-nums">{fmtNum(d.mail.inbound)}</span>
            </span>
            <span>
              исходящих <span className="font-semibold tabular-nums">{fmtNum(d.mail.outbound)}</span>
            </span>
            <span className="text-muted-foreground">
              последнее письмо: {d.mail.last ? fmtDate(d.mail.last) : 'не было'}
            </span>
            {!d.mail.outbound && (
              <span className={cn('text-amber-600 dark:text-amber-400')}>
                исходящих нет — ящиком пока не отвечают
              </span>
            )}
          </CardContent>
        </Card>
      </section>

      <div className="flex flex-wrap items-center gap-4">
        <a href="/messages"
          className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
          Открыть чаты<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
        <a href="/support/"
          className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
          Обращения клиентов — в контакт-центре<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  )
}
