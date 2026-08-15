/**
 * «Периметр» → «Движение и прогноз» — три вещи, на которые таблица не отвечает.
 *
 * **Мост изменения долга** отвечает «почему стало больше»: было → выдали → вернули →
 * закрыли отчётом → зачли → списали → стало. Возрастные корзины показывают «сколько и
 * как давно», но движение целиком видно только так. Каждая ступень — сумма операций
 * своего вида, а не расчётная разность, поэтому расхождение (если оно есть) честно
 * показывается, а не прячется подгонкой.
 *
 * **Прогноз потребности** строится из уже известных обязательств, а не из тренда:
 * регулярные выплаты разворачиваются по своим периодам, к ним добавляются сроки
 * возврата полученных займов. Каждая точка объяснима — в этом её смысл; средняя по
 * прошлым месяцам красива, но решений не меняет.
 *
 * **Сверка кошелька** — единственный способ узнать масштаб незаписанного. Расхождение
 * закрывается явной операцией с причиной, а не подгонкой остатка: подгонка молча
 * уменьшает то, что было, вместо того чтобы показать, что ушло мимо записи.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useFilters } from '@/contexts/FilterContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  doReconcile, getCashForecast, getDebtBridge, getReconcileState,
} from '@/services/perimeterService'
import { Loading, TableCard, Th } from './OfficePanels'
import { money, num } from './officeShared'

function Td({ children, right, muted }: {
  children: React.ReactNode; right?: boolean; muted?: boolean
}) {
  return (
    <td className={cn('px-3 py-2 align-top', right && 'text-right tabular-nums whitespace-nowrap',
      muted && 'text-muted-foreground')}>{children}</td>
  )
}

const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'
const today = () => new Date().toISOString().slice(0, 10)

export function CashToolsScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { period } = useFilters()
  const [purse, setPurse] = useState('owner')
  const [counted, setCounted] = useState('')
  const [note, setNote] = useState('')

  const bridge = useQuery({
    queryKey: ['perimeter', 'debt-bridge', companyId, period.from, period.to],
    queryFn: () => getDebtBridge(companyId, period.from, period.to),
    enabled: !!companyId,
  })
  const forecast = useQuery({
    queryKey: ['perimeter', 'forecast', companyId],
    queryFn: () => getCashForecast(companyId, 90),
    enabled: !!companyId,
  })
  const state = useQuery({
    queryKey: ['perimeter', 'reconcile', companyId, purse],
    queryFn: () => getReconcileState(companyId, purse),
    enabled: !!companyId,
  })
  const save = useMutation({
    mutationFn: () => doReconcile(companyId, {
      countedOn: today(), counted: Number(counted), purse, note: note || null,
    }),
    onSuccess: (r) => {
      toast.success(r.created
        ? `Расхождение ${money.format(r.diff)} ₽ записано операцией`
        : 'Пересчёт сошёлся с журналом')
      setCounted(''); setNote('')
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (bridge.isError || forecast.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать движение" onRetry={() => {
        bridge.refetch(); forecast.refetch()
      }} />
    </div>
  }
  if (!bridge.data || !forecast.data) return <Loading />
  const b = bridge.data
  const f = forecast.data
  const maxWeek = Math.max(...f.weeks.map((w) => w.amount), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Понадобится за 30 дней" value={`${money.format(f.next30)} ₽`}
          hint="по известным обязательствам и срокам" />
        <MetricTile label="Всего до конца горизонта" value={`${money.format(f.total)} ₽`}
          hint={`по ${f.horizon}`} />
        <MetricTile label="Не закрыто за людьми"
          value={`${money.format(b.steps.at(-1)?.amount ?? 0)} ₽`}
          hint="на конец периода: займы и подотчёт" />
      </div>

      <TableCard note={`Как изменился долг за ${b.from} — ${b.to}. Каждая ступень — сумма операций своего вида, а не разность`}
        head={<><Th>Ступень</Th><Th right>Сумма</Th></>}>
        {b.steps.map((s) => (
          <tr key={s.key} className={cn('border-b last:border-0',
            s.kind === 'total' && 'font-medium')}>
            <Td>{s.label}</Td>
            <Td right>
              <span className={cn(!!s.amount && s.kind === 'plus' && 'text-destructive',
                !!s.amount && s.kind === 'minus' && 'text-emerald-600')}>
                {s.kind === 'total' ? '' : s.amount > 0 ? '+' : ''}
                {money.format(s.amount)} ₽
              </span>
            </Td>
          </tr>
        ))}
      </TableCard>

      {Math.abs(b.checks.diff) > 0.01 && (
        <p className="text-[11px] text-destructive">
          Ступени не сходятся с остатком на {money.format(b.checks.diff)} ₽: часть
          движения прошла мимо видов операций. Расхождение показано, а не подогнано.
        </p>
      )}

      {f.weeks.length ? (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div>
              <div className="text-base font-medium">Когда понадобятся наличные</div>
              <div className="text-[11px] text-muted-foreground">
                По неделям, из регулярных обязательств и сроков возврата полученных займов
              </div>
            </div>
            <div className="space-y-1.5">
              {f.weeks.map((w) => (
                <div key={w.weekStart} className="flex items-center gap-2">
                  <span className="w-24 text-[11px] text-muted-foreground tabular-nums shrink-0">
                    с {w.weekStart.slice(8)}.{w.weekStart.slice(5, 7)}
                  </span>
                  <div className="flex-1 h-4 bg-muted rounded overflow-hidden">
                    <div className="h-full bg-primary/60"
                      style={{ width: `${Math.round((w.amount / maxWeek) * 100)}%` }} />
                  </div>
                  <span className="w-28 text-right text-sm tabular-nums shrink-0">
                    {money.format(w.amount)} ₽
                  </span>
                </div>
              ))}
            </div>
            <TableCard note="Каждая точка объяснима: это обязательство или срок возврата, а не среднее по прошлым месяцам"
              head={<><Th>Когда</Th><Th>Что</Th><Th right>Сколько</Th></>}>
              {f.points.slice(0, 20).map((p, i) => (
                <tr key={`${p.id}-${i}`} className="border-b last:border-0">
                  <Td><span className="tabular-nums">{p.date}</span></Td>
                  <Td>{p.what}</Td>
                  <Td right>{money.format(p.amount)} ₽</Td>
                </tr>
              ))}
            </TableCard>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Известных будущих выплат нет: регулярные обязательства не заведены, полученных
            займов со сроком возврата тоже.
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-4 space-y-3">
          <div>
            <div className="text-base font-medium">Пересчёт кошелька</div>
            <div className="text-[11px] text-muted-foreground">
              Раз в неделю пересчитать деньги и сравнить с журналом — единственный способ
              узнать, сколько ушло мимо записи. Расхождение станет операцией с причиной,
              а не тихой правкой остатка.
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-4 items-end">
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Чьи деньги
              </span>
              <select className={inputCls} value={purse}
                onChange={(e) => setPurse(e.target.value)}>
                <option value="owner">Личные средства</option>
                <option value="company">Наличные компании</option>
              </select>
            </label>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                По журналу
              </div>
              <div className="text-lg tabular-nums">
                {state.data ? `${money.format(state.data.byJournal)} ₽` : '—'}
              </div>
            </div>
            <label className="block space-y-1">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Насчитали, ₽
              </span>
              <input className={inputCls} type="number" step="0.01" value={counted}
                onChange={(e) => setCounted(e.target.value)} />
            </label>
            <Button size="sm" disabled={counted === '' || save.isPending}
              onClick={() => save.mutate()}>
              {save.isPending ? 'Записываем…' : 'Записать пересчёт'}
            </Button>
          </div>

          <input className={inputCls} value={note} placeholder="Причина расхождения, если знаете"
            onChange={(e) => setNote(e.target.value)} />

          {state.data?.lastCheckedOn && (
            <p className="text-[11px] text-muted-foreground">
              Последний пересчёт {state.data.lastCheckedOn}
              {state.data.lastDiff
                ? `, расхождение ${money.format(state.data.lastDiff)} ₽` : ''}
            </p>
          )}
          {counted !== '' && state.data && (
            <p className="text-[11px] text-muted-foreground">
              Разница составит{' '}
              <b className={cn(Number(counted) - state.data.byJournal < 0
                && 'text-destructive')}>
                {money.format(Number(counted) - state.data.byJournal)} ₽
              </b>
              {Number(counted) - state.data.byJournal < 0
                ? ' — деньги ушли мимо записи'
                : Number(counted) - state.data.byJournal > 0
                  ? ' — деньги пришли мимо записи' : ''}
            </p>
          )}
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        {num.format(f.points.length)} будущих выплат в горизонте прогноза.
      </p>
    </div>
  )
}
