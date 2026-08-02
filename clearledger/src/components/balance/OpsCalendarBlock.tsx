/**
 * Календарь сбора документов — что и от кого ждём вперёд.
 *
 * Договоры переходящие: объект работает и в этом месяце, и в следующем, значит
 * сроки известны заранее и собирать документы надо по календарю, а не в
 * последний день месяца.
 *
 * Просроченное идёт первым и отдельной группой: это уже не план работы, а долг.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { CalendarClock, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { getOpsCalendar, type OpsCalendarBucket } from '@/services/opsService'

const money = (v: number) => fmtN(Math.round(v))

const dayLabel = (iso: string) => {
  const d = new Date(iso)
  const names = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
  return `${d.getDate()} ${names[d.getMonth()]}`
}

export function OpsCalendarBlock() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['ops-calendar', companyId],
    queryFn: () => getOpsCalendar(companyId!, 45),
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return <Card><CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Считаю сроки…
    </CardContent></Card>
  }
  if (q.isError || !q.data || q.data.buckets.length === 0) {
    return (
      <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
        Ближайших сроков нет. Либо всё собрано, либо ожидания ещё не развёрнуты —
        откройте «Закрытие месяца», шкала периодов развернёт их сама.
      </CardContent></Card>
    )
  }

  const { buckets } = q.data
  const overdue = buckets.find((b) => b.overdue)
  const upcoming = buckets.filter((b) => !b.overdue)

  return (
    <div className="space-y-3">
      {overdue && <Bucket bucket={overdue} />}
      {upcoming.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {upcoming.slice(0, 8).map((b) => <Bucket key={b.due} bucket={b} />)}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Срок берётся из условия договора: N-е число месяца, следующего за отчётным.
        Где в условии он не задан — десятое число.
      </p>
    </div>
  )
}

function Bucket({ bucket }: { bucket: OpsCalendarBucket }) {
  return (
    <Card className={bucket.overdue ? 'border-red-500/40' : undefined}>
      <CardContent className="space-y-2 pt-4">
        <div className="flex items-baseline gap-2">
          <CalendarClock className={`h-4 w-4 shrink-0 ${
            bucket.overdue ? 'text-red-500' : 'text-primary'}`} />
          <span className="text-sm font-medium">
            {bucket.overdue ? 'Просрочено' : `К ${dayLabel(bucket.due!)}`}
          </span>
          <span className="ml-auto text-sm tabular-nums">
            {fmtN(bucket.count)} · {money(bucket.gross)} ₽
          </span>
        </div>
        <div className="space-y-1">
          {bucket.byCounterparty.slice(0, 6).map((c) => (
            <div key={c.name} className="flex items-baseline gap-2 text-sm">
              <span className="truncate" title={c.objects.join(', ')}>{c.name}</span>
              <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">
                {c.count} · {money(c.gross)} ₽
              </span>
            </div>
          ))}
          {bucket.byCounterparty.length > 6 && (
            <div className="text-xs text-muted-foreground">
              и ещё {bucket.byCounterparty.length - 6} контрагентов
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
