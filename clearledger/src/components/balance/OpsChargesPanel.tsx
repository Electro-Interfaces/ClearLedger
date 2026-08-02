/**
 * «Затраты объектов» — матрица объект × месяц × статья.
 *
 * Отвечает на вопрос «что и как мы собрали по всем разрезам» за квартал и год.
 * Квартал и год своего закрытия не имеют: это свёртка закрытых месяцев, поэтому
 * итоги считаются на чтении.
 *
 * Под итогом месяца стоит доля подтверждённого документами. Месяц, где половина
 * строк закрыта расчётом, и месяц, где всё подтверждено, — цифры разной
 * достоверности, и в отчёте они обязаны различаться.
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Loader2 } from 'lucide-react'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { getOpsCharges, type OpsChargesMatrix } from '@/services/opsService'
import { formatBucket } from '@/lib/formatDate'

const money = (v: number | null | undefined) =>
  !v ? '—' : fmtN(Math.round(v))


/** Доля строк месяца, закрытых документом. Ниже 100% — цифра частично расчётная. */
function confirmedPct(byBasis: Record<string, number> | undefined): number | null {
  if (!byBasis) return null
  const total = Object.values(byBasis).reduce((a, b) => a + b, 0)
  if (!total) return null
  return Math.round(((byBasis.document ?? 0) / total) * 100)
}

export function OpsChargesPanel() {
  const { companyId } = useCompany()
  const [scope, setScope] = useState<'location' | 'company' | 'all'>('location')
  const [months, setMonths] = useState(12)
  const tableRef = useRef<HTMLDivElement>(null)

  const q = useQuery({
    queryKey: ['ops-charges', companyId, scope, months],
    queryFn: () => {
      const d = new Date()
      d.setDate(1)
      d.setMonth(d.getMonth() - 1)
      const to = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
      d.setMonth(d.getMonth() - (months - 1))
      const from = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
      return getOpsCharges(companyId!, from, to, scope)
    },
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return <div className="flex justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.isError) {
    return <div className="p-6 text-sm text-red-600 dark:text-red-400">
      Не удалось загрузить затраты. Обновите страницу.
    </div>
  }

  const d = q.data as OpsChargesMatrix
  const grand = d.rows.reduce((a, r) => a + r.total, 0)

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border border-border bg-muted/60 p-0.5">
          {([['location', 'По объектам'], ['company', 'Общие затраты'],
             ['all', 'Всё вместе']] as const).map(([v, label]) => (
            <button key={v} type="button" onClick={() => setScope(v)}
              className={`rounded-[5px] px-3 py-1.5 text-sm transition-colors ${
                scope === v ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>
          ))}
        </div>
        <select value={months} onChange={(e) => setMonths(Number(e.target.value))}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm">
          <option value={3}>Квартал</option>
          <option value={6}>Полгода</option>
          <option value={12}>Год</option>
        </select>
        <div className="ml-auto">
          <ExportButton title="Затраты объектов"
            subtitle={`${formatBucket(d.from)} — ${formatBucket(d.to)}`}
            getEl={() => tableRef.current} />
        </div>
      </div>

      {d.rows.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          За выбранный период начислений нет. Разверните ожидания на экране
          «Закрытие месяца» — там же видно, каким договорам не хватает условий.
        </CardContent></Card>
      ) : (
        <Card><CardContent ref={tableRef} className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-card">Объект</TableHead>
                {d.periods.map((p) => (
                  <TableHead key={p} className="whitespace-nowrap text-right">
                    {formatBucket(p)}
                  </TableHead>
                ))}
                <TableHead className="text-right">Итого</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.rows.map((r) => (
                <TableRow key={r.locationId ?? 'company'}>
                  <TableCell className="sticky left-0 max-w-[240px] truncate bg-card font-medium"
                    title={r.locationName}>{r.locationName}</TableCell>
                  {d.periods.map((p) => {
                    const sum = Object.values(r.byPeriod[p] ?? {}).reduce((a, b) => a + b, 0)
                    const detail = Object.entries(r.byPeriod[p] ?? {})
                      .filter(([, v]) => v)
                      .map(([c, v]) => {
                        const label = d.costItems.find((i) => i.code === c)?.label ?? c
                        return `${label}: ${money(v)} ₽`
                      }).join('\n')
                    return (
                      <TableCell key={p} className="text-right tabular-nums"
                        title={detail || undefined}>{money(sum)}</TableCell>
                    )
                  })}
                  <TableCell className="text-right font-medium tabular-nums">
                    {money(r.total)}
                  </TableCell>
                </TableRow>
              ))}
              <TableRow className="bg-muted/40">
                <TableCell className="sticky left-0 bg-muted/40 font-semibold">Всего</TableCell>
                {d.periods.map((p) => {
                  const pct = confirmedPct(d.byBasis[p])
                  return (
                    <TableCell key={p} className="text-right font-semibold tabular-nums">
                      {money(d.totalsByPeriod[p])}
                      {pct !== null && (
                        <div className={`text-[10px] font-normal ${
                          pct >= 90 ? 'text-emerald-600 dark:text-emerald-400'
                            : pct >= 50 ? 'text-amber-600 dark:text-amber-400'
                            : 'text-red-600 dark:text-red-400'}`}
                          title="Доля суммы, подтверждённой документами контрагентов">
                          док {pct}%
                        </div>
                      )}
                    </TableCell>
                  )
                })}
                <TableCell className="text-right font-semibold tabular-nums">
                  {money(grand)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent></Card>
      )}

      <p className="text-xs text-muted-foreground">
        В ячейке — сумма всех статей за месяц; наведите курсор, чтобы увидеть разбивку.
        Подпись «док» под итогом месяца показывает, какая доля закрыта документами
        контрагентов, а не расчётом.
      </p>
    </div>
  )
}
