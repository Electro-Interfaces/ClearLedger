/**
 * Заявки Поддержки по этому объекту — вторая сторона одного объекта пространства.
 *
 * Учёт и Поддержка смотрят на одну и ту же станцию; ось — общий объект
 * (docs/SPACE.md). Данные не копируем в Ledger: спрашиваем разрез в момент
 * показа, иначе в пространстве появилась бы вторая правда о заявках.
 *
 * Инженеру мало списка последних заявок — ему нужно понять, что это за станция
 * по истории обслуживания: сколько раз сюда уже ездили, что чинили, как долго
 * закрывают, срывались ли сроки. Поэтому сводка считается Поддержкой по ВСЕМ
 * заявкам объекта, а не по отданной странице: «20» из-за лимита выдачи было бы
 * неправдой ровно в том вопросе, ради которого сюда смотрят.
 */
import { useQuery } from '@tanstack/react-query'
import { LifeBuoy, ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getObjectTickets } from '@/services/spaceObjectsService'

const OPEN_LABEL: Record<string, string> = {
  new: 'Новая', open: 'Открыта', in_progress: 'В работе',
  waiting_customer: 'Ждём заказчика', waiting_partner: 'Ждём подрядчика',
  waiting: 'Ожидание', escalated: 'Эскалация',
  resolved: 'Решена', done: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена',
}

const ВИД_РАБОТЫ: Record<string, string> = {
  incident: 'отказ', request: 'заявка на работу', question: 'вопрос',
  problem: 'разбор причины', eco_object: 'работа по объекту',
}

const nf = new Intl.NumberFormat('ru-RU')

const дата = (iso?: string | null) => iso
  ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
  : '—'

/** Срок закрытия словами: «11 ч» читается, «11.3» — нет. */
function срок(часов: number | null | undefined): string {
  if (часов == null) return '—'
  if (часов < 24) return `${Math.round(часов)} ч`
  const дней = часов / 24
  return дней < 30 ? `${дней.toFixed(дней < 10 ? 1 : 0)} дн` : `${Math.round(дней / 30)} мес`
}

function Плитка({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: string
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

export function CoordinatorTickets({ objectId }: { objectId: string }) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['object-tickets', companyId, objectId],
    queryFn: () => getObjectTickets(companyId, objectId),
    enabled: !!companyId && !!objectId,
    staleTime: 60_000,
    retry: false,
  })

  // Приложение не подключено к этой компании — молчим: это не ошибка, а состояние.
  if (q.isError || (q.data && !q.data.linked)) return null

  const data = q.data
  const st = data?.stats
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium">
          <LifeBuoy className="size-4 text-primary" /> Заявки Поддержки
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-xs text-muted-foreground">
              открытых: {data.open} из {data.total}
            </span>
          )}
          <a href="/support/" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            Открыть <ExternalLink className="size-3" />
          </a>
        </div>
      </div>

      {q.isLoading && <p className="text-sm text-muted-foreground">Загрузка заявок…</p>}

      {/* История обслуживания станции: «как часто сюда ездят и чем это кончается». */}
      {st && st.total > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <Плитка label="Заявок всего" value={nf.format(st.total)}
            hint={st.firstAt ? `с ${дата(st.firstAt)}` : undefined} />
          <Плитка label="За последний год" value={nf.format(st.year)}
            hint={st.lastAt ? `последняя ${дата(st.lastAt)}` : undefined} />
          <Плитка label="Открыто сейчас" value={nf.format(st.open)}
            tone={st.open ? 'text-amber-600 dark:text-amber-400' : undefined} />
          <Плитка label="Закрывают в среднем" value={срок(st.avgHours)}
            hint="от заведения до закрытия" />
          <Плитка label="Со срывом срока" value={nf.format(st.breached)}
            hint={`срочных ${nf.format(st.urgent)}`}
            tone={st.breached ? 'text-red-600 dark:text-red-400' : undefined} />
        </div>
      )}

      {/* Что именно чинят: разрез по виду работ отвечает, беда разовая или та же. */}
      {st && st.kinds.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">что делали:</span>
          {st.kinds.map((k) => (
            <span key={k.kind ?? 'нет'} className="rounded bg-muted px-1.5 py-0.5">
              {ВИД_РАБОТЫ[k.kind ?? ''] ?? k.kind ?? 'вид не указан'}
              <span className="ml-1 text-muted-foreground">{k.count}</span>
            </span>
          ))}
        </div>
      )}

      {data && data.tickets.length === 0 && (
        <p className="text-sm text-muted-foreground">По объекту заявок нет.</p>
      )}

      <div className="space-y-2">
        {data?.tickets.map((t) => (
          <a key={t.id} href={`/support/customer/tickets/${t.id}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-border/50 p-3 transition-colors hover:bg-accent/30">
            <span className="font-mono text-xs font-medium">
              {t.display_number ?? `#${t.number}`}
            </span>
            <span className="flex-1 truncate text-sm">{t.title}</span>
            {t.assignee_name && (
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {t.assignee_name}
              </span>
            )}
            {t.sla_breached && (
              <Badge variant="secondary"
                className="bg-red-500/15 text-[10px] text-red-600 dark:text-red-400">
                срок сорван
              </Badge>
            )}
            <Badge variant="secondary" className="text-[10px]">
              {OPEN_LABEL[t.status] ?? t.status}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {дата(t.created_at)}
              {/* Дата закрытия рядом с датой заведения: по паре видно, станция
                  стояла сутки или полтора месяца. */}
              {(t.closed_at ?? t.resolved_at) && <> → {дата(t.closed_at ?? t.resolved_at)}</>}
            </span>
          </a>
        ))}
      </div>

      {data && data.total > data.tickets.length && (
        <p className="text-xs text-muted-foreground">
          показаны последние {data.tickets.length} из {nf.format(data.total)} —
          остальные в Поддержке.
        </p>
      )}
    </section>
  )
}
