/**
 * «Бюджет портфеля» — куда уходят деньги проектов и что с ними будет дальше.
 *
 * Две вещи, которых не хватало отчёту «сумма плана и факта»:
 *   • капвложения отделены от расходов периода — у них разная судьба. Первые
 *     войдут в стоимость объекта (счёт 08 → 01), вторые списаны сразу;
 *   • деньги разложены по состоянию проекта: в работе, приостановлены (по
 *     ФСБУ 26/2020 остаются на счёте 08) и отменены (подлежат списанию,
 *     Дт 91.02 Кт 08 в периоде решения).
 *
 * Отклонение показываем рядом с планом, а не отдельной витриной: цифра без
 * плана ничего не значит, а процент без плана вообще не считается.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2 } from 'lucide-react'
import { ExportButton } from './ExportButton'
import { getCostsReport } from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const money = (v: number) => `${nf0.format(Math.round(v))} ₽`

export function ProjectBudgetPanel({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['pr-costs-report', companyId],
    queryFn: () => getCostsReport(companyId),
  })
  if (q.isLoading || !q.data) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const d = q.data
  const empty = d.items.length === 0

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Бюджет</h2>
          <p className="text-sm text-muted-foreground">
            План {money(d.planTotal)} · факт {money(d.factTotal)}. Капвложения войдут в стоимость
            объектов, расходы периода — нет.
          </p>
        </div>
        <ExportButton companyId={companyId} report="budget" fileName="budget.xlsx" />
      </div>

      {empty ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Бюджет ещё не заводили. Статьи добавляются в карточке проекта, вкладка «Учёт»:
            план и факт по каждой — техприсоединение, оборудование, СМР, проектирование.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Card>
              <CardContent className="p-3">
                <div className="text-sm font-semibold mb-1">Капвложения (счёт 08 → стоимость объекта)</div>
                <div className="text-sm text-muted-foreground">
                  план <span className="font-mono text-foreground">{money(d.capital.plan)}</span> ·
                  {' '}факт <span className="font-mono text-foreground">{money(d.capital.fact)}</span>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-3">
                <div className="text-sm font-semibold mb-1">Расходы периода</div>
                <div className="text-sm text-muted-foreground">
                  план <span className="font-mono text-foreground">{money(d.expense.plan)}</span> ·
                  {' '}факт <span className="font-mono text-foreground">{money(d.expense.fact)}</span>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40">По статьям</div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th className="text-left px-3 py-1.5 font-medium">Статья</th>
                    <th className="text-left px-3 py-1.5 font-medium">Судьба</th>
                    <th className="text-right px-3 py-1.5 font-medium">Проектов</th>
                    <th className="text-right px-3 py-1.5 font-medium">План</th>
                    <th className="text-right px-3 py-1.5 font-medium">Факт</th>
                    <th className="text-right px-3 py-1.5 font-medium">Отклонение</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((i) => (
                    <tr key={i.kind} className="border-b border-border/30">
                      <td className="px-3 py-1.5">{i.label}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {i.capital ? 'капвложение' : 'расход периода'}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">{i.sites}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{money(i.plan)}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{money(i.fact)}</td>
                      <td className={`px-3 py-1.5 text-right font-mono ${i.variance > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {i.variance > 0 ? '+' : ''}{money(i.variance)}
                        {i.variancePct != null && <span className="text-xs"> ({i.variancePct}%)</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40">
                Состояние проектов — что будет с деньгами
              </div>
              <div className="p-3 space-y-1.5">
                {d.buckets.map((b) => (
                  <div key={b.key} className="flex items-center justify-between text-sm">
                    <span className={b.key === 'closed' && b.fact > 0 ? 'text-amber-700 dark:text-amber-400' : ''}>
                      {b.label}
                    </span>
                    <span className="font-mono text-muted-foreground">
                      план {money(b.plan)} · факт {money(b.fact)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
