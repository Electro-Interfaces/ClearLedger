/**
 * «Требует внимания» (О-6, слой политик) — виджет-исключения на Обзоре для
 * «работы по исключениям». Консолидирует отклонения, которые директору нельзя
 * пропустить: отставание от плана (🔴🟡 из план-факта О-1), позиции ниже
 * себестоимости, дефицит, неликвиды, затоварка (из ассортимента).
 * Ключи React Query совпадают с монитором/панелью ассортимента → без доп.запросов.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ChevronRight } from 'lucide-react'
import { getStorePlanFacts, getStoreAssortment } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

type Sev = 'red' | 'amber'
interface Exc { sev: Sev; text: string; hint?: string }

const SEV: Record<Sev, { dot: string; text: string; ring: string }> = {
  red: { dot: 'bg-red-400', text: 'text-red-400/85', ring: 'border-red-400/30' },
  amber: { dot: 'bg-amber-400', text: 'text-amber-300/90', ring: 'border-amber-400/30' },
}

export function StoreExceptionsWidget({ companyId, dateFrom, dateTo, period }: {
  companyId: string; dateFrom: string; dateTo: string; period: string
}) {
  const pf = useQuery({
    queryKey: ['store-plan-facts', companyId, period],
    queryFn: () => getStorePlanFacts(period),
    enabled: !!period && period.length === 7,
  })
  const asrt = useQuery({
    queryKey: ['store-assortment', companyId, dateFrom, dateTo, 'all'],
    queryFn: () => getStoreAssortment(dateFrom, dateTo, 'all'),
  })

  const excs = useMemo<Exc[]>(() => {
    const out: Exc[] = []
    // Отклонения от плана (только если план задан)
    const cards = pf.data ? [pf.data.total, ...pf.data.by_category, ...pf.data.by_station] : []
    for (const c of cards) {
      if (!c.traffic || c.traffic === 'green' || c.pct == null) continue
      out.push({
        sev: c.traffic === 'red' ? 'red' : 'amber',
        text: `${c.label}: ${Math.round(c.pct)}% плана`,
        hint: c.delta != null ? `${c.delta >= 0 ? '+' : ''}${fmtMoney(c.delta)} к плану` : undefined,
      })
    }
    const s = asrt.data?.summary
    if (s) {
      if (s.loss_count > 0) out.push({ sev: 'red', text: `${s.loss_count} поз. ниже себестоимости`, hint: 'проверить цену' })
      if (s.oos_count > 0) out.push({ sev: 'red', text: `${s.oos_count} поз. дефицит`, hint: 'есть спрос, нет остатка' })
      if (s.dead_count > 0) out.push({ sev: 'amber', text: `${s.dead_count} неликвидов`, hint: `заморожено ${fmtMoney(s.dead_cost)}` })
      if (s.overstock_count > 0) out.push({ sev: 'amber', text: `${s.overstock_count} поз. затоварка`, hint: `${fmtMoney(s.overstock_cost)} в запасе` })
    }
    // red — вперёд
    return out.sort((a, b) => (a.sev === b.sev ? 0 : a.sev === 'red' ? -1 : 1))
  }, [pf.data, asrt.data])

  const loading = pf.isLoading || asrt.isLoading
  const redCount = excs.filter((e) => e.sev === 'red').length

  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-400/90" />
          <span className="text-sm font-medium">Требует внимания</span>
        </div>
        {excs.length > 0 && (
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {redCount > 0 && <span className="text-red-400/85 font-medium">{redCount} критично</span>}
            {redCount > 0 && excs.length > redCount && ' · '}
            {excs.length > redCount && `${excs.length - redCount} внимание`}
          </span>
        )}
      </div>

      {loading ? (
        <div className="text-xs text-muted-foreground">Проверка исключений…</div>
      ) : excs.length === 0 ? (
        <div className="flex items-center gap-2 text-xs text-emerald-300/80 py-1">
          <CheckCircle2 className="h-4 w-4" /> Исключений нет — показатели в норме.
        </div>
      ) : (
        <ul className="space-y-1">
          {excs.map((e, i) => {
            const c = SEV[e.sev]
            return (
              <li key={i} className={`flex items-center gap-2 text-xs rounded-md border ${c.ring} bg-background/40 px-2.5 py-1.5`}>
                <span className={`inline-block w-2 h-2 rounded-full ${c.dot} shrink-0`} />
                <span className={`font-medium ${c.text}`}>{e.text}</span>
                {e.hint && (
                  <span className="text-muted-foreground/70 inline-flex items-center gap-0.5">
                    <ChevronRight className="h-3 w-3" /> {e.hint}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
