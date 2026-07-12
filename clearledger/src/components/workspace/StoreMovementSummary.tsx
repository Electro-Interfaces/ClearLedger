/**
 * «Движение и потери» на Обзоре — учёт документов движения в разделе Магазин:
 * приходы, списания (потери), инвентаризация (недостачи/излишки), перемещения
 * (внутренние), переоценки. Свод по сменам за период (shifts_composite).
 * Данные: /api/store/shifts.
 */
import { useQuery } from '@tanstack/react-query'
import { PackagePlus, Trash2, ClipboardList, ArrowLeftRight, Tag, TrendingDown } from 'lucide-react'
import { getStoreShifts } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)

export function StoreMovementSummary({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data } = useQuery({
    queryKey: ['store-shifts', companyId, dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })
  if (!data) return null
  const s = data.summary
  const shortage = Math.min(0, s.inventory_net || 0)   // недостача (< 0) из инвентаризаций
  const losses = (s.writeoff_amount || 0) + Math.abs(shortage)   // потери = списания + недостачи

  const cells = [
    { icon: PackagePlus, label: 'Приходы (нетто)', value: fmtMoney(s.receipts_amount), cls: 'text-primary' },
    { icon: Trash2, label: 'Списания', value: fmtMoney(s.writeoff_amount), cls: s.writeoff_amount > 0 ? 'text-red-400/80' : 'text-muted-foreground' },
    { icon: ClipboardList, label: s.inventory_net < 0 ? 'Недостача (инв.)' : 'Излишки (инв.)', value: fmtMoney(Math.abs(s.inventory_net || 0)), cls: s.inventory_net < 0 ? 'text-red-400/80' : 'text-emerald-300/80', hint: `${nf(s.inventory_docs)} док.` },
    { icon: ArrowLeftRight, label: 'Перемещения', value: `${nf(s.transfer_docs)} док.`, cls: 'text-muted-foreground', hint: 'внутренние склад↔зал' },
    { icon: Tag, label: 'Переоценки', value: `${nf(s.reval_docs)} док.`, cls: 'text-muted-foreground' },
    { icon: TrendingDown, label: 'Потери всего', value: fmtMoney(losses), cls: losses > 0 ? 'text-red-400/90' : 'text-emerald-300/80', hint: 'списания + недостачи' },
  ]

  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-sm font-medium mb-2.5">Движение и потери за период</div>
      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {cells.map((c) => (
          <div key={c.label} className="rounded-md border border-border/40 bg-background/40 p-2.5">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground"><c.icon className="h-3 w-3" /> {c.label}</div>
            <div className={`text-base font-semibold tabular-nums mt-0.5 ${c.cls}`}>{c.value}</div>
            {c.hint && <div className="text-[10px] text-muted-foreground/60 mt-0.5">{c.hint}</div>}
          </div>
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground/60 mt-2">
        Потери (списания + недостачи) уменьшают валовую прибыль магазина. Перемещения — внутреннее движение (склад↔зал), в потери не входят.
      </p>
    </div>
  )
}
