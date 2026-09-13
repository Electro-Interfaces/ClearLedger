/**
 * «Мы глазами рынка» — наш публичный профиль (docs/MARKET-ROADMAP.md, этап 1б).
 *
 * Наша сеть есть и в публичном реестре: 429 точек. Это редкая возможность увидеть
 * себя так, как видит клиент, выбирающий станцию в приложении: связь, доля успешных
 * зарядок, оценка, отзывы. И сравнить с тем, что мы знаем о себе сами.
 *
 * Расхождение здесь — не повод спорить с источником. Клиент видит именно эту
 * картинку и по ней решает, ехать или не ехать. Самый дорогой случай — станция, по
 * которой у нас идут сессии, а рынок показывает её молчащей.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, Eye } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketSelfView } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function Num({ v, unit, digits = 1 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">
    {digits ? nf1.format(v) : nf.format(v)}{unit ? ` ${unit}` : ''}
  </span>
}

export function MarketSelfPanel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-self', companyId],
    queryFn: () => getMarketSelfView(companyId, { days: 90 }),
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Сверяем наш реестр с тем, что о наших станциях знает рынок.
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const t = q.data?.totals
  // Наша сторона: журнал сессий. Пустой объект — чтобы экран пережил старый ответ
  // сервера, где этого блока ещё нет.
  const ours = q.data?.ours ?? {
    sessions: 0, successful: 0, failed: 0, successPct: null, energyKwh: 0, revenue: 0,
  }
  const peers = q.data?.peers ?? []
  const sites = q.data?.sites ?? []
  const best = peers.reduce<number | null>(
    (acc, p) => (p.quality != null && (acc == null || p.quality > acc) ? p.quality : acc), null)

  if (!t || t.inMarket === 0) {
    return (
      <Card className="m-4"><CardContent className="p-6 text-sm text-muted-foreground">
        Наших точек в публичном реестре не нашлось. Либо выгрузка ещё не загружена,
        либо оператор нашей сети в ней назван иначе — проверьте «Компании».
      </CardContent></Card>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-4">
      <Card>
        <CardContent className="space-y-2 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Eye className="size-4 text-primary" aria-hidden />
            Клиент видит {nf.format(t.inMarket)} наших станций: связь{' '}
            <Num v={t.quality} unit="%" />
            {best != null && (
              <span className="text-muted-foreground">
                против {nf1.format(best)} % у лучшей сети рынка
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
            <span>оценка <Num v={t.rating} digits={1} /> по {nf.format(t.reviews)} отзывам</span>
            {/* Слева — что о нас публикует рынок (по успешности он молчит),
                справа — наш собственный журнал сессий. Это разные источники, и
                мешать их в одно число нельзя. */}
            <span>
              успешных зарядок: рынок о нас{' '}
              {t.success != null ? <Num v={t.success} unit="%" /> : 'не публикует'}
              {ours.successPct != null && (
                <span className="text-foreground">
                  {' '}· по нашим данным {nf1.format(ours.successPct)} %
                  <span className="text-muted-foreground">
                    {' '}({nf.format(ours.failed)} срывов из {nf.format(ours.sessions)})
                  </span>
                </span>
              )}
            </span>
            <span>рынок считает живыми {nf.format(t.aliveByMarket)} из {nf.format(t.inMarket)}</span>
            <span>сопоставлено с нашим реестром {nf.format(t.matchedToRegistry)}</span>
          </div>
          {t.silentButWorking > 0 && (
            <p className="text-xs text-warning">
              {nf.format(t.silentButWorking)} станций рынок показывает молчащими, хотя
              по нашим данным на них заряжают. Клиент в приложении видит их мёртвыми и
              проезжает мимо — это потерянные сессии, а не ошибка отчёта.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="mb-2 font-headline text-sm font-semibold">
            С кем нас сравнивает клиент
          </div>
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-medium">Сеть</th>
                <th className="py-1 text-right font-medium">Точек</th>
                <th className="py-1 text-right font-medium">Связь</th>
                <th className="py-1 text-right font-medium">Успешных зарядок</th>
                <th className="py-1 text-right font-medium">Оценка</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-border bg-primary/5">
                <td className="py-1 font-medium">мы</td>
                <td className="py-1 text-right tabular-nums">{nf.format(t.inMarket)}</td>
                <td className="py-1 text-right"><Num v={t.quality} unit="%" /></td>
                <td className="py-1 text-right">
                  {ours.successPct != null ? (
                    <>
                      <span className="tabular-nums">{nf1.format(ours.successPct)} %</span>
                      <span className="text-muted-foreground"> по нашим данным</span>
                    </>
                  ) : <Num v={t.success} unit="%" />}
                </td>
                <td className="py-1 text-right"><Num v={t.rating} digits={1} /></td>
              </tr>
              {peers.map((p) => (
                <tr key={p.name} className="border-t border-border/40">
                  <td className="py-1">{p.name}</td>
                  <td className="py-1 text-right tabular-nums">{nf.format(p.sites)}</td>
                  <td className="py-1 text-right"><Num v={p.quality} unit="%" /></td>
                  <td className="py-1 text-right"><Num v={p.success} unit="%" /></td>
                  <td className="py-1 text-right"><Num v={p.rating} digits={1} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">
            Сети от 30 точек. Пустая клетка — источник не публикует этот показатель по
            сети; у нашей он пуст так же, и это само по себе стоит внимания: клиент не
            видит нашей надёжности там, где видит чужую.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="mb-2 font-headline text-sm font-semibold">
            Наши станции: где профиль хуже всего
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-medium">Станция</th>
                  <th className="py-1 text-left font-medium">Город</th>
                  <th className="py-1 text-right font-medium">Связь</th>
                  <th className="py-1 text-right font-medium">Успех</th>
                  <th className="py-1 text-right font-medium">Оценка</th>
                  <th className="py-1 text-left font-medium">Рынок видит</th>
                  <th className="py-1 text-right font-medium">Наших сессий</th>
                </tr>
              </thead>
              <tbody>
                {sites.map((r) => (
                  <tr key={r.siteId} className="border-t border-border/40">
                    <td className="py-1">{r.ourName ?? r.marketName}</td>
                    <td className="py-1 text-muted-foreground">{r.city ?? '—'}</td>
                    <td className="py-1 text-right"><Num v={r.quality} unit="%" /></td>
                    <td className="py-1 text-right"><Num v={r.successPct} unit="%" /></td>
                    <td className="py-1 text-right"><Num v={r.rating} digits={1} /></td>
                    <td className="py-1">
                      {r.aliveByMarket ? (
                        <span className="text-muted-foreground">заряжают</span>
                      ) : (
                        <span className={(r.ourSessions ?? 0) > 0 ? 'text-warning' : 'text-muted-foreground'}>
                          {(r.ourSessions ?? 0) > 0 ? 'молчит, хотя работает' : 'молчит'}
                        </span>
                      )}
                    </td>
                    <td className="py-1 text-right">
                      <Num v={r.ourSessions} digits={0} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{q.data?.note}</p>
        </CardContent>
      </Card>
    </div>
  )
}
