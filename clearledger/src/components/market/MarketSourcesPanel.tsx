/**
 * «Источники и свежесть» — откуда мы знаем рынок и можно ли этому верить сегодня.
 *
 * Разведка рынка — задача о свежести, а не о дашборде (docs/MARKET-ROADMAP.md §3.4):
 * цену недельной давности показывать можно, месячной — опасно, потому что она
 * выглядит достоверно, а решение по ней уже ошибочно. Поэтому здесь три ответа:
 * ЧТО у нас есть (источники и их ранг), НАСКОЛЬКО оно заполнено (покрытие полей —
 * такой же показатель, как цена) и ЧТО ИЗМЕНИЛОСЬ между срезами.
 *
 * Покрытие не прячется: неравномерная заполненность — свойство публичного реестра,
 * и человек должен видеть, что «производитель» известен у каждой десятой точки,
 * прежде чем строить на этом поле вывод.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Database, Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getMarketChanges, getMarketSources, SITE_CLASS_LABEL, SOURCE_LABEL,
  type MarketChangeCard, type MarketSource,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')

const ВИДЫ = [
  { k: 'sources', label: 'Источники' },
  { k: 'coverage', label: 'Покрытие полей' },
  { k: 'changes', label: 'Что изменилось' },
] as const

/** Возраст факта словами: по нему видно, можно ли доверять, а не только когда это было. */
function age(iso: string | null): { text: string; stale: boolean } {
  if (!iso) return { text: 'не приходило', stale: true }
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return { text: 'сегодня', stale: false }
  if (days === 1) return { text: 'вчера', stale: false }
  if (days < 30) return { text: `${days} дн назад`, stale: false }
  return { text: `${days} дн назад`, stale: true }
}

/** Полоса покрытия. Цвет помогает, но число рядом — носитель смысла, а не цвет. */
function Coverage({ label, pct }: { label: string; pct: number }) {
  const tone = pct >= 70 ? 'bg-success' : pct >= 30 ? 'bg-warning' : 'bg-destructive'
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={`block h-full ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
      <span className="w-24 shrink-0 text-xs tabular-nums">
        {pct} % точек{pct < 30 ? ' — мало' : ''}
      </span>
    </div>
  )
}

function SourceCard({ s }: { s: MarketSource }) {
  const seen = age(s.lastSeenAt)
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="font-headline text-sm font-semibold">
            {SOURCE_LABEL[s.source] ?? s.source}
          </span>
          <span className="text-xs text-muted-foreground">
            ранг {s.rank} · {s.source}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span className="tabular-nums">{nf.format(s.sites)} точек</span>
          <span className={seen.stale ? 'text-warning' : 'text-muted-foreground'}>
            последний контакт: {seen.text}
          </span>
          {s.homeSockets > 0 && (
            <span className="text-muted-foreground tabular-nums">
              из них домашних розеток {nf.format(s.homeSockets)}
            </span>
          )}
          {s.closed > 0 && (
            <span className="text-muted-foreground tabular-nums">закрытых {nf.format(s.closed)}</span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ChangeList({ title, hint, rows, unit }: {
  title: string; hint: string; rows: MarketChangeCard[]; unit?: string
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-2">
          <span className="font-headline text-sm font-semibold">{title}</span>
          <span className="ml-2 text-xs tabular-nums text-muted-foreground">{rows.length}</span>
          <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
        </div>
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            За выбранные срезы таких точек нет.
          </p>
        ) : (
          <ul className="space-y-1">
            {rows.slice(0, 12).map((r) => (
              <li key={r.id} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">
                  {r.name}
                  {r.city ? <span className="text-muted-foreground"> · {r.city}</span> : null}
                  {r.siteClass === 'home' && (
                    <span className="text-muted-foreground"> · {SITE_CLASS_LABEL.home}</span>
                  )}
                </span>
                {r.was != null && r.now != null && (
                  <span className="shrink-0 tabular-nums">
                    {r.was} → {r.now}{unit ? ` ${unit}` : ''}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/** Скелетон вместо спиннера: экран с данными грузится в свою же раскладку. */
function Skeleton() {
  return (
    <div className="space-y-2 p-4" aria-busy="true">
      <span className="sr-only">Считаем источники рынка</span>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-20 animate-pulse rounded-lg border border-border bg-muted/40" />
      ))}
    </div>
  )
}

export function MarketSourcesPanel() {
  const { companyId } = useCompany()
  const [вид, setВид] = useState<string>('sources')
  const [base, setBase] = useState<string>('')
  const [current, setCurrent] = useState<string>('')

  const sources = useQuery({
    queryKey: ['market-sources', companyId],
    queryFn: () => getMarketSources(companyId),
    enabled: !!companyId,
  })
  const changes = useQuery({
    queryKey: ['market-changes', companyId, base, current],
    queryFn: () => getMarketChanges(companyId, {
      ...(base ? { base } : {}), ...(current ? { current } : {}),
    }),
    enabled: !!companyId && вид === 'changes',
  })

  if (sources.isLoading) return <Skeleton />

  const data = sources.data
  const totals = data?.totals
  const snapshots = data?.snapshots ?? []
  const lastSnapshot = snapshots[0]

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      {/* Вывод экрана словами: с него человек начинает, а таблицы объясняют. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
          <span className="flex items-center gap-2 text-sm">
            <Database className="size-4 text-primary" aria-hidden />
            <span className="font-semibold tabular-nums">{nf.format(totals?.sites ?? 0)}</span>
            точек рынка из {data?.sources.length ?? 0} источников
          </span>
          <span className="text-xs text-muted-foreground">
            свежесть: {lastSnapshot ? `срез от ${lastSnapshot.date}` : 'срезов ещё не было'}
          </span>
          <span className="text-xs">
            <span className="tabular-nums">{nf.format(totals?.alive ?? 0)}</span> живых —
            заряжали за {totals?.aliveDays ?? 90} дней
          </span>
          <span className="text-xs text-muted-foreground">
            цена известна у <span className="tabular-nums">{nf.format(totals?.priced ?? 0)}</span>
            {totals?.conflicts ? `, спорных наблюдений ${nf.format(totals.conflicts)}` : ''}
          </span>
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'sources' && (
        <div className="grid gap-2 md:grid-cols-2">
          {(data?.sources ?? []).map((s) => <SourceCard key={s.source} s={s} />)}
          {(data?.sources ?? []).length === 0 && (
            <Card><CardContent className="p-4 text-xs text-muted-foreground">
              Рынок пуст. Точки приходят выгрузкой реестра через «Данные → Коннекторы»,
              импортом списком или наблюдением с места.
            </CardContent></Card>
          )}
        </div>
      )}

      {вид === 'coverage' && (
        <div className="space-y-2">
          {(data?.sources ?? []).map((s) => (
            <Card key={s.source}>
              <CardContent className="space-y-2 p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-headline text-sm font-semibold">
                    {SOURCE_LABEL[s.source] ?? s.source}
                  </span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {nf.format(s.sites)} точек
                  </span>
                </div>
                <Coverage label="координаты" pct={s.coverage.geo} />
                <Coverage label="мощность" pct={s.coverage.power} />
                <Coverage label="производитель" pct={s.coverage.vendor} />
                <Coverage label="успешность" pct={s.coverage.successPct} />
                <Coverage label="последняя зарядка" pct={s.coverage.lastSession} />
              </CardContent>
            </Card>
          ))}
          <p className="text-xs text-muted-foreground">
            Заполненность неравномерна — это свойство источника, а не ошибка загрузки.
            Там, где поля нет, экраны показывают «нет данных», а не ноль: ноль в мощности
            и в успешности — осмысленное значение, и подменять им пропуск нельзя.
          </p>
        </div>
      )}

      {вид === 'changes' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Сравнить срез</span>
            <Select value={base || (changes.data?.base ?? '')} onValueChange={setBase}>
              <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="основание" /></SelectTrigger>
              <SelectContent>
                {(changes.data?.available ?? []).map((d) => (
                  <SelectItem key={d} value={d}>{d}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">со срезом</span>
            <Select value={current || (changes.data?.current ?? '')} onValueChange={setCurrent}>
              <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="свежий" /></SelectTrigger>
              <SelectContent>
                {(changes.data?.available ?? []).map((d) => (
                  <SelectItem key={d} value={d}>{d}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {changes.isFetching && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          </div>

          {changes.data?.message ? (
            <Card><CardContent className="p-4 text-xs text-muted-foreground">
              {changes.data.message}
            </CardContent></Card>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              <ChangeList title="Появились" rows={changes.data?.appeared ?? []}
                hint="Точек не было в прошлом срезе — рядом мог открыться конкурент." />
              <ChangeList title="Исчезли" rows={changes.data?.gone ?? []}
                hint="Пропали из выгрузки. Закрытыми считаются после трёх пропусков подряд." />
              <ChangeList title="Сменили цену" rows={changes.data?.priceMoves ?? []}
                unit="₽/кВт·ч" hint="Движение тарифа соседей — повод пересчитать свой." />
              <ChangeList title="Упала связь" rows={changes.data?.qualityDrops ?? []}
                unit="%" hint="Качество связи просело на 20 пунктов и больше." />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
