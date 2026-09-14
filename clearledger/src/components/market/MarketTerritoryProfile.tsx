/**
 * Профиль территории: всё, что мы знаем о СВОЕЙ сети здесь, рядом с рынком.
 *
 * Решение МАГа 13.09.2026: наша сторона в «Маркетинге» не может быть беднее
 * рыночной. Рынок отвечает на «кто вокруг», мы — на «почему у нас так»: оснащение,
 * загрузка портов, состав клиентов, чем и когда заряжают, чем кончаются сессии,
 * динамика к прошлому периоду. Это и объясняет, что делать с территорией.
 */
import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useCompany } from '@/contexts/CompanyContext'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { getTerritoryProfile } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function money(v: number | null | undefined): string {
  if (v == null) return 'нет данных'
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

function Num({ v, unit, digits = 0 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">
    {digits ? nf1.format(v) : nf.format(v)}{unit ? ` ${unit}` : ''}
  </span>
}

/** Показатель с подписью — плотно, потому что их много и все нужны рядом. */
function Stat({ label, children, hint }: {
  label: string; children: React.ReactNode; hint?: string
}) {
  // `data-kpi` — метка для выгрузки: показатель, значение и подпись уезжают в
  // книгу листом «KPI» ровно в том порядке, в каком стоят здесь.
  return (
    <div data-kpi>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold">{children}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

/** Разбивка словами: доли важнее полос, когда категорий мало. */
function Split({ title, data, total }: {
  title: string; data: Record<string, number>; total?: number
}) {
  const все = Object.entries(data).sort((a, b) => b[1] - a[1])
  const rows = все.slice(0, 6)
  const sum = total ?? rows.reduce((acc, [, v]) => acc + v, 0)
  if (rows.length === 0) return null
  return (
    <div>
      <div className="mb-1 text-xs font-medium">{title}</div>
      {/* На экране шесть первых строк: остальное — хвост, который глазами не читают.
          В книгу уходит разбивка целиком. */}
      <table hidden {...exportRows(title, [title, 'Сколько', 'Доля, %'],
        все.map(([k, v]) => [k, v, sum > 0 ? (v / sum) * 100 : null]))} />
      <ul className="space-y-0.5">
        {rows.map(([k, v]) => (
          <li key={k} className="flex items-baseline justify-between gap-2 text-xs">
            <span className="min-w-0 truncate text-muted-foreground">{k}</span>
            <span className="shrink-0 tabular-nums">
              {nf.format(v)}
              {sum > 0 && <span className="ml-1 text-muted-foreground">
                {nf1.format((v / sum) * 100)} %
              </span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function MarketTerritoryProfile({ name, level, onBack }: {
  name: string; level: 'city' | 'region'; onBack: () => void
}) {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['market-territory-profile', companyId, name, level],
    queryFn: () => getTerritoryProfile(companyId, { name, level, days: 90 }),
    enabled: !!companyId && !!name,
  })

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Собираем профиль территории</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const o = q.data?.ours
  const m = q.data?.market
  const peak = o?.hours?.length
    ? o.hours.reduce((a, b) => (b.sessions > a.sessions ? b : a))
    : null
  const working = o ? (o.byStatus['working'] ?? 0) : 0
  const trend = o?.trend

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-4">
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={onBack}
          className="flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" aria-hidden /> ко всем территориям
        </button>
        {o && (
          <span data-export-ignore>
            <ExportButton title={`Территория · ${name}`}
              subtitle={`наша сеть и рынок, ${q.data?.days} дней`} getEl={() => экран.current} />
          </span>
        )}
      </div>

      {!o ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground">
          {q.data?.message ?? 'В этой территории наших объектов нет.'}
        </CardContent></Card>
      ) : (
        <>
          <Card>
            <CardContent className="space-y-3 p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-headline text-base font-semibold">{name}</span>
                <span className="text-xs text-muted-foreground">
                  наша сеть и рынок, {q.data?.days} дней
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                <Stat label="наших объектов"
                  hint={working ? `работают ${nf.format(working)}` : undefined}>
                  <Num v={o.objects} />
                </Stat>
                <Stat label="портов" hint={o.powerKwtTotal
                  ? `${nf.format(o.powerKwtTotal)} кВт всего` : undefined}>
                  <Num v={o.ports} />
                </Stat>
                <Stat label="сессий"
                  hint={trend?.sessionsPct != null
                    ? `${trend.sessionsPct > 0 ? '+' : ''}${nf1.format(trend.sessionsPct)} % к прошлым` : undefined}>
                  <Num v={o.sessions} />
                </Stat>
                <Stat label="выручка"
                  hint={trend?.revenuePct != null
                    ? `${trend.revenuePct > 0 ? '+' : ''}${nf1.format(trend.revenuePct)} % к прошлым` : undefined}>
                  {money(o.revenue)}
                </Stat>
                <Stat label="наша ₽/кВт·ч"
                  hint={m?.marketPricePerKwh != null
                    ? `рынок ${nf1.format(m.marketPricePerKwh)}` : 'рынок не наблюдали'}>
                  <Num v={o.pricePerKwh} digits={1} />
                </Stat>
                <Stat label="наша доля"
                  hint={m ? `чужих сетей ${nf.format(m.rivalSites)}` : undefined}>
                  <Num v={m?.sharePct} unit="%" digits={1} />
                </Stat>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                <Stat label="загрузка порта" hint="сессий в сутки">
                  <Num v={o.sessionsPerPortDay} digits={1} />
                </Stat>
                <Stat label="отпуск на порт" hint="кВт·ч в сутки">
                  <Num v={o.kwhPerPortDay} digits={1} />
                </Stat>
                <Stat label="клиентов">
                  <Num v={o.clients} />
                </Stat>
                <Stat label="средний чек">
                  {money(o.avgCheck)}
                </Stat>
                <Stat label="средняя зарядка" hint="минут">
                  <Num v={o.avgDurationMin} digits={1} />
                </Stat>
                <Stat label="час пик" hint={peak ? `${nf.format(peak.sessions)} сессий` : undefined}>
                  {peak ? `${peak.hour}:00` : <span className="text-muted-foreground">нет данных</span>}
                </Stat>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <Card><CardContent className="space-y-3 p-4">
              <Split title="Состояние объектов" data={o.byStatus} total={o.objects} />
              <Split title="Класс скорости" data={o.bySpeed} total={o.objects} />
            </CardContent></Card>
            <Card><CardContent className="space-y-3 p-4">
              <Split title="Производители" data={o.byBrand} total={o.objects} />
              <Split title="Коннекторы объектов" data={o.connectorTypes} />
            </CardContent></Card>
            <Card><CardContent className="space-y-3 p-4">
              <Split title="Кто заряжается"
                data={Object.fromEntries(Object.entries(o.byUserType)
                  .map(([k, v]) => [k, v.sessions]))} total={o.sessions} />
              <Split title="Чем заряжают" data={o.byConnector} total={o.sessions} />
            </CardContent></Card>
          </div>

          <Card><CardContent className="space-y-2 p-4">
            <Split title="Чем кончаются сессии" data={o.byResult} total={o.sessions} />
            <p className="text-xs text-muted-foreground">
              Доля сессий, завершившихся ошибкой, — это и есть та надёжность, которую
              видит клиент. Она объясняет отток лучше, чем любая кривая спроса.
            </p>
          </CardContent></Card>

          <Card><CardContent className="p-4">
            <div className="mb-2 font-headline text-sm font-semibold">
              Наши объекты здесь
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs"
                {...exportRows('Наши объекты', [
                  'Объект', 'Город', 'кВт', 'Портов', 'Производитель', 'Состояние',
                  'Сессий', 'Выручка, ₽',
                ], o.objectsList.map((r) => [
                  r.name, r.city, r.powerKwt, r.ports, r.brand, r.status, r.sessions, r.revenue,
                ]))}>
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-1 text-left font-medium">Объект</th>
                    <th className="py-1 text-left font-medium">Город</th>
                    <th className="py-1 text-right font-medium">кВт</th>
                    <th className="py-1 text-right font-medium">Портов</th>
                    <th className="py-1 text-left font-medium">Производитель</th>
                    <th className="py-1 text-left font-medium">Состояние</th>
                    <th className="py-1 text-right font-medium">Сессий</th>
                    <th className="py-1 text-right font-medium">Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {o.objectsList.map((r) => (
                    <tr key={r.locationId} className="border-t border-border/40">
                      <td className="py-1">{r.name}</td>
                      <td className="py-1 text-muted-foreground">{r.city ?? '—'}</td>
                      <td className="py-1 text-right"><Num v={r.powerKwt} digits={1} /></td>
                      <td className="py-1 text-right"><Num v={r.ports} /></td>
                      <td className="py-1 text-muted-foreground">{r.brand ?? '—'}</td>
                      <td className="py-1 text-muted-foreground">{r.status ?? '—'}</td>
                      <td className="py-1 text-right"><Num v={r.sessions} /></td>
                      <td className="py-1 text-right tabular-nums">{money(r.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent></Card>
        </>
      )}
    </div>
  )
}
