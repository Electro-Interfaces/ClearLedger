/**
 * «Приоритеты» — что брать, что расшивать, что отклонить.
 *
 * Две оси вместо одного балла: привлекательность (стоит ли здесь стоять) ×
 * исполнимость (можно ли это сделать). Четыре квадранта — четыре разных действия.
 *
 * Балл считается только по факторам, данные по которым есть, и рядом всегда идёт
 * УВЕРЕННОСТЬ. Площадка с одним известным фактором не выдаётся за оценённую:
 * при низкой уверенности она попадает в «Не хватает данных» — это честнее
 * середины шкалы и прямо говорит, что делать дальше (добрать факты).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Info } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import {
  getSitesMatrix, getSitesOverview, QUADRANT_META, STAGE_META,
  type MatrixItem, type Quadrant,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { ProjectPhaseStrip } from './ProjectPhaseStrip'
import { useOpenProject } from './useOpenProject'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

export function SitesPriorityPanel({ companyId }: { companyId: string }) {
  const [region, setRegion] = useState('')
  const [quadrant, setQuadrant] = useState<'' | Quadrant>('')
  const [detailId, setDetailId] = useState<string | null>(null)
  // Клик — рабочий экран проекта, Alt+клик — быстрый просмотр.
  const openProject = useOpenProject()

  const ov = useQuery({ queryKey: ['sites-overview', companyId], queryFn: () => getSitesOverview(companyId) })
  const q = useQuery({
    queryKey: ['sites-matrix', companyId, region],
    queryFn: () => getSitesMatrix(companyId, { region: region || undefined }),
  })
  const d = q.data

  const items = useMemo(
    () => (d?.items ?? []).filter((i) => !quadrant || i.quadrant === quadrant),
    [d, quadrant],
  )
  const bench = d?.benchmark.network

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Приоритеты площадок</h2>
          <p className="text-sm text-muted-foreground">
            Чем заняться в первую очередь на этапе подбора: привлекательность (спрос и покрытие)
            × исполнимость (мощность, деньги, право). Клик по строке открывает проект.
          </p>
        </div>
        <Select value={region || '__all__'} onValueChange={(v) => setRegion(v === '__all__' ? '' : v)}>
          <SelectTrigger className="h-8 w-[200px] text-sm"><SelectValue placeholder="Все регионы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-sm">Все регионы</SelectItem>
            {(ov.data?.byRegion ?? []).map((r) => (
              <SelectItem key={r.region} value={r.region} className="text-sm">{r.region} ({r.count})</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <ProjectPhaseStrip current="select"
        note="Приоритеты считаются для проектов на первом этапе — что двигать вперёд к земле и реализации." />

      {q.isLoading || !d ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {d.quadrants.map((qd) => (
              <button key={qd.key} type="button" onClick={() => setQuadrant((v) => (v === qd.key ? '' : qd.key))}
                className={`text-left rounded-lg border p-3 transition-colors ${quadrant === qd.key ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'}`}>
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <span className={`h-2 w-2 rounded-full ${QUADRANT_META[qd.key].dot}`} />{qd.label}
                </div>
                <div className="text-xl font-semibold mt-1">{nf0.format(qd.count)}</div>
                <div className="text-xs text-muted-foreground leading-tight mt-0.5">{qd.hint}</div>
              </button>
            ))}
          </div>

          {/* Поле матрицы: ось X — исполнимость, ось Y — привлекательность */}
          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
                Карта решений — каждая точка это площадка
              </div>
              <div className="p-4">
                <MatrixPlot items={(d.items ?? []).filter((i) => i.quadrant !== 'need_data')}
                  onPick={(id) => setDetailId(id)} />
                <div className="mt-2 text-xs text-muted-foreground">
                  На поле показаны только оценённые площадки
                  ({nf0.format((d.items ?? []).filter((i) => i.quadrant !== 'need_data').length)} из {nf0.format(d.total)}).
                  Остальным не хватает данных — по ним решать нечего, их надо дособрать.
                </div>
              </div>
            </CardContent>
          </Card>

          {bench && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard label="Медиана выработки станции" value={`${nf0.format(bench.kwhMonth ?? 0)} кВт·ч/мес`}
                hint={`по ${bench.stations} станциям сети за ${d.benchmark.months} мес`} />
              <KpiCard label="Верхняя четверть (p75)" value={`${nf0.format(bench.kwhP75 ?? 0)} кВт·ч/мес`}
                hint="ориентир хорошего сценария" />
              <KpiCard label="Средний тариф сети" value={`${nf1.format(bench.tariff ?? 0)} ₽/кВт·ч`}
                hint="факт по сессиям, вкл. корп-тарифы" />
              <KpiCard label="Риск каннибализации"
                value={nf0.format((d.items ?? []).filter((i) => i.cannibalization).length)}
                hint={`ближе ${d.thresholds.cannibalKm * 1000} м к своей станции`} accent="warning" />
            </div>
          )}

          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40 flex items-center justify-between">
                <span>{quadrant ? QUADRANT_META[quadrant].label : 'Все площадки по приоритету'}</span>
                <span className="font-mono">{nf0.format(items.length)}</span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/20 text-muted-foreground">
                    <th className="text-left p-2 font-medium">Проект</th>
                    <th className="text-left p-2 font-medium">Адрес / место</th>
                    <th className="text-left p-2 font-medium">Стадия</th>
                    <th className="text-right p-2 font-medium">Привлек.</th>
                    <th className="text-right p-2 font-medium">Исполн.</th>
                    <th className="text-right p-2 font-medium">Увер.</th>
                    <th className="text-right p-2 font-medium">До сети, км</th>
                    <th className="text-left p-2 font-medium">Решение</th>
                    <th className="text-left p-2 font-medium">Чего не хватает</th>
                  </tr>
                </thead>
                <tbody>
                  {items.slice(0, 300).map((it) => (
                    <tr key={it.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                      onClick={(ev) => (ev.altKey ? setDetailId(it.id) : openProject(it.id))}>
                      <td className="p-2 whitespace-nowrap font-mono">{it.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[240px] truncate" title={it.address ?? ''}>
                        {it.address ?? it.city ?? '—'}
                        <span className="text-muted-foreground"> · {it.region ?? ''}</span>
                      </td>
                      <td className="p-2">
                        <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[it.stage]?.cls ?? ''}`}>
                          {it.stageLabel}
                        </span>
                      </td>
                      <td className="p-2 text-right font-mono">{it.attract ?? '—'}</td>
                      <td className="p-2 text-right font-mono">{it.feasible ?? '—'}</td>
                      <td className={`p-2 text-right font-mono ${it.confidence < 34 ? 'text-red-600 dark:text-red-400' : it.confidence < 67 ? 'text-amber-600 dark:text-amber-400' : ''}`}>
                        {it.confidence}%
                      </td>
                      <td className={`p-2 text-right font-mono ${it.cannibalization ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                        {it.nearestStationKm != null ? nf1.format(it.nearestStationKm) : '—'}
                      </td>
                      <td className="p-2">
                        <span className={`text-xs rounded border px-1.5 py-0.5 ${QUADRANT_META[it.quadrant].cls}`}
                          title={QUADRANT_META[it.quadrant].hint}>{QUADRANT_META[it.quadrant].label}</span>
                      </td>
                      <td className="p-2 max-w-[260px] truncate text-muted-foreground" title={it.unknown.join('; ')}>
                        {it.unknown[0] ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {items.length > 300 && (
                <div className="px-3 py-2 text-xs text-muted-foreground border-t">
                  Показаны первые 300 из {nf0.format(items.length)} — сузьте регион или квадрант.
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              Привлекательность: удалённость от собственных станций (близко — делёж трафика,
              далеко — новое покрытие), спрос региона по нашим фактическим сессиям, тип места и якорь.
              Исполнимость: свободная мощность, стоимость и срок подключения, расстояние до ТП,
              определённость права, ставка аренды. Уверенность — доля факторов, по которым есть данные.
            </span>
          </div>
        </>
      )}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}

/** Поле «привлекательность × исполнимость» с квадрантами и точками-площадками. */
function MatrixPlot({ items, onPick }: { items: MatrixItem[]; onPick: (id: string) => void }) {
  if (items.length === 0) {
    return <div className="py-10 text-center text-sm text-muted-foreground">
      Оценённых площадок нет — сначала нужно добрать данные (мощность, стоимость подключения, право).
    </div>
  }
  return (
    <div className="relative w-full" style={{ paddingBottom: '52%' }}>
      <div className="absolute inset-0">
        {/* фон квадрантов */}
        <div className="absolute inset-0 grid grid-cols-2 grid-rows-2">
          <div className="border border-border/50 bg-amber-500/[0.04]" />
          <div className="border border-border/50 bg-emerald-500/[0.05]" />
          <div className="border border-border/50 bg-red-400/[0.04]" />
          <div className="border border-border/50 bg-sky-500/[0.04]" />
        </div>
        {/* подписи квадрантов */}
        <span className="absolute left-2 top-2 text-xs text-amber-700 dark:text-amber-400">Расшивать узкое место</span>
        <span className="absolute right-2 top-2 text-xs text-emerald-700 dark:text-emerald-400">Делать сейчас</span>
        <span className="absolute left-2 bottom-6 text-xs text-red-600 dark:text-red-400">Кандидат на отказ</span>
        <span className="absolute right-2 bottom-6 text-xs text-sky-700 dark:text-sky-400">Дешёвый опцион</span>
        {/* точки */}
        {items.map((it) => {
          const x = (it.feasible ?? 0) / 100
          const y = (it.attract ?? 0) / 100
          const size = 6 + (it.confidence / 100) * 6
          return (
            <button key={it.id} type="button" onClick={() => onPick(it.id)}
              title={`${it.region ?? ''} ${it.city ?? ''} — привлекательность ${it.attract}, исполнимость ${it.feasible}, уверенность ${it.confidence}%`}
              className={`absolute rounded-full ${QUADRANT_META[it.quadrant].dot} opacity-80 hover:opacity-100 hover:ring-2 ring-primary/40`}
              style={{
                left: `calc(${x * 100}% - ${size / 2}px)`,
                bottom: `calc(${y * 100}% - ${size / 2}px)`,
                width: size, height: size,
              }} />
          )
        })}
        {/* оси */}
        <div className="absolute -bottom-0.5 left-0 right-0 text-xs text-muted-foreground text-center">
          исполнимость →
        </div>
        <div className="absolute left-0 top-1/2 -translate-y-1/2 -rotate-90 origin-center text-xs text-muted-foreground">
          привлекательность →
        </div>
      </div>
    </div>
  )
}
