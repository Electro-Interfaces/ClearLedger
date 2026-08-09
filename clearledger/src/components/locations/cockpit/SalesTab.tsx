/**
 * Реализация станции — продажи в разрезе конкретной точки.
 * АЗС: P&L + структура оплат + последняя смена (STS). ЭЗС: сессии, энергия,
 * деньги и чеки из витрины АСУиМ. Прочие типы — каркас/заглушка.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Wallet, Fuel, Banknote, CreditCard, Ticket, GitCompare, ChevronLeft, ChevronRight,
  Zap, Box, Loader2, Receipt,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { locationStationNumber } from '@/components/reconciliation/locationMapping'
import { useStationPnL, useStationPaymentMix, useStationLastShift } from '@/hooks/useStationData'
import { fmtMoney, fmtMoneyShort, fmtLiters, fmtPct } from '@/services/analyticsService'
import { getStationSales, type StationSales } from '@/services/chargePaymentsService'
import type { ServiceLocation } from '@/types/location'
import { SectionCard, InfoRow, Placeholder, WipBadge, ScrollTab, typeFlags } from './shared'
import { MetricTile as Kpi } from '@/components/ui/metric-tile'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function monthBounds(year: number, month: number) {
  const first = new Date(year, month - 1, 1)
  const last = new Date(year, month, 0)
  return { from: first.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10) }
}

export function SalesTab({ location }: { location: ServiceLocation }) {
  const flags = typeFlags(location.type)

  if (flags.isEv) return <EvSales location={location} />

  if (!flags.isFuel) {
    if (flags.isRetail || flags.isFood) {
      return (
        <ScrollTab>
          <SectionCard title="Розничные продажи" icon={Wallet} muted action={<WipBadge />}>
            <InfoRow label="Чеков" value="—" />
            <InfoRow label="Выручка" value="—" />
          </SectionCard>
          <p className="text-xs text-muted-foreground/70">
            Продажи сопутки/общепита по станции появятся после привязки чеков к точке.
          </p>
        </ScrollTab>
      )
    }
    return (
      <ScrollTab>
        <Placeholder icon={Box} title="Реализация не ведётся"
          text="Для офисов и складов продажи не учитываются." />
      </ScrollTab>
    )
  }

  return <FuelSales location={location} />
}

/**
 * Реализация ЭЗС: сессии → энергия → деньги → чек, по этой точке.
 *
 * Две суммы намеренно разные и стоят рядом. «Отпущено на сумму» — сколько
 * начислено по сессиям, «списано эквайрингом» — сколько банк реально снял с
 * карт. Расходятся они не от ошибки: у ЮЛ постоплата (платежа в эквайринге нет
 * вовсе), а на краях периода платежи выгружены глубже, чем сессии. Показывать
 * одну цифру вместо двух — значит прятать этот разрыв.
 */
function EvSales({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  const { data, isLoading } = useQuery<StationSales>({
    queryKey: ['station-sales', companyId, location.id],
    queryFn: () => getStationSales(companyId!, location.id),
    enabled: !!companyId && !!location.id,
  })

  if (isLoading) {
    return (
      <ScrollTab>
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </ScrollTab>
    )
  }

  const t = data?.totals
  if (!t || !t.sessions) {
    return (
      <ScrollTab>
        <Placeholder icon={Zap} title="Зарядных сессий нет"
          text="По этой станции в Учёте нет ни одной сессии: либо она ещё не работала, либо не сопоставлена с выгрузкой (вкладка «Интеграции»)." />
      </ScrollTab>
    )
  }

  const period = [t.firstAt, t.lastAt]
    .map((d) => (d ? new Date(d).toLocaleDateString('ru-RU') : null))
    .filter(Boolean).join(' — ')
  const receiptPct = t.payments ? Math.round((t.receipts / t.payments) * 100) : 0

  return (
    <ScrollTab>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Сессий" value={nf0.format(t.sessions)} sub={period || undefined} />
        <Kpi label="Отпущено" value={`${nf0.format(t.kwh)} кВт·ч`} />
        <Kpi label="Отпущено на сумму" value={`${fmtMoneyShort(t.amount)} ₽`}
             sub={`средняя ${fmtMoney(t.avgCheck)} ₽`} />
        <Kpi label="Клиентов" value={nf0.format(t.clients)} />
      </div>

      <SectionCard title="Деньги и чеки" icon={Receipt}>
        <InfoRow label="Списано эквайрингом"
          value={`${fmtMoney(t.paid)} ₽ · ${nf0.format(t.payments)} платежей`} />
        <InfoRow label="Фискальный чек"
          value={`${receiptPct} % · ${nf0.format(t.receipts)} из ${nf0.format(t.payments)}`} />
        <InfoRow label="Заблокировано (холд)"
          value={`${fmtMoney(t.hold)} ₽ · возвращено ${fmtMoney(t.refund)} ₽`} />
        <InfoRow label="Сессий без платежа"
          value={t.unpaidSessions
            ? `${nf0.format(t.unpaidSessions)} — постоплата ЮЛ или платёж ещё не выгружен`
            : 'нет'} />
      </SectionCard>

      {!!data?.byMonth.length && (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Месяц</th>
              <th className="p-2 text-right font-medium">Сессий</th>
              <th className="p-2 text-right font-medium">кВт·ч</th>
              <th className="p-2 text-right font-medium">Отпущено на</th>
              <th className="p-2 text-right font-medium">Списано</th>
              <th className="p-2 text-right font-medium">С чеком</th>
            </tr></thead>
            <tbody>
              {data.byMonth.map((m) => (
                <tr key={m.bucket} className="border-b last:border-0">
                  <td className="p-2">{m.bucket}</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(m.sessions)}</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(m.kwh)}</td>
                  <td className="p-2 text-right tabular-nums">{fmtMoney(m.amount)} ₽</td>
                  <td className="p-2 text-right tabular-nums">{fmtMoney(m.paid)} ₽</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">
                    {m.payments ? `${Math.round((m.receipts / m.payments) * 100)} %` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
    </ScrollTab>
  )
}

/** Реализация АЗС: P&L + оплаты + последняя смена (STS). */
function FuelSales({ location }: { location: ServiceLocation }) {
  const navigate = useNavigate()
  const { companyId } = useCompany()
  const stationId = locationStationNumber(location)

  const now = new Date()
  const [ym, setYm] = useState({ year: now.getFullYear(), month: now.getMonth() + 1 })
  const { from, to } = monthBounds(ym.year, ym.month)
  const periodLabel = new Date(ym.year, ym.month - 1, 1)
    .toLocaleString('ru-RU', { month: 'long', year: 'numeric' })

  const shiftMonth = (delta: number) => setYm(({ year, month }) => {
    const m = month + delta
    if (m < 1) return { year: year - 1, month: 12 }
    if (m > 12) return { year: year + 1, month: 1 }
    return { year, month: m }
  })

  const pnlQ = useStationPnL(stationId, companyId, from, to)
  const mixQ = useStationPaymentMix(stationId, companyId, from, to)
  const { lastShift, reportQ } = useStationLastShift(stationId)

  if (stationId == null) {
    return (
      <ScrollTab>
        <Placeholder icon={Fuel} title="Станция не сопоставлена с STS"
          text="Укажите номер станции в привязке источника (вкладка «Интеграции») — тогда здесь появятся продажи и P&L." />
      </ScrollTab>
    )
  }

  const t = pnlQ.data?.totals
  const mix = mixQ.data
  const report = reportQ.data

  return (
    <ScrollTab>
      {/* Период */}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => shiftMonth(-1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-40 text-center text-sm font-medium capitalize">{periodLabel}</span>
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => shiftMonth(1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* P&L KPI */}
      {pnlQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка показателей…</p>}
      {t && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Выручка" value={`${fmtMoneyShort(t.revenue)} ₽`} sub={`нетто ${fmtMoneyShort(t.revenue_net)}`} />
          <Kpi label="Маржа" value={`${fmtMoneyShort(t.gross_margin)} ₽`} sub={fmtPct(t.gross_margin_pct)} />
          <Kpi label="Реализация" value={fmtLiters(t.liters)} />
          <Kpi label="Смен в периоде" value={String(pnlQ.data?.shifts_count ?? 0)} />
        </div>
      )}

      {/* Структура оплат */}
      <SectionCard title="Структура оплат" icon={Wallet}>
        {mixQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
        {mix && (
          <div className="space-y-1.5">
            <InfoRow label={<span className="inline-flex items-center gap-1.5"><Banknote className="h-3.5 w-3.5" /> Наличные</span>}
              value={`${fmtMoney(mix.breakdown.cash)} ₽ · ${mix.shares_pct.cash.toFixed(1)}%`} />
            <InfoRow label={<span className="inline-flex items-center gap-1.5"><CreditCard className="h-3.5 w-3.5" /> Карты</span>}
              value={`${fmtMoney(mix.breakdown.card)} ₽ · ${mix.shares_pct.card.toFixed(1)}%`} />
            <InfoRow label={<span className="inline-flex items-center gap-1.5"><Ticket className="h-3.5 w-3.5" /> Талоны</span>}
              value={`${fmtMoney(mix.breakdown.voucher)} ₽ · ${mix.shares_pct.voucher.toFixed(1)}%`} />
            <InfoRow label="Прочее"
              value={`${fmtMoney(mix.breakdown.other)} ₽ · ${mix.shares_pct.other.toFixed(1)}%`} />
            <div className="flex justify-between pt-1.5 text-sm font-medium">
              <span>Итого</span>
              <span className="tabular-nums">{fmtMoney(mix.total_amount)} ₽</span>
            </div>
          </div>
        )}
      </SectionCard>

      {/* Последняя смена */}
      <SectionCard title="Последняя закрытая смена" icon={Fuel}>
        {reportQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
        {!reportQ.isLoading && !report && <p className="text-sm text-muted-foreground">Нет закрытых смен.</p>}
        {report && (
          <div className="space-y-1.5">
            <InfoRow label="Смена №" value={<span className="font-mono">{lastShift?.shift}</span>} />
            <InfoRow label="Закрыта" value={lastShift?.dt_close ? new Date(lastShift.dt_close).toLocaleString('ru-RU') : '—'} />
            <InfoRow label="Реализация" value={fmtLiters(report.totalVolumeLiters)} />
            <InfoRow label="Сумма" value={`${fmtMoney(report.totalAmount)} ₽`} />
          </div>
        )}
      </SectionCard>

      <Button variant="outline" size="sm" onClick={() => navigate('/reconciliation')}>
        <GitCompare className="mr-2 h-4 w-4" /> Открыть сверки по станции
      </Button>
    </ScrollTab>
  )
}
