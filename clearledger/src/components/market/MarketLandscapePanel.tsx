/**
 * «Расклад сил» — раздел «Рынок» перестаёт быть списком точек.
 *
 * Здесь два слоя, которых в открытых источниках нет: чья ИТ-платформа обслуживает
 * сеть и участвует ли сеть в роуминге. Первое говорит, с кем на самом деле идёт
 * разговор о технологии — рынок держится на нескольких платформах, и большинство
 * сетей на них клиенты. Второе отвечает на вопрос водителя «где я смогу зарядиться
 * одним приложением».
 *
 * Отсутствие роуминга — факт о технологии, а не о качестве: так и написано, «работает
 * только в своём приложении». А вот оценка приложения — прямой отзыв водителя о
 * сервисе, и её мы показываем рядом со своей.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Swords } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { useCompany } from '@/contexts/CompanyContext'
import { MarketCompaniesPanel } from './MarketCompaniesPanel'
import { getMarketLandscape, type MarketNetworkRow } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const ВИДЫ = [
  { k: 'power', label: 'Расклад сил' },
  { k: 'platforms', label: 'Платформы' },
  { k: 'roaming', label: 'Роуминг' },
  { k: 'service', label: 'Качество сервиса' },
  { k: 'legal', label: 'Реквизиты' },
] as const

function Num({ v, unit, digits = 0 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">
    {digits ? nf1.format(v) : nf.format(v)}{unit ? ` ${unit}` : ''}
  </span>
}

/** Строка нашей сети подсвечена: сравнение с рынком идёт от неё. */
function rowClass(r: MarketNetworkRow): string {
  return r.isOurs ? 'border-t border-border bg-primary/5 font-medium' : 'border-t border-border/50'
}

export function MarketLandscapePanel() {
  const { companyId } = useCompany()
  const [вид, setВид] = useState<string>('power')
  // Расклад отвечает «кто сильнее», карточка — «что он делает». Второй вопрос
  // возникает сразу после первого, поэтому строка сети ведёт в карточку, а не
  // заставляет искать компанию в другом разделе.
  const [карточка, setКарточка] = useState<string | null>(null)
  const [q, setQ] = useState('')

  const data = useQuery({
    queryKey: ['market-landscape', companyId],
    queryFn: () => getMarketLandscape(companyId),
    enabled: !!companyId,
  })

  if (data.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем расклад сил</span>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const t = data.data?.totals
  const all = data.data?.networks ?? []
  const rows = all.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()))
  const ours = all.find((r) => r.isOurs)
  const platforms = data.data?.platforms ?? []

  if (карточка) {
    return <MarketCompaniesPanel initialOpen={карточка} onBack={() => setКарточка(null)} />
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Swords className="size-4 text-primary" aria-hidden />
            {ours
              ? `Мы ${ours.sharePct} % рынка: ${nf.format(ours.sites)} точек в ${nf.format(ours.citiesCount ?? 0)} городах.`
              : `На рынке ${t?.networks ?? 0} сетей.`}
          </span>
          <span className="text-xs text-muted-foreground">
            {nf.format(t?.networks ?? 0)} сетей · {nf.format(t?.networkSites ?? 0)} точек ·
            своя платформа у {t?.ownPlatform ?? 0} · в роуминге {t?.roamingNetworks ?? 0}
          </span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Сеть"
            className="h-8 w-[180px] text-xs" />
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'power' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Сеть</th>
                <th className="p-2 text-right font-medium">Точек</th>
                <th className="p-2 text-right font-medium">Доля</th>
                <th className="p-2 text-right font-medium">Городов</th>
                <th className="p-2 text-right font-medium">Округов</th>
                <th className="p-2 text-left font-medium">Модель</th>
                <th className="p-2 text-left font-medium">База</th>
                <th className="p-2 text-right font-medium">Средняя мощность</th>
                <th className="p-2 text-right font-medium">Медиана цены</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={`${rowClass(r)} cursor-pointer hover:bg-muted/40`}
                  onClick={() => setКарточка(r.id)} tabIndex={0} role="button"
                  onKeyDown={(e) => e.key === 'Enter' && setКарточка(r.id)}>
                  <td className="p-2 underline decoration-dotted underline-offset-2">
                    {r.name}{r.isOurs && ' · мы'}
                  </td>
                  <td className="p-2 text-right"><Num v={r.sites} /></td>
                  <td className="p-2 text-right"><Num v={r.sharePct} unit="%" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.citiesCount} /></td>
                  <td className="p-2 text-right"><Num v={r.districts} /></td>
                  <td className="p-2 text-muted-foreground">
                    {r.class ?? 'не определена'}
                    {r.class && !r.classChecked && (
                      <span className="ml-1 text-xs">· не проверено</span>
                    )}
                  </td>
                  <td className="p-2 text-muted-foreground">{r.baseCity ?? '—'}</td>
                  <td className="p-2 text-right"><Num v={r.avgPowerKw} unit="кВт" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.medianPricePerKwh} digits={1} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">{data.data?.note}</p>
        </div>
      )}

      {вид === 'platforms' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Платформа — это чья система обслуживает станции. Сеть на чужой платформе
            технологически зависит от её владельца, и разговор с ней о протоколах,
            роуминге и интеграции идёт через него. Из {t?.networks ?? 0} сетей своя
            платформа у {t?.ownPlatform ?? 0}.
          </CardContent></Card>
          {platforms.map((p) => (
            <Card key={p.owner}>
              <CardContent className="p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-headline text-sm font-semibold">{p.owner}</span>
                  <span className="text-xs text-muted-foreground">
                    своих точек {nf.format(p.ownSites)} · чужих {nf.format(p.clientSites)}
                    {p.clients.length > 0 && ` в ${p.clients.length} сетях`}
                  </span>
                </div>
                {p.clients.length > 0 ? (
                  <ul className="mt-1 space-y-0.5">
                    {p.clients.map((c) => (
                      <li key={c.name} className="flex items-baseline justify-between gap-2 text-xs">
                        <span className="text-muted-foreground">{c.name}</span>
                        <span className="tabular-nums">{nf.format(c.sites)} точек</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Обслуживает только свою сеть.
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {вид === 'roaming' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Роуминг означает, что на станции можно зарядиться через приложение другого
            оператора. В роуминге {t?.roamingNetworks ?? 0} сетей
            ({nf.format(t?.roamingSites ?? 0)} точек), только в своём приложении
            работают {t?.closedNetworks ?? 0} ({nf.format(t?.closedSites ?? 0)} точек).
            Это факт о технологии, а не о качестве сети.
          </CardContent></Card>
          <div className="rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="bg-muted/60 text-muted-foreground">
                <tr>
                  <th className="p-2 text-left font-medium">Сеть</th>
                  <th className="p-2 text-right font-medium">Точек</th>
                  <th className="p-2 text-left font-medium">Доступ</th>
                  <th className="p-2 text-right font-medium">Доля точек в роуминге</th>
                  <th className="p-2 text-left font-medium">Платформа</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={rowClass(r)}>
                    <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                    <td className="p-2 text-right"><Num v={r.sites} /></td>
                    <td className="p-2">
                      {r.roaming
                        ? <span className="text-success">роуминг с другими сетями</span>
                        : r.roaming === false
                          ? <span className="text-muted-foreground">только своё приложение</span>
                          : <span className="text-muted-foreground">нет данных</span>}
                    </td>
                    <td className="p-2 text-right"><Num v={r.roamingPct} unit="%" digits={0} /></td>
                    <td className="p-2 text-muted-foreground">{r.platformOwner ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {вид === 'service' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Сеть</th>
                <th className="p-2 text-right font-medium">Точек</th>
                <th className="p-2 text-right font-medium">Связь</th>
                <th className="p-2 text-right font-medium">Успешных зарядок</th>
                <th className="p-2 text-right font-medium">Молчат больше полугода</th>
                <th className="p-2 text-right font-medium">Оценка приложения</th>
                <th className="p-2 text-right font-medium">Отзывов</th>
                <th className="p-2 text-left font-medium">Приложение</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={rowClass(r)}>
                  <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                  <td className="p-2 text-right"><Num v={r.sites} /></td>
                  <td className="p-2 text-right"><Num v={r.quality} unit="%" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.success} unit="%" digits={1} /></td>
                  <td className="p-2 text-right">
                    <Num v={r.silentHalfYear} />
                    {r.sites > 0 && r.silentHalfYear > 0 && (
                      <span className="ml-1 text-muted-foreground">
                        {nf1.format((r.silentHalfYear / r.sites) * 100)} %
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {r.appRating == null ? <span className="text-muted-foreground">нет данных</span> : (
                      <span className={`tabular-nums ${r.appRating >= 4 ? 'text-success'
                        : r.appRating < 2.5 ? 'text-warning' : ''}`}>
                        {nf1.format(r.appRating)}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right"><Num v={r.appReviews} /></td>
                  <td className="p-2 text-muted-foreground">{r.appName ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">
            Четыре независимых среза одной темы: связь и успешность зарядок — техника,
            доля молчащих — спрос, оценка приложения — то, что об этом думает водитель.
            Пустая клетка означает, что источник этого показателя по сети не даёт.
          </p>
        </div>
      )}

      {вид === 'legal' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Реквизиты подтверждены у {t?.legalTrusted ?? 0} сетей. Ссылаться можно
            только на подтверждённые: бренд и юрлицо часто не совпадают, и ошибка здесь
            дороже молчания.
          </CardContent></Card>
          <div className="rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="bg-muted/60 text-muted-foreground">
                <tr>
                  <th className="p-2 text-left font-medium">Сеть</th>
                  <th className="p-2 text-left font-medium">Юридическое лицо</th>
                  <th className="p-2 text-left font-medium">ИНН</th>
                  <th className="p-2 text-left font-medium">ОГРН</th>
                  <th className="p-2 text-left font-medium">Руководитель</th>
                  <th className="p-2 text-left font-medium">Достоверность</th>
                </tr>
              </thead>
              <tbody>
                {rows.filter((r) => r.legalName || r.inn).map((r) => (
                  <tr key={r.id} className={rowClass(r)}>
                    <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                    <td className="p-2">{r.legalName ?? '—'}</td>
                    <td className="p-2 font-mono">{r.inn ?? '—'}</td>
                    <td className="p-2 font-mono">{r.ogrn ?? '—'}</td>
                    <td className="p-2 text-muted-foreground">{r.director ?? '—'}</td>
                    <td className="p-2">
                      <span className={r.legalTrusted ? 'text-success' : 'text-warning'}>
                        {r.legalConfidence ?? 'не проверено'}
                      </span>
                      {!r.legalTrusted && (
                        <span className="ml-1 text-muted-foreground">— ссылаться нельзя</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
