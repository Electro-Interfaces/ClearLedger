/**
 * «Смены» — смена как составной документ (архитектура МАГа): организующая
 * единица, на которую роллапятся продажи (сопутка/общепит), возвраты, приходы,
 * инвентаризации, списания того же дня. Приходы/инвентаризации в ЦБ не несут
 * GUID смены → связка по (станция, дата).
 * Данные: /api/store/shifts (GoodsDashboardService.shifts_composite).
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreShifts, type ShiftComposite } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { ExportButton } from './analytics/ExportButton'
import { ShiftDetailModal } from './ShiftDetailModal'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

export function StoreShiftsPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-shifts', companyId, dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка смен…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки смен</div>
  if (!data) return null

  const s = data.summary
  const KPIS = [
    { label: 'Смен', value: nf(s.count), hint: `${data.period.from} – ${data.period.to}` },
    { label: 'Выручка', value: money(s.revenue) },
    { label: 'Возвраты', value: money(s.returns), cls: s.returns > 0 ? 'text-amber-300/90' : '' },
    { label: 'Приходы (нетто)', value: money(s.receipts_amount), hint: 'ПТУ за период' },
    { label: 'Инвент. док', value: nf(s.inventory_docs) },
    { label: 'Списания', value: money(s.writeoff_amount), cls: s.writeoff_amount > 0 ? 'text-red-400/80' : '' },
  ]

  return (
    <div ref={ref} className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Смены — составной документ</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Смена как организующая единица: продажи + возвраты + приходы + инвентаризации + списания за смену.
            Приходы/инвентаризации связаны по дате и станции (в ЦБ отдельные документы).
          </p>
        </div>
        <ExportButton title="Смены магазина" subtitle={`${data.period.from} — ${data.period.to}`} getEl={() => ref.current} />
      </div>

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Дата</th>
              <th className="px-3 py-2 font-medium text-left">АЗС</th>
              <th className="px-3 py-2 font-medium text-left">№ смены</th>
              <th className="px-3 py-2 font-medium text-right">Выручка</th>
              <th className="px-3 py-2 font-medium text-right">Сопутка</th>
              <th className="px-3 py-2 font-medium text-right">Общепит</th>
              <th className="px-3 py-2 font-medium text-right">Позиций</th>
              <th className="px-3 py-2 font-medium text-right">Возвраты</th>
              <th className="px-3 py-2 font-medium text-right">Приходы</th>
              <th className="px-3 py-2 font-medium text-center">Инв.</th>
              <th className="px-3 py-2 font-medium text-right">Списания</th>
            </tr>
          </thead>
          <tbody>
            {data.shifts.map((sh: ShiftComposite) => (
              <tr key={sh.shift_key} onClick={() => setOpenKey(sh.shift_key)}
                className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                <td className="px-3 py-1.5 whitespace-nowrap">{sh.date}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{sh.station}</td>
                <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{sh.number ?? '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums font-medium">{money(sh.revenue)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{money(sh.soputka)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{money(sh.obshepit)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{nf(sh.positions)}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${sh.returns > 0 ? 'text-amber-300/90' : 'text-muted-foreground/50'}`}>{money(sh.returns)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {sh.receipts_amount > 0
                    ? <span title={`${sh.receipts_count} документ(ов)`}>{money(sh.receipts_amount)}</span>
                    : <span className="text-muted-foreground/50">—</span>}
                </td>
                <td className="px-3 py-1.5 text-center tabular-nums">
                  {sh.inventory_count > 0 ? <span className="text-blue-300/80" title={`отклонение ${fmtMoney(sh.inventory_net)}`}>{sh.inventory_count}</span> : <span className="text-muted-foreground/50">—</span>}
                </td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${sh.writeoff_amount > 0 ? 'text-red-400/80' : 'text-muted-foreground/50'}`}>
                  {sh.writeoff_amount > 0 ? <span title={`${sh.writeoff_count} документ(ов)`}>{money(sh.writeoff_amount)}</span> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.shifts.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет смен за период (поставьте апрель).</div>}
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Клик по смене — детализация (строки продаж, касса, приходы/инвентаризации/списания дня).
        Приходы/инвентаризации/списания показаны за дату смены (в ЦБ — отдельные документы, GUID смены не несут).
      </p>

      {openKey && <ShiftDetailModal shiftKey={openKey} companyId={companyId} onClose={() => setOpenKey(null)} />}
    </div>
  )
}
