/**
 * «Партнёры и интеграции» (docs/MARKET-ROADMAP.md §9, этап 6).
 *
 * Роуминг имеет смысл там, где сеть нас ДОПОЛНЯЕТ: её точки стоят в городах, куда
 * наш клиент сегодня не доезжает. Сеть, стоящая ровно там же, где мы, подключением
 * ничего не добавляет — она просто поделит с нами тот же спрос. Поэтому главная
 * колонка здесь не «сколько у него точек», а «сколько из них в городах без нас».
 *
 * Отношение к компании — решение человека, а не свойство данных: одна и та же сеть
 * бывает конкурентом в одном регионе и кандидатом на роуминг в другом.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Handshake } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketPartners, patchMarketOperator } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const RELATIONS: Record<string, string> = {
  competitor: 'конкурент',
  candidate: 'кандидат на интеграцию',
  partner: 'партнёр',
  integrated: 'интегрирован',
  other: 'прочие',
}

export function MarketPartnersPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [saving, setSaving] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['market-partners', companyId],
    queryFn: () => getMarketPartners(companyId),
    enabled: !!companyId,
  })
  const setRelation = useMutation({
    mutationFn: ({ id, relation }: { id: string; relation: string }) =>
      patchMarketOperator(companyId, id, { relation }),
    onMutate: ({ id }) => setSaving(id),
    onSettled: () => {
      setSaving(null)
      qc.invalidateQueries({ queryKey: ['market-partners', companyId] })
      qc.invalidateQueries({ queryKey: ['market-operators', companyId] })
    },
  })

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем покрытие сетей</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const rows = q.data?.partners ?? []
  const best = rows[0]

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Handshake className="size-4 text-primary" aria-hidden />
            {!best
              ? 'Сетей с точками рядом пока не наблюдали — обсуждать роуминг не с кем.'
              : `Больше всех дополняет нашу сеть ${best.name}: ${nf.format(best.complementSites)} точек в городах, где нас нет.`}
          </span>
          <span className="text-xs text-muted-foreground">
            мы стоим в {nf.format(q.data?.ourCities ?? 0)} городах
          </span>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Сеть</th>
              <th className="p-2 text-right font-medium">Точек</th>
              <th className="p-2 text-right font-medium">Живых</th>
              <th className="p-2 text-right font-medium">Дополняет</th>
              <th className="p-2 text-right font-medium">Дублирует</th>
              <th className="p-2 text-left font-medium">Города без нас</th>
              <th className="p-2 text-left font-medium">Отношение</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-border/60">
                <td className="p-2 font-medium">{r.name}</td>
                <td className="p-2 text-right tabular-nums">{nf.format(r.sites)}</td>
                <td className="p-2 text-right tabular-nums">{nf.format(r.alive)}</td>
                <td className="p-2 text-right">
                  <span className={`tabular-nums ${r.complementPct != null && r.complementPct >= 50 ? 'text-success' : ''}`}>
                    {nf.format(r.complementSites)}
                    {r.complementPct != null && (
                      <span className="ml-1 font-normal text-muted-foreground">
                        {nf1.format(r.complementPct)} %
                      </span>
                    )}
                  </span>
                </td>
                <td className="p-2 text-right tabular-nums">{nf.format(r.overlapSites)}</td>
                <td className="p-2 text-muted-foreground">
                  {r.newCities.length === 0 ? 'нет' : r.newCities.slice(0, 4).join(', ')}
                  {r.newCitiesTotal > 4 && ` и ещё ${r.newCitiesTotal - 4}`}
                </td>
                <td className="p-2">
                  <Select value={r.relation}
                    onValueChange={(relation) => setRelation.mutate({ id: r.id, relation })}>
                    <SelectTrigger className="h-7 w-[190px] text-xs"
                      disabled={saving === r.id}><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(RELATIONS).map(([k, label]) => (
                        <SelectItem key={k} value={k}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{q.data?.note}</p>
    </div>
  )
}
