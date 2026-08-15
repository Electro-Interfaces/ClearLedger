/**
 * «Периметр» → «Возраст и сроки» — сколько висит невозвращённое и когда оно сгорит.
 *
 * Два разных срока, и путать их нельзя. **Возраст** — сколько дней деньги у человека:
 * чем дольше висит невозвращённый и неотчитанный подотчёт, тем выше риск, что его
 * признают доходом человека со всеми последствиями. **Исковая давность** — когда право
 * требования сгорает: после трёх лет взыскать через суд нельзя.
 *
 * Второй срок продукт считает не от выдачи, а от последнего признания долга — частичной
 * оплаты, акта сверки, просьбы об отсрочке. Такое действие прерывает срок, и он течёт
 * заново; поэтому акт сверки здесь не бумагомарание, а продление права требования.
 */
import { useQuery } from '@tanstack/react-query'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import { exportTable } from '@/services/booksExport'
import { getCashAging, logExport } from '@/services/perimeterService'
import { Loading, TableCard, Th } from './OfficePanels'
import { ExportButton, money, num } from './officeShared'

function Td({ children, right, muted }: {
  children: React.ReactNode; right?: boolean; muted?: boolean
}) {
  return (
    <td className={cn('px-3 py-2 align-top', right && 'text-right tabular-nums whitespace-nowrap',
      muted && 'text-muted-foreground')}>{children}</td>
  )
}

export function CashAgingScreen({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['perimeter', 'cash-aging', companyId],
    queryFn: () => getCashAging(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать возраст выдач" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data
  const owner = d.byPurse.find((p) => p.key === 'owner')?.amount ?? 0

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Не закрыто" value={`${money.format(d.total)} ₽`}
          hint={`${num.format(d.rows.length)} выдач`} />
        <MetricTile label="Из личных средств" value={`${money.format(owner)} ₽`}
          hint="деньги собственника у людей" />
        <MetricTile label="Подотчёт просрочен" value={num.format(d.overdueReports.length)}
          hint={`срок отчёта — ${d.advanceDays} дн.`}
          tone={d.overdueReports.length ? 'danger' : undefined} />
        <MetricTile label="Право сгорает" value={num.format(d.expiring.length)}
          hint="в ближайшие 90 дней"
          tone={d.expiring.length ? 'warning' : undefined} />
      </div>

      {!d.rows.length ? (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Незакрытых выдач нет: займы возвращены, подотчёт закрыт отчётами.
          </CardContent>
        </Card>
      ) : (
        <>
          <TableCard note="Чем дольше висит невозвращённое, тем выше риск, что налоговая признает его доходом человека"
            head={<><Th>Возраст</Th><Th right>Выдач</Th><Th right>Сумма</Th></>}>
            {d.buckets.map((b) => (
              <tr key={b.key} className="border-b last:border-0">
                <Td>{b.label}</Td>
                <Td right muted>{b.count ? num.format(b.count) : '—'}</Td>
                <Td right>{b.amount ? `${money.format(b.amount)} ₽` : '—'}</Td>
              </tr>
            ))}
          </TableCard>

          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Незакрытые выдачи
            </div>
            <ExportButton onClick={() => {
              exportTable('Возраст выдач', [
                { header: 'Дата', key: 'happenedOn', width: 13 },
                { header: 'Кому', key: 'person', width: 30 },
                { header: 'Вид', key: 'kindLabel', width: 22 },
                { header: 'За что', key: 'purpose', width: 40 },
                { header: 'Выдано', key: 'amount', width: 16, money: true },
                { header: 'Осталось', key: 'rest', width: 16, money: true },
                { header: 'Дней', key: 'age', width: 10 },
                { header: 'Право сгорает', key: 'limitationExpiresOn', width: 16 },
              ], d.rows)
              // Выгрузка живёт дальше сама по себе — её след остаётся в журнале.
              logExport(companyId, 'Возраст выдач', d.rows.length)
            }} />
          </div>
          <TableCard note="«Право сгорает» считается от последнего признания долга: частичная оплата или подписанный акт сверки продлевают срок на три года"
            head={<><Th>Кому и за что</Th><Th right>Осталось</Th><Th right>Дней у человека</Th>
              <Th>Право сгорает</Th></>}>
            {d.rows.map((r) => (
              <tr key={r.id} className={cn('border-b last:border-0',
                r.overdueReport && 'bg-destructive/5')}>
                <Td>
                  <div>{r.person}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {r.kindLabel}{r.purpose ? ` · ${r.purpose}` : ''} · {r.purseLabel.toLowerCase()}
                  </div>
                </Td>
                <Td right>{money.format(r.rest ?? 0)} ₽</Td>
                <Td right>
                  {num.format(r.age)}
                  {r.overdueReport && (
                    <div className="text-[11px] text-destructive">отчёт просрочен</div>
                  )}
                </Td>
                <Td>
                  {r.limitationExpiresOn ? (
                    <>
                      <span className={cn('tabular-nums',
                        (r.limitationDaysLeft ?? 0) < 0 && 'text-destructive',
                        (r.limitationDaysLeft ?? 0) >= 0
                        && (r.limitationDaysLeft ?? 0) <= 90 && 'text-amber-600')}>
                        {r.limitationExpiresOn}
                      </span>
                      <div className="text-[11px] text-muted-foreground">
                        {(r.limitationDaysLeft ?? 0) < 0
                          ? 'срок истёк'
                          : `осталось ${num.format(r.limitationDaysLeft ?? 0)} дн.`}
                        {r.limitationBase ? ` · от «${r.limitationBase}»` : ''}
                      </div>
                    </>
                  ) : '—'}
                </Td>
              </tr>
            ))}
          </TableCard>
        </>
      )}

      {!!d.expiring.length && (
        <Card>
          <CardContent className="p-4 text-sm space-y-2">
            <div className="font-medium text-amber-700 dark:text-amber-500">
              Право требования скоро сгорит
            </div>
            <p className="text-muted-foreground">
              По этим выдачам срок исковой давности истекает в ближайшие три месяца.
              Прервать его можно действием должника, из которого видно, что он долг
              признаёт: частичной оплатой, подписанным актом сверки, письменной просьбой
              об отсрочке. После этого срок начинает течь заново — отметьте признание в
              карточке операции.
            </p>
            <ul className="text-[11px] text-muted-foreground space-y-0.5">
              {d.expiring.slice(0, 8).map((r) => (
                <li key={r.id} className="tabular-nums">
                  {r.limitationExpiresOn} · {r.person} · {money.format(r.rest ?? 0)} ₽
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {d.disclaimer && (
        <p className="text-[11px] text-muted-foreground">{d.disclaimer}</p>
      )}
    </div>
  )
}
