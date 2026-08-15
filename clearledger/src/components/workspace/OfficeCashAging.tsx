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
import { getCashAging } from '@/services/perimeterService'
import { PerimeterExport } from './perimeterShared'
import { Loading, TableCard, Th } from './OfficePanels'
import { money, num , Td } from './officeShared'

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
        <MetricTile label="Осталось за людьми" value={`${money.format(d.total)} ₽`}
          hint={`${num.format(d.rows.length)} выдач`} />
        <MetricTile label="Из личных средств" value={`${money.format(owner)} ₽`}
          hint="деньги собственника у людей" />
        <MetricTile label="Подотчёт просрочен" value={num.format(d.overdueReports.length)}
          hint={`срок отчёта — ${d.advanceDays} дн.`}
          tone={d.overdueReports.length ? 'danger' : undefined} />
        <MetricTile label="Право сгорает" value={num.format(d.expiring.length)}
          hint={d.expired.length
            ? `в ближайшие 90 дней; ${num.format(d.expired.length)} уже сгорело`
            : 'в ближайшие 90 дней'}
          tone={d.expiring.length || d.expired.length ? 'warning' : undefined} />
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
            {/* Выгрузка живёт дальше сама по себе — её след остаётся в журнале. */}
            <PerimeterExport companyId={companyId} title="Возраст выдач"
              columns={[
                { header: 'Дата', key: 'happenedOn', width: 13 },
                { header: 'Кому', key: 'person', width: 30 },
                { header: 'Вид', key: 'kindLabel', width: 22 },
                { header: 'За что', key: 'purpose', width: 40 },
                { header: 'Выдано', key: 'amount', width: 16, money: true },
                { header: 'Осталось', key: 'rest', width: 16, money: true },
                { header: 'Возраст, дней', key: 'age', width: 14 },
                { header: 'Право сгорает', key: 'limitationExpiresOn', width: 16 },
              ]}
              rows={d.rows} />
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
                        && (r.limitationDaysLeft ?? 0) <= 90 && 'text-amber-700 dark:text-amber-400')}>
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

      {!!d.takenRest && (
        <Card>
          <CardContent className="p-4 text-sm space-y-1">
            <div className="font-medium">Что должны мы</div>
            <p className="text-muted-foreground">
              Полученные займы на {money.format(d.takenRest)} ₽ в счёт выше не входят:
              возраст и сроки давности считаются по тому, что должны нам. Наш долг —
              другой разговор и другой срок, и складывать их в одну цифру значило бы
              сказать, что долг знакомого гасит наш.
            </p>
            <ul className="text-[11px] text-muted-foreground space-y-0.5 pt-1">
              {d.takenRows.slice(0, 6).map((r) => (
                <li key={r.id} className="tabular-nums">
                  {r.happenedOn} · {r.person} · {money.format(r.rest ?? 0)} ₽
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
