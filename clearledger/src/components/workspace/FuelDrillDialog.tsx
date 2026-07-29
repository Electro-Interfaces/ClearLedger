/**
 * Провал вглубь строки разреза и сводная выгрузка «Реализации».
 *
 * До этого строка таблицы была тупиком: видно, что АИ-95 дал 40 % выручки, а чем
 * этот АИ-95 отличается от ДТ — часами, видами оплаты, станциями — уже нет. У сети
 * ЭЗС такой провал есть с самого начала (клик по строке раскрывает её по исходу,
 * коннектору и типу клиента), здесь тот же приём на топливном грейне.
 *
 * Сужение делает сервер (`dim`/`dim_val` у /analytics/fills) — клиент только
 * показывает три встречных разреза и не считает ничего сам.
 */
import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2 } from 'lucide-react'
import { fmtMoney } from '@/services/analyticsService'
import {
  getFuelFills, getFuelSlice,
  type FuelGroupBy, type FuelNarrow,
} from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const GROUP_TITLE: Partial<Record<FuelGroupBy, string>> = {
  station: 'По станциям', fuel: 'По видам топлива', channel: 'По каналам оплаты',
  pay_type: 'По видам оплаты', segment: 'По сегментам', hour: 'По часам суток',
  weekday: 'По дням недели', shift: 'По сменам', card: 'По картам',
}

/**
 * Какие три разреза показать внутри строки.
 *
 * Правило простое: не повторять то, по чему уже сузились, и начинать с разреза,
 * который чаще всего объясняет разницу — состав топлива и способ оплаты. Час суток
 * третьим: он отвечает на «когда», когда первые два не объяснили.
 */
function drillGroups(dim: FuelGroupBy): FuelGroupBy[] {
  const all: FuelGroupBy[] = ['fuel', 'channel', 'station', 'hour']
  return all.filter((g) => g !== dim).slice(0, 3)
}

export function FuelDrillDialog({ open, onClose, companyId, dateFrom, dateTo, dim, dimVal, label, narrow }: {
  open: boolean
  onClose: () => void
  companyId: string
  dateFrom: string
  dateTo: string
  dim: FuelGroupBy
  dimVal: string
  label: string
  narrow: FuelNarrow
}) {
  const groups = useMemo(() => drillGroups(dim), [dim])
  const qs = useQueries({
    queries: groups.map((g) => ({
      queryKey: ['fuel-drill', companyId, dateFrom, dateTo, dim, dimVal, g,
        narrow.stationCodes?.join(',') ?? '', narrow.segment ?? ''],
      queryFn: () => getFuelFills({
        companyId, dateFrom, dateTo, groupBy: g, dim, dimVal, top: 12, ...narrow,
      }),
      enabled: open,
    })),
  })

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-base">{label}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-3">
          {groups.map((g, i) => {
            const q = qs[i]
            const data = q.data
            return (
              <div key={g} className="min-w-0">
                <div className="mb-1.5 text-xs font-semibold text-muted-foreground">
                  {GROUP_TITLE[g] ?? g}
                </div>
                {q.isLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  </div>
                ) : !data || data.lines.length === 0 ? (
                  <div className="py-6 text-center text-xs text-muted-foreground">Нет данных</div>
                ) : (
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="p-1.5 text-left font-medium">Значение</th>
                        <th className="p-1.5 text-right font-medium">Выручка</th>
                        <th className="p-1.5 text-right font-medium">Доля</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.lines.slice(0, 10).map((l) => (
                        <tr key={l.key} className="border-b border-border/30">
                          <td className="max-w-[130px] truncate p-1.5">{l.label}</td>
                          <td className="p-1.5 text-right font-mono">{fmtMoney(l.amount)}</td>
                          <td className="p-1.5 text-right font-mono text-muted-foreground">
                            {nf1.format(l.share_pct)}%
                          </td>
                        </tr>
                      ))}
                      <tr className="font-medium">
                        <td className="p-1.5">Итого</td>
                        <td className="p-1.5 text-right font-mono">{fmtMoney(data.totals.amount)}</td>
                        <td className="p-1.5 text-right font-mono text-muted-foreground">
                          {nf0.format(data.totals.fills)} шт.
                        </td>
                      </tr>
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </div>
        <div className="text-[11px] text-muted-foreground">
          Внутри строки действуют те же фильтры экрана: период, область учёта и сегмент.
          Итоги колонок совпадают между собой — это одна и та же выборка под разными углами.
        </div>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Сводная выгрузка: разрез × месяцы одним листом Excel.
 *
 * Экспорт видимой таблицы отдаёт то, что на экране, — один период. Управленцу же
 * нужна матрица «станции по месяцам», и собирать её вручную из двенадцати выгрузок
 * никто не будет. Данные те же (`fills/slice`), просто развёрнутые.
 */
export async function exportFuelPivot(p: {
  companyId: string; dateFrom: string; dateTo: string
  groupBy: FuelGroupBy; narrow: FuelNarrow; title: string
}): Promise<void> {
  const data = await getFuelSlice({
    companyId: p.companyId, dateFrom: p.dateFrom, dateTo: p.dateTo,
    bucket: 'month', groupBy: p.groupBy, metric: 'amount', topN: 1000, ...p.narrow,
  })
  const XLSX = await import('xlsx')
  const header = ['Разрез', ...data.intervals.map((i) => i.label), 'Итого']
  const rows = data.lines.map((l) => {
    const vals = l.values.map((v) => (v == null ? 0 : Number(v)))
    return [l.label, ...vals, vals.reduce((s, v) => s + v, 0)]
  })
  const totals = data.totals.values.map((v) => (v == null ? 0 : Number(v)))
  rows.push(['Итого', ...totals, totals.reduce((s, v) => s + v, 0)])
  const ws = XLSX.utils.aoa_to_sheet([header, ...rows])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Сводная')
  XLSX.writeFile(wb, `${p.title}_${p.dateFrom}_${p.dateTo}.xlsx`)
}
