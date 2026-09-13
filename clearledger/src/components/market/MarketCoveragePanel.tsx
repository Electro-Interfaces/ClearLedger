/**
 * «Обеспеченность» — сколько электромобилей приходится на РАБОТАЮЩУЮ зарядку.
 *
 * Два разных дефицита, которые обычно смешивают в один. Где станций мало — надо
 * строить. Где станции есть, но стоят мёртвыми — строить бессмысленно, надо чинить
 * или договариваться с тем, чьи они. Разрыв между «есть» и «работает» и есть главный
 * ответ этого экрана.
 *
 * Парк считается по электромобилям без гибридов: их вдвое больше, но региональной
 * разбивки по ним в открытом доступе нет, и подмешать их значило бы завысить спрос.
 */
import { useQuery } from '@tanstack/react-query'
import { BatteryCharging } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketCoverage, type MarketCoverageRow } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function Num({ v, digits = 0 }: { v: number | null | undefined; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">{digits ? nf1.format(v) : nf.format(v)}</span>
}

/** Нагрузка словами: цифра сама по себе не говорит, много это или мало. */
function Load({ row }: { row: MarketCoverageRow }) {
  const v = row.carsPerAlive
  if (v == null) return <span className="text-muted-foreground">—</span>
  const tone = v >= 40 ? 'text-warning' : v <= 15 ? 'text-success' : ''
  return (
    <span className={`tabular-nums ${tone}`}>
      {nf1.format(v)}
      <span className="ml-1 font-normal text-muted-foreground">
        {v >= 40 ? 'тесно' : v <= 15 ? 'свободно' : 'терпимо'}
      </span>
    </span>
  )
}

export function MarketCoveragePanel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-coverage', companyId],
    queryFn: () => getMarketCoverage(companyId),
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем обеспеченность регионов</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const rows = q.data?.regions ?? []
  if (rows.length === 0) {
    return (
      <Card className="m-4"><CardContent className="p-6 text-sm text-muted-foreground">
        {q.data?.message ?? 'Данных о парке электромобилей нет.'}
      </CardContent></Card>
    )
  }

  const worst = rows[0]
  const dead = rows.filter((r) => (r.deadGapRatio ?? 1) >= 2)
  const ourRegions = rows.filter((r) => r.ourSites > 0)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <BatteryCharging className="size-4 text-primary" aria-hidden />
            Тяжелее всего в регионе «{worst.region}»: {nf1.format(worst.carsPerAlive ?? 0)} машин
            на работающую зарядку.
          </span>
          <span className="text-xs text-muted-foreground">
            в {dead.length} регионах нагрузка вдвое выше, чем кажется по числу станций
          </span>
          <span className="text-xs text-muted-foreground">
            мы стоим в {ourRegions.length} из {rows.length}
          </span>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Регион</th>
              <th className="p-2 text-right font-medium">Электромобилей</th>
              <th className="p-2 text-right font-medium">Доля парка</th>
              <th className="p-2 text-right font-medium">Зарядок</th>
              <th className="p-2 text-right font-medium">Из них работают</th>
              <th className="p-2 text-right font-medium">Машин на зарядку</th>
              <th className="p-2 text-right font-medium">На работающую</th>
              <th className="p-2 text-right font-medium">Разрыв</th>
              <th className="p-2 text-right font-medium">Наших точек</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.region} className={r.ourSites > 0
                ? 'border-t border-border bg-primary/5' : 'border-t border-border/50'}>
                <td className="p-2 font-medium">{r.region}</td>
                <td className="p-2 text-right"><Num v={r.evCars} /></td>
                <td className="p-2 text-right"><Num v={r.evSharePct} digits={1} /></td>
                <td className="p-2 text-right"><Num v={r.stations} /></td>
                <td className="p-2 text-right">
                  <Num v={r.stationsAlive} />
                  {r.deadStations ? (
                    <span className="ml-1 text-muted-foreground">
                      мёртвых {nf.format(r.deadStations)}
                    </span>
                  ) : null}
                </td>
                <td className="p-2 text-right"><Num v={r.carsPerStation} digits={1} /></td>
                <td className="p-2 text-right"><Load row={r} /></td>
                <td className="p-2 text-right">
                  {r.deadGapRatio == null ? <span className="text-muted-foreground">—</span> : (
                    <span className={`tabular-nums ${r.deadGapRatio >= 2 ? 'text-warning' : ''}`}>
                      ×{nf1.format(r.deadGapRatio)}
                    </span>
                  )}
                </td>
                <td className="p-2 text-right">
                  <Num v={r.ourSites} />
                  {r.ourSites > 0 && (
                    <span className="ml-1 text-muted-foreground">
                      работают {nf.format(r.ourWorking)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Card>
        <CardContent className="space-y-1 p-3 text-xs text-muted-foreground">
          <p>
            <b className="text-foreground">Разрыв</b> — во сколько раз нагрузка на
            работающую зарядку выше, чем кажется по числу станций. Он и отличает две
            разные истории: «станций мало, надо строить» от «станции есть, но стоят».
            Во втором случае стройка не поможет, а вот роуминг или франшиза с тем, чьи
            это станции, — вполне.
          </p>
          <p>{q.data?.note}</p>
          <p>
            Источник парка: {rows[0].source ?? 'не указан'}
            {rows[0].asOf ? `, данные на ${rows[0].asOf}` : ''}. Обновляется вручную
            несколько раз в год — число зарядок меняется быстрее.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
