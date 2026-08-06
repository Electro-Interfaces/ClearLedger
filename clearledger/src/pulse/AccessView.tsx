/**
 * «Пульс» → «Команда» → «Доступ»: то, что касается руководителя лично.
 *
 * Не слежка за присутствием (PULSE.md §3): «Люди» рядом показывают нагрузку и
 * затор. Здесь другое — риск. Права переживают людей: человек ушёл из проекта,
 * а полный доступ у него остался; кого-то позвали, и он не дошёл. Целиком это
 * видно только руководителю пространства.
 */
import { useQuery } from '@tanstack/react-query'
import { KeyRound, ShieldAlert, UserRound } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseAccess } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtDate } from './parts'

/** Действия журнала — словами: `member.access` руководителю ничего не говорит. */
const ACTION_LABEL: Record<string, string> = {
  'user.create': 'заведён человек',
  'user.remove': 'человек удалён',
  'member.access': 'изменены права',
  'member.scope': 'изменён охват объектов',
  'member.party': 'изменён тип участия',
  'role.create': 'создана роль',
  'role.update': 'изменена роль',
  'invite.create': 'отправлено приглашение',
}

export function AccessView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-access', company.id],
    queryFn: () => getPulseAccess(company.id),
    refetchInterval: 10 * 60_000,
  })
  if (q.isLoading) return <PulseLoading what="состава и доступа" />
  if (q.isError) return <PulseError what="состав и доступ" onRetry={() => q.refetch()} />
  const d = q.data
  if (!d) return null

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Давно не заходили
        </h2>
        {d.dormant.length ? (
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.dormant.map((p) => {
                const admin = p.role === 'admin'
                return (
                  <div key={p.email} className="flex items-center gap-3 px-3 py-2 text-xs">
                    {/* Спящий админ — это не «неактивный пользователь», это
                        открытая дверь: подсвечиваем отдельно. */}
                    {admin
                      ? <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                      : <UserRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px]">{p.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">{p.email}</div>
                    </div>
                    {p.party === 'partner' && (
                      <Badge variant="outline" className="shrink-0 px-1.5 py-0 text-[10px] font-normal">
                        внешний
                      </Badge>
                    )}
                    <Badge variant="outline"
                      className={cn('shrink-0 px-1.5 py-0 text-[10px] font-normal',
                        admin && 'border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400')}>
                      {admin ? 'полный доступ' : p.role}
                    </Badge>
                    <span className="w-28 shrink-0 text-right text-muted-foreground">
                      {p.last_seen ? fmtDate(p.last_seen) : 'ни разу не заходил'}
                    </span>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed py-0">
            <CardContent className="p-4 text-xs text-muted-foreground">
              Все участники заходили за последний месяц.
            </CardContent>
          </Card>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Что меняли в составе и правах · за месяц
        </h2>
        <Card className="py-0">
          <CardContent className="space-y-1.5 p-3">
            {d.events.length ? d.events.map((e, i) => (
              <div key={i} className="flex min-w-0 gap-2 text-xs">
                <KeyRound className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="shrink-0 tabular-nums text-muted-foreground">{fmtDate(e.at)}</span>
                <span className="shrink-0">{ACTION_LABEL[e.action] ?? e.action}</span>
                <span className="truncate text-muted-foreground" title={e.details ?? undefined}>
                  {e.who}{e.details ? ` · ${e.details}` : ''}
                </span>
              </div>
            )) : (
              <div className="text-xs text-muted-foreground">
                За месяц состав и права не меняли.
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
