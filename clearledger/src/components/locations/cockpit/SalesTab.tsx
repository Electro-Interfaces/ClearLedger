/**
 * Реализация станции — продажи в разрезе конкретной точки.
 * АЗС: P&L + структура оплат + последняя смена (STS, реально). EV: задел кВт·ч.
 * Прочие типы — каркас/заглушка.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Wallet, Fuel, Banknote, CreditCard, Ticket, GitCompare, ChevronLeft, ChevronRight, Zap, Box,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { locationStationNumber } from '@/components/reconciliation/locationMapping'
import { useStationPnL, useStationPaymentMix, useStationLastShift } from '@/hooks/useStationData'
import { fmtMoney, fmtMoneyShort, fmtLiters, fmtPct } from '@/services/analyticsService'
import type { ServiceLocation } from '@/types/location'
import { SectionCard, InfoRow, Placeholder, WipBadge, ScrollTab, typeFlags } from './shared'

function monthBounds(year: number, month: number) {
  const first = new Date(year, month - 1, 1)
  const last = new Date(year, month, 0)
  return { from: first.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10) }
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  )
}

export function SalesTab({ location }: { location: ServiceLocation }) {
  const flags = typeFlags(location.type)

  if (flags.isEv) {
    return (
      <ScrollTab>
        <SectionCard title="Реализация энергии (кВт·ч)" icon={Zap} muted action={<WipBadge>EV-пайплайн</WipBadge>}>
          <InfoRow label="Сессий зарядки" value="—" />
          <InfoRow label="Отпущено кВт·ч" value="—" />
          <InfoRow label="Выручка" value="—" />
        </SectionCard>
        <p className="text-xs text-muted-foreground/70">
          Учёт зарядных сессий (кВт·ч → платежи) — будущая фаза EV-пайплайна.
        </p>
      </ScrollTab>
    )
  }

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
