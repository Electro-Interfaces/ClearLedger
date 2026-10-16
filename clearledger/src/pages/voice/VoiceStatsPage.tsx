/**
 * «Статистика» — все звонки линии, а не только дошедшие до контакт-центра
 * (docs/voice-app.html ContactHub, §7). Формулы — узла (`GET /stats/definitions`),
 * они же в подсказках плиток: администратор видит, как посчитано число.
 *
 * Главный ответ экрана, которого нет в КЦ, — «Куда ушли звонки»: одна полоса долей
 * и таблица того же состава. Цвет — палитра графиков, у каждой доли подпись и
 * число: цвет не единственный признак.
 *
 * Выгрузка CSV и Excel — той же выборки, что на экране, первой строкой фильтры.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Download } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { скачатьCSV, скачатьExcel, type Лист } from './exportTable'
import { деньФайла, началоДня, оператор, процент, сек, число } from './format'
import { Heading, NodeError, Stat } from './parts'
import { кудаУшли, поВремени, поГруппам } from './statsMath'

const ЧЕТВЕРТЬ = 15 * 60_000
/** Конец периода «по сейчас» — вверх до 15 минут, как округляет узел: ключ запроса не меняется каждую секунду. */
const сейчасДо15 = () => new Date(Math.ceil(Date.now() / ЧЕТВЕРТЬ) * ЧЕТВЕРТЬ).toISOString()
const началоМесяца = () => { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(1); return d.toISOString() }

const ПЕРИОДЫ = [
  { key: 'today', name: 'Сегодня', from: () => началоДня(0), to: сейчасДо15 },
  { key: 'yesterday', name: 'Вчера', from: () => началоДня(-1), to: () => началоДня(0) },
  { key: 'week', name: '7 дней', from: () => началоДня(-6), to: сейчасДо15 },
  { key: 'days30', name: '30 дней', from: () => началоДня(-29), to: сейчасДо15 },
  { key: 'month', name: 'Этот месяц', from: началоМесяца, to: сейчасДо15 },
] as const

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Moscow'

export default function VoiceStatsPage() {
  const { companyId } = useCompany()
  const [период, setПериод] = useState<(typeof ПЕРИОДЫ)[number]['key']>('today')
  const [толькоКЦ, setТолькоКЦ] = useState(false)
  const п = ПЕРИОДЫ.find(x => x.key === период) ?? ПЕРИОДЫ[0]
  const from = п.from()
  const to = п.to()
  const длинный = Date.parse(to) - Date.parse(from) > 2 * 86_400_000
  const шаг = длинный ? '1d' : '1h'
  const servedBy = толькоКЦ ? 'cc' : ''
  const кц = (r: voice.SeriesRow) => !толькоКЦ || r.group?.servedBy === 'cc'

  const опр = useQuery({
    queryKey: ['voice-stats-defs', companyId],
    queryFn: () => voice.statsDefinitions(companyId),
    staleTime: Infinity,
  })
  const сводка = useQuery({
    queryKey: ['voice-stats', companyId, 'summary', from, to, servedBy],
    queryFn: () => voice.statsSummary(companyId, { from, to, tz: TZ, servedBy }),
  })
  const ряд = useQuery({
    queryKey: ['voice-stats', companyId, 'series', from, to, шаг],
    queryFn: () => voice.statsSeries(companyId, { from, to, tz: TZ, interval: шаг, groupBy: 'servedBy' }),
  })
  const темы = useQuery({
    queryKey: ['voice-stats', companyId, 'topic', from, to],
    queryFn: () => voice.statsSeries(companyId, { from, to, tz: TZ, interval: '1mo', groupBy: 'topic,servedBy' }),
  })
  const центры = useQuery({
    queryKey: ['voice-stats', companyId, 'cc', from, to],
    queryFn: () => voice.statsSeries(companyId, { from, to, tz: TZ, interval: '1mo', groupBy: 'cc' }),
  })
  const операторы = useQuery({
    queryKey: ['voice-stats', companyId, 'operators', from, to],
    queryFn: () => voice.statsOperators(companyId, { from, to }),
  })

  const пояснение = useMemo(() => {
    const map = new Map((опр.data ?? []).map(d => [d.key, `${d.title}: ${d.formula}`]))
    return (k: string) => map.get(k)
  }, [опр.data])

  const m = сводка.data
  const части = m ? кудаУшли(m) : []
  const всего = m?.arrived ?? 0
  const поЧасам = ряд.data ? поВремени(ряд.data.rows, кц) : []
  const поТемам = темы.data ? поГруппам(темы.data.rows, 'topic', кц).sort((a, b) => (b.m.arrived ?? 0) - (a.m.arrived ?? 0)) : []
  const поКЦ = центры.data ? поГруппам(центры.data.rows, 'cc').filter(x => x.группа) : []

  const подписьИнтервала = (iso: string) => new Date(iso).toLocaleString('ru-RU',
    длинный ? { day: 'numeric', month: 'short' } : { day: 'numeric', hour: '2-digit', minute: '2-digit' })

  function листы(): Лист[] {
    const фильтр = `Период: ${п.name} (${new Date(from).toLocaleString('ru-RU')} — ${new Date(to).toLocaleString('ru-RU')}); `
      + `${толькоКЦ ? 'только дошедшие до КЦ' : 'все звонки линии'}; часовой пояс ${TZ}`
    const сводкаСтроки = (опр.data ?? []).filter(d => d.key !== 'fallbackByReason').map(d => {
      const v = m?.[d.key as keyof voice.Metrics]
      return [d.title, typeof v === 'number' ? v : null, d.unit ?? '', d.formula]
    })
    return [
      { имя: 'Сводка', строки: [[фильтр], ['Показатель', 'Значение', 'Ед.', 'Формула'], ...сводкаСтроки] },
      { имя: 'Куда ушли звонки', строки: [[фильтр], ['Исход', 'Звонков', 'Доля, %'],
        ...части.map(x => [x.имя, x.n, всего ? Math.round((x.n / всего) * 1000) / 10 : null])] },
      { имя: 'По времени', строки: [[фильтр], ['Начало', 'Поступило', 'Отвечено', 'Брошено', 'Запасной', 'SL, %'],
        ...поЧасам.map(r => [new Date(r.start).toLocaleString('ru-RU'), r.m.arrived ?? 0, r.m.answered ?? 0, r.m.abandoned ?? 0, r.m.fallback ?? 0, r.m.slPct ?? null])] },
      { имя: 'По темам', строки: [[фильтр], ['Тема', 'Поступило', 'Отвечено', 'SL, %', 'ASA, с', 'Переводы, %', 'FCR, %'],
        ...поТемам.map(r => [r.группа || 'без темы', r.m.arrived ?? 0, r.m.answered ?? 0, r.m.slPct ?? null, r.m.asaSec ?? null, r.m.transferPct ?? null, r.m.fcrPct ?? null])] },
      { имя: 'По контакт-центрам', строки: [[фильтр], ['Подключение КЦ', 'Поставлено', 'Отвечено', 'SL, %', 'ASA, с', 'Брошено, %'],
        ...поКЦ.map(r => [r.группа, r.m.offered ?? 0, r.m.answered ?? 0, r.m.slPct ?? null, r.m.asaSec ?? null, r.m.abandonPct ?? null])] },
      { имя: 'По операторам', строки: [[фильтр], ['Оператор', 'Отвечено', 'AHT, с', 'Разговор, с', 'Переводы'],
        ...(операторы.data ?? []).map(r => [оператор(r.operator), r.metrics.answered ?? 0, r.metrics.ahtSec ?? null, r.metrics.talkSec ?? null, r.metrics.transferred ?? 0])] },
    ]
  }

  // Имя файла — местные дни периода (to в период не входит): по UTC начало дня — ещё вчера.
  const первыйДень = деньФайла(from)
  const последнийДень = деньФайла(Date.parse(to) - 1)
  const файл = `телефония-статистика-${первыйДень === последнийДень ? первыйДень : `${первыйДень}_${последнийДень}`}`
  async function выгрузить(как: 'csv' | 'xlsx') {
    try {
      if (как === 'csv') скачатьCSV(файл, листы()); else await скачатьExcel(файл, листы())
    } catch (e) {
      toast.error(e instanceof Error ? `Выгрузка не удалась: ${e.message}` : 'Выгрузка не удалась')
    }
  }

  const наибольшее = Math.max(1, ...поЧасам.map(r => r.m.arrived ?? 0))

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Статистика" подпись="Все звонки линии: и отвеченные, и брошенные, и пришедшие вне часов.">
        <Button variant="outline" size="sm" onClick={() => void выгрузить('csv')} disabled={!m}><Download />CSV</Button>
        <Button variant="outline" size="sm" onClick={() => void выгрузить('xlsx')} disabled={!m}><Download />Excel</Button>
      </Heading>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5">
          {ПЕРИОДЫ.map(x => (
            <button key={x.key} type="button" onClick={() => setПериод(x.key)} aria-pressed={период === x.key}
              className={cn('min-h-8 rounded px-3 text-sm transition-colors',
                период === x.key ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
              {x.name}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={толькоКЦ} onCheckedChange={setТолькоКЦ} aria-label="Только дошедшие до КЦ" />
          только дошедшие до КЦ
        </label>
      </div>

      {сводка.isLoading && <p role="status" className="text-sm">Считаем у узла…</p>}
      {сводка.isError && <NodeError ошибка={сводка.error} что="посчитать статистику" />}
      {m && !всего && (
        <EmptyBlock иконка={BarChart3} текст="За этот период звонков нет" подсказка="Выберите период подлиннее." />
      )}

      {m && !!всего && (
        <>
          <section aria-label="Показатели" className="flex flex-wrap gap-x-8 gap-y-3 rounded-xl border border-border bg-card p-4">
            <Stat имя="Поступило" значение={число(m.arrived)} пояснение={пояснение('arrived')} />
            <Stat имя="Вне часов" значение={число(m.afterHours)} пояснение={пояснение('afterHours')} />
            {/* Перевод с другой линии ставит звонок в очередь ещё раз: «в очередь» бывает больше «поступило». */}
            <Stat имя="В очередь" значение={число(m.offered)}
              пояснение={(m.transferredIn ?? 0) > 0 ? `${пояснение('offered') ?? ''}. ${пояснение('transferredIn') ?? ''}` : пояснение('offered')}
              подпись={(m.transferredIn ?? 0) > 0 ? `из них ${число(m.transferredIn)} переводом с другой линии` : undefined} />
            <Stat имя="Отвечено" значение={число(m.answered)} пояснение={пояснение('answered')} />
            <Stat имя="SL — ответили вовремя" значение={процент(m.slPct)} пояснение={пояснение('slPct')} />
            <Stat имя="ASA — среднее ожидание" значение={сек(m.asaSec)}
              пояснение={`${пояснение('asaSec') ?? ''}. P90 — ${сек(m.waitP90Sec)}, максимум — ${сек(m.waitMaxSec)}`} />
            <Stat имя="Брошено" значение={процент(m.abandonPct)} пояснение={пояснение('abandonPct')}
              тон={(m.abandonPct ?? 0) > 10 ? 'warning' : undefined} />
            <Stat имя="Запасной сценарий" значение={процент(m.fallbackPct)} пояснение={пояснение('fallbackPct')} />
            <Stat имя="AHT — время обработки" значение={сек(m.ahtSec)} пояснение={пояснение('ahtSec')} />
            <Stat имя="Переводы" значение={процент(m.transferPct)} пояснение={пояснение('transferPct')} />
            <Stat имя="FCR — решено с первого раза" значение={процент(m.fcrPct)} пояснение={пояснение('fcrPct')} />
            <Stat имя="Итог не записан" значение={число(m.noDisposition)} пояснение={пояснение('noDisposition')}
              тон={(m.noDisposition ?? 0) > 0 ? 'warning' : undefined} />
          </section>

          <section aria-label="Куда ушли звонки" className="space-y-3 rounded-xl border border-border bg-card p-4">
            <h2 className="font-headline text-base font-semibold">Куда ушли звонки</h2>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-border" aria-hidden="true">
              {части.filter(x => x.n).map(x => <div key={x.key} className={x.цвет} style={{ width: `${(x.n / всего) * 100}%` }} />)}
            </div>
            <table className="w-full max-w-xl text-sm">
              <tbody>
                {части.map(x => (
                  <tr key={x.key} className="border-t border-border/60">
                    <td className="py-1.5"><span className="inline-flex items-center gap-2"><i className={cn('h-2.5 w-2.5 rounded-sm', x.цвет)} />{x.имя}</span></td>
                    <td className="py-1.5 text-right tabular-nums">{число(x.n)}</td>
                    <td className="w-20 py-1.5 text-right tabular-nums text-muted-foreground">{процент(Math.round((x.n / всего) * 1000) / 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!!m.fallbackByReason && Object.keys(m.fallbackByReason).length > 0 && (
              <p className="text-xs text-muted-foreground">
                Запасной сценарий по причинам: {Object.entries(m.fallbackByReason).map(([к, n]) =>
                  `${ПРИЧИНА_ЗАПАСНОГО[к] ?? к} — ${n}`).join(', ')}
              </p>
            )}
          </section>

          <section aria-label="По времени" className="space-y-2 rounded-xl border border-border bg-card p-4">
            <h2 className="font-headline text-base font-semibold">{длинный ? 'По дням' : 'По часам'}</h2>
            {ряд.isError && <NodeError ошибка={ряд.error} что="построить ряд" />}
            {!!поЧасам.length && (
              <>
                <div className="flex h-40 items-end gap-0.5" aria-hidden="true">
                  {поЧасам.map(r => {
                    const h = (n?: number) => `${((n ?? 0) / наибольшее) * 100}%`
                    return (
                      <div key={r.start} className="flex h-full min-w-1 flex-1 flex-col justify-end" title={
                        `${подписьИнтервала(r.start)}: поступило ${r.m.arrived ?? 0}, отвечено ${r.m.answered ?? 0}, брошено ${r.m.abandoned ?? 0}`}>
                        <div className="bg-chart-3" style={{ height: h(r.m.abandoned) }} />
                        <div className="bg-chart-5" style={{ height: h(r.m.fallback) }} />
                        <div className="rounded-t-sm bg-chart-1" style={{ height: h(r.m.answered) }} />
                      </div>
                    )
                  })}
                </div>
                <ul className="flex flex-wrap gap-x-4 text-xs">
                  <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-1" />отвечено</li>
                  <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-5" />запасной сценарий</li>
                  <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-3" />брошено</li>
                </ul>
                <details className="text-sm">
                  <summary className="cursor-pointer text-xs text-muted-foreground">Таблица</summary>
                  <table className="mt-1 w-full text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr><th className="py-1 font-normal">Начало</th><th className="py-1 text-right font-normal">Поступило</th>
                        <th className="py-1 text-right font-normal">Отвечено</th><th className="py-1 text-right font-normal">Брошено</th>
                        <th className="py-1 text-right font-normal">SL</th></tr>
                    </thead>
                    <tbody>
                      {поЧасам.map(r => (
                        <tr key={r.start} className="border-t border-border/60">
                          <td className="py-1">{подписьИнтервала(r.start)}</td>
                          <td className="py-1 text-right tabular-nums">{r.m.arrived ?? 0}</td>
                          <td className="py-1 text-right tabular-nums">{r.m.answered ?? 0}</td>
                          <td className="py-1 text-right tabular-nums">{r.m.abandoned ?? 0}</td>
                          <td className="py-1 text-right tabular-nums">{процент(r.m.slPct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            )}
          </section>

          <div className="grid gap-4 xl:grid-cols-2">
            <section aria-label="По темам" className="space-y-2 rounded-xl border border-border bg-card p-4">
              <h2 className="font-headline text-base font-semibold">По темам</h2>
              {!поТемам.length ? <p className="text-sm text-muted-foreground">Тем за период нет.</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr><th className="py-1 font-normal">Тема</th><th className="py-1 text-right font-normal">Звонков</th>
                        <th className="py-1 text-right font-normal">SL</th><th className="py-1 text-right font-normal">Ожидание</th>
                        <th className="py-1 text-right font-normal">Переводы</th><th className="py-1 text-right font-normal">FCR</th></tr>
                    </thead>
                    <tbody>
                      {поТемам.map(r => (
                        <tr key={r.группа} className="border-t border-border/60">
                          <td className="py-1.5">{r.группа ? <span className="font-mono text-xs">{r.группа}</span> : <span className="text-muted-foreground">без темы</span>}</td>
                          <td className="py-1.5 text-right tabular-nums">{число(r.m.arrived)}</td>
                          <td className="py-1.5 text-right tabular-nums">{процент(r.m.slPct)}</td>
                          <td className="py-1.5 text-right tabular-nums">{сек(r.m.asaSec)}</td>
                          <td className="py-1.5 text-right tabular-nums">{процент(r.m.transferPct)}</td>
                          <td className="py-1.5 text-right tabular-nums">{процент(r.m.fcrPct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section aria-label="По контакт-центрам" className="space-y-2 rounded-xl border border-border bg-card p-4">
              <h2 className="font-headline text-base font-semibold">По контакт-центрам</h2>
              {!поКЦ.length ? <p className="text-sm text-muted-foreground">Звонков через контакт-центр за период нет.</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr><th className="py-1 font-normal">Подключение</th><th className="py-1 text-right font-normal">В очередь</th>
                        <th className="py-1 text-right font-normal">Отвечено</th><th className="py-1 text-right font-normal">SL</th>
                        <th className="py-1 text-right font-normal">Ожидание</th><th className="py-1 text-right font-normal">Брошено</th></tr>
                    </thead>
                    <tbody>
                      {поКЦ.map(r => (
                        <tr key={r.группа} className="border-t border-border/60">
                          <td className="py-1.5 font-mono text-xs">{r.группа}</td>
                          <td className="py-1.5 text-right tabular-nums">{число(r.m.offered)}</td>
                          <td className="py-1.5 text-right tabular-nums">{число(r.m.answered)}</td>
                          <td className="py-1.5 text-right tabular-nums">{процент(r.m.slPct)}</td>
                          <td className="py-1.5 text-right tabular-nums">{сек(r.m.asaSec)}</td>
                          <td className="py-1.5 text-right tabular-nums">{процент(r.m.abandonPct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          <section aria-label="По операторам" className="space-y-2 rounded-xl border border-border bg-card p-4">
            <h2 className="font-headline text-base font-semibold">По операторам</h2>
            <p className="text-xs text-muted-foreground">По первому ответившему. Операторы КЦ — под псевдонимом, который дал контакт-центр.</p>
            {операторы.isError && <NodeError ошибка={операторы.error} что="посчитать по операторам" />}
            {операторы.data && !операторы.data.length && <p className="text-sm text-muted-foreground">Отвеченных за период нет.</p>}
            {!!операторы.data?.length && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr><th className="py-1 font-normal">Оператор</th><th className="py-1 text-right font-normal">Отвечено</th>
                      <th className="py-1 text-right font-normal">AHT</th><th className="py-1 text-right font-normal">Разговор</th>
                      <th className="py-1 text-right font-normal">Переводы</th></tr>
                  </thead>
                  <tbody>
                    {операторы.data.map(r => (
                      <tr key={`${r.operator.kind}:${r.operator.id}`} className="border-t border-border/60">
                        <td className="py-1.5">{оператор(r.operator)}</td>
                        <td className="py-1.5 text-right tabular-nums">{число(r.metrics.answered)}</td>
                        <td className="py-1.5 text-right tabular-nums">{сек(r.metrics.ahtSec)}</td>
                        <td className="py-1.5 text-right tabular-nums">{сек(r.metrics.talkSec)}</td>
                        <td className="py-1.5 text-right tabular-nums">{число(r.metrics.transferred)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

const ПРИЧИНА_ЗАПАСНОГО: Record<string, string> = {
  max_wait: 'потолок ожидания',
  kc_offline: 'КЦ не на связи',
  no_command: 'КЦ не назначил оператора',
  rule: 'правило',
}
