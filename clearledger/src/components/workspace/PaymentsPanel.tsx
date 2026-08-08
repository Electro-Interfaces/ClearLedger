/**
 * Пункт «Платежи и чеки» — эквайринг ЭЗС из витрины АСУиМ.
 * Внутренние табы: Сводка · Помесячно · Реестр (с разборами).
 *
 * Зачем отдельно от «Сессий»: сессия говорит, сколько энергии отпущено, платёж —
 * сколько денег реально списано и есть ли на это фискальный чек. Расхождение
 * между ними и есть предмет разбора (зависшие холды, платежи без сессии).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, ExternalLink } from 'lucide-react'
import { Kpi } from './analytics/Kpi'
import { PanelViewTabs } from './PanelViewTabs'
import { useTabParams } from '@/hooks/useTabParams'
import {
  getPaymentsList, getPaymentsSummary,
  type PaymentLine, type PaymentsSummary,
} from '@/services/chargePaymentsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const money = (v: number) => nf0.format(Math.round(v || 0)) + ' ₽'
const rub = (v: number) => nf2.format(v || 0) + ' ₽'
const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0)

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text }: { text: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

const VIEWS = [
  { k: 'summary', label: 'Сводка' },
  { k: 'months', label: 'Помесячно' },
  { k: 'list', label: 'Реестр' },
] as const

const SLICES = [
  { k: '', label: 'Все' },
  { k: 'orphans', label: 'Без сессии' },
  { k: 'stuck', label: 'Зависшие холды' },
  { k: 'refunds', label: 'С возвратом' },
] as const

interface Props { companyId: string; dateFrom: string; dateTo: string }

export function PaymentsPanel({ companyId, dateFrom, dateTo }: Props) {
  const [t0, patch] = useTabParams('cs_payments', { view: 'summary' })
  const view = t0.view
  const setView = (k: string) => patch({ view: k })
  const [slice, setSlice] = useState<string>('')

  const { data, isLoading } = useQuery<PaymentsSummary>({
    queryKey: ['charge-payments', companyId, dateFrom, dateTo],
    queryFn: () => getPaymentsSummary({ companyId, dateFrom, dateTo }),
    enabled: !!companyId,
  })

  const list = useQuery<PaymentLine[]>({
    queryKey: ['charge-payments-list', companyId, dateFrom, dateTo, slice],
    queryFn: () => getPaymentsList({
      companyId, dateFrom, dateTo,
      only: (slice || undefined) as 'orphans' | 'stuck' | 'refunds' | undefined,
    }),
    enabled: !!companyId && view === 'list',
  })

  if (isLoading) return <Loading />
  if (!data || !data.totals.count) return <Empty text="За период платежей нет" />
  const t = data.totals

  return (
    <div className="space-y-4">
      <PanelViewTabs tabs={VIEWS} value={view} onChange={setView} />

      {view === 'summary' && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Списано" value={money(t.amount)} sub={`${nf0.format(t.count)} платежей`} />
            <Kpi label="Средний чек" value={rub(t.avgCheck)} />
            <Kpi label="Фискальный чек" value={`${pct(t.receipts, t.count)} %`}
                 sub={`${nf0.format(t.receipts)} из ${nf0.format(t.count)}`} />
            <Kpi label="Заблокировано (холд)" value={money(t.hold)}
                 sub={`возвращено ${money(t.refund)}`} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Kpi label="Зависшие холды" value={money(t.stuckAmount)}
                 sub={`${nf0.format(t.stuckCount)} платежей: деньги удержаны, списания и возврата нет`}
                 cls={t.stuckCount ? 'text-amber-600 dark:text-amber-400' : undefined} />
            <Kpi label="Платежей без сессии" value={nf0.format(t.orphans)}
                 sub={t.orphans ? 'сессия в Учёт ещё не загружена' : 'все платежи нашли свою сессию'}
                 cls={t.orphans ? 'text-amber-600 dark:text-amber-400' : undefined} />
          </div>
          <Card><CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">Тип операции</th>
                <th className="p-2 text-right font-medium">Платежей</th>
                <th className="p-2 text-right font-medium">Списано</th>
              </tr></thead>
              <tbody>
                {data.byType.map((r) => (
                  <tr key={r.name} className="border-b last:border-0">
                    <td className="p-2">{r.name}</td>
                    <td className="p-2 text-right tabular-nums">{nf0.format(r.count)}</td>
                    <td className="p-2 text-right tabular-nums">{money(r.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        </div>
      )}

      {view === 'months' && (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Месяц</th>
              <th className="p-2 text-right font-medium">Платежей</th>
              <th className="p-2 text-right font-medium">Списано</th>
              <th className="p-2 text-right font-medium">Возвращено</th>
              <th className="p-2 text-right font-medium">С чеком</th>
            </tr></thead>
            <tbody>
              {data.byMonth.map((r) => (
                <tr key={r.bucket} className="border-b last:border-0">
                  <td className="p-2">{r.bucket}</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(r.count)}</td>
                  <td className="p-2 text-right tabular-nums">{money(r.amount)}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{money(r.refund)}</td>
                  <td className="p-2 text-right tabular-nums">{pct(r.receipts, r.count)} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}

      {view === 'list' && (
        <div className="space-y-3">
          <PanelViewTabs tabs={SLICES} value={slice} onChange={setSlice} label="Разбор" />
          {list.isLoading ? <Loading /> : !list.data?.length ? <Empty text="Платежей в этом разрезе нет" /> : (
            <Card><CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium">Дата</th>
                  <th className="p-2 text-left font-medium">Платёж</th>
                  <th className="p-2 text-left font-medium">Сессия</th>
                  <th className="p-2 text-right font-medium">Списано</th>
                  <th className="p-2 text-right font-medium">Холд</th>
                  <th className="p-2 text-right font-medium">Возврат</th>
                  <th className="p-2 text-left font-medium">Чек</th>
                </tr></thead>
                <tbody>
                  {list.data.map((p) => (
                    <tr key={p.id} className="border-b last:border-0">
                      <td className="p-2 whitespace-nowrap">
                        {p.paidAt ? new Date(p.paidAt).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'}
                      </td>
                      <td className="p-2 tabular-nums">{p.id}</td>
                      <td className="p-2 tabular-nums text-muted-foreground">{p.sessionId || '—'}</td>
                      <td className="p-2 text-right tabular-nums">{money(p.amount)}</td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{money(p.hold)}</td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">{money(p.refund)}</td>
                      <td className="p-2">
                        {p.receiptUrl
                          ? <a href={p.receiptUrl} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1 text-primary hover:underline">
                              чек <ExternalLink className="h-3 w-3" />
                            </a>
                          : <span className="text-muted-foreground">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent></Card>
          )}
        </div>
      )}
    </div>
  )
}
