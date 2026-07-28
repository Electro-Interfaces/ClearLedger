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
import { ExportButton } from './ExportButton'
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
          <h2 className="text-base font-semibold">Приоритеты</h2>
          <p className="text-sm text-muted-foreground">
            Чем заняться в первую очередь на этапе подбора: привлекательность (спрос и покрытие)
            × исполнимость (мощность, деньги, право). Клик по строке открывает проект.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportButton companyId={companyId} report="matrix" fileName="priorities.xlsx" />
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
      </div>

      <ProjectPhaseStrip current="select"
        note="Приоритеты считаются для проектов на первом этапе — что двигать вперёд к земле и реализации." />

      {q.isLoading || !d ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {d.quadrants.map((qd) => (
              // Карточки компактные: вместе с полосой этапов они съедали высоту, и
              // карта решений уходила под сгиб — на неё же и приходят смотреть.
              <button key={qd.key} type="button" onClick={() => setQuadrant((v) => (v === qd.key ? '' : qd.key))}
                className={`text-left rounded-lg border px-3 py-2 transition-colors ${quadrant === qd.key ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'}`}>
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <span className={`h-2 w-2 rounded-full ${QUADRANT_META[qd.key].dot}`} />{qd.label}
                  <span className="ml-auto text-lg font-semibold tabular-nums">{nf0.format(qd.count)}</span>
                </div>
                <div className="text-xs text-muted-foreground leading-tight">{qd.hint}</div>
              </button>
            ))}
          </div>

          {/* Поле матрицы: ось X — исполнимость, ось Y — привлекательность */}
          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
                Карта решений — каждая точка это проект
              </div>
              <div className="p-4">
                <MatrixPlot items={(d.items ?? []).filter((i) => i.quadrant !== 'need_data')}
                  onPick={(id) => setDetailId(id)} />
                <div className="mt-2 text-xs text-muted-foreground">
                  На поле показаны только оценённые проекты
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
                <span>{quadrant ? QUADRANT_META[quadrant].label : 'Все проекты по приоритету'}</span>
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

/**
 * Поле «привлекательность × исполнимость» с квадрантами и точками-проектами.
 *
 * Было: высота в половину экрана (52% ширины), пустое поле с горсткой точек в
 * углу, ни сетки, ни шкал, подпись оси поперёк данных. Понять, 60 у точки или 80,
 * было нельзя — а именно это и решает, куда её относить.
 *
 * Стало: фиксированная высота 400 px, сетка по 25 с числами на осях, точки с
 * обводкой (на тёмной теме без неё они сливались с фоном), счётчик в каждом
 * квадранте и подпись осей за пределами поля.
 */
const AXIS_TICKS = [0, 25, 50, 75, 100]
// Высота поля: на ноутбуке (768 px) фиксированные 400 px уводили шкалу X и нижние
// квадранты под сгиб — приходилось скроллить, чтобы прочитать собственную карту.
const PLOT_H = 'min(340px, 38vh)' 

function MatrixPlot({ items, onPick }: { items: MatrixItem[]; onPick: (id: string) => void }) {
  // Разобранный кластер: какие проекты стоят в одной точке поля.
  const [openCluster, setOpenCluster] = useState<string | null>(null)

  // Баллы дискретны и часто совпадают: пять проектов с одинаковой оценкой рисуются
  // друг на друге, и кликнуть можно только в верхний. Собираем такие в один
  // кружок с числом — он раскрывается списком, из которого выбирают проект.
  const clusters = useMemo(() => {
    const map = new Map<string, { x: number; y: number; items: MatrixItem[] }>()
    for (const it of items) {
      const x = Math.min(98, Math.max(2, it.feasible ?? 0))
      const y = Math.min(98, Math.max(2, it.attract ?? 0))
      // Шаг сетки 3 балла: ближе этого точки визуально всё равно сливаются.
      const key = `${Math.round(x / 3)}:${Math.round(y / 3)}`
      const c = map.get(key)
      if (c) c.items.push(it)
      else map.set(key, { x, y, items: [it] })
    }
    return [...map.entries()].map(([key, c]) => ({ key, ...c }))
  }, [items])

  if (items.length === 0) {
    return <div className="py-10 text-center text-sm text-muted-foreground">
      Оценённых проектов нет — сначала нужно добрать данные (мощность, стоимость подключения, право).
    </div>
  }
  // Считаем по тому же признаку, что и карточки сверху (`item.quadrant` с сервера).
  const n = (k: Quadrant) => items.filter((i) => i.quadrant === k).length
  const quads: { key: Quadrant; pos: string; cls: string }[] = [
    { key: 'unblock', pos: 'left-2 top-2', cls: 'text-amber-600 dark:text-amber-400' },
    { key: 'do_now', pos: 'right-2 top-2 text-right', cls: 'text-emerald-600 dark:text-emerald-400' },
    { key: 'drop', pos: 'left-2 bottom-2', cls: 'text-red-600 dark:text-red-400' },
    { key: 'option', pos: 'right-2 bottom-2 text-right', cls: 'text-sky-600 dark:text-sky-400' },
  ]

  return (
    <div className="flex gap-2">
      {/* Шкала привлекательности слева: без чисел точку нельзя прочитать. */}
      <div className="relative w-7 shrink-0" style={{ height: PLOT_H }}>
        {AXIS_TICKS.map((t) => (
          <span key={t} className="absolute right-0 text-xs tabular-nums text-muted-foreground"
            style={{ bottom: `calc(${t}% - 0.5em)` }}>{t}</span>
        ))}
      </div>

      <div className="min-w-0 flex-1">
        <div className="relative w-full rounded-md border border-border bg-card" style={{ height: PLOT_H }}>
          {/* Поле нейтральное. Цветная заливка квадрантов давала грязные оттенки
              на тёмной теме и спорила с цветом точек: область теперь читается по
              подписи в углу и разделителям на 50, а цвет остаётся у данных. */}
          {AXIS_TICKS.slice(1, -1).map((t) => (
            <div key={`v${t}`} className={`absolute top-0 bottom-0 ${t === 50 ? 'border-l-2 border-border' : 'border-l border-border/25'}`}
              style={{ left: `${t}%` }} />
          ))}
          {AXIS_TICKS.slice(1, -1).map((t) => (
            <div key={`h${t}`} className={`absolute left-0 right-0 ${t === 50 ? 'border-t-2 border-border' : 'border-t border-border/25'}`}
              style={{ bottom: `${t}%` }} />
          ))}

          {quads.map((qd) => (
            <span key={qd.key}
              className={`absolute ${qd.pos} ${qd.cls} inline-flex items-center gap-1.5 rounded bg-background/80 px-1.5 py-0.5 text-xs`}>
              <span className={`h-2 w-2 rounded-full ${QUADRANT_META[qd.key].dot}`} />
              {QUADRANT_META[qd.key].label}
              <span className="tabular-nums opacity-70">· {n(qd.key)}</span>
            </span>
          ))}

          {/* Точка или кластер. Размер — уверенность оценки; обводка цветом фона,
              иначе на тёмной теме кружок сливается с полем. */}
          {clusters.map((c) => {
            const many = c.items.length > 1
            const it = c.items[0]
            const size = many ? 20 : 9 + (it.confidence / 100) * 6
            const active = openCluster === c.key
            // Список открывается вплотную к точке. Уводить его вниз под карту
            // нельзя: выбор уезжает за экран, и до него надо ещё доскроллить.
            // У края поля разворачиваем в другую сторону, иначе он обрежется.
            const toLeft = c.x > 62
            const toDown = c.y > 62
            return (
              <div key={c.key} className={`absolute ${active ? 'z-30' : ''}`}
                style={{ left: `${c.x}%`, bottom: `${c.y}%` }}>
                <button type="button"
                  onClick={() => (many ? setOpenCluster(active ? null : c.key) : onPick(it.id))}
                  title={many
                    ? `${c.items.length} проекта в одной точке — нажмите, чтобы выбрать`
                    : `${it.projectNo ?? ''} ${it.city ?? it.region ?? ''} — привлекательность ${it.attract}, исполнимость ${it.feasible}, уверенность ${it.confidence}%`}
                  className={`absolute flex items-center justify-center rounded-full ring-1 ring-background transition-transform hover:z-10 hover:scale-125
                    ${QUADRANT_META[it.quadrant].dot} ${active ? 'ring-2 ring-primary scale-110' : ''}`}
                  style={{ left: -size / 2, bottom: -size / 2, width: size, height: size }}>
                  {many && <span className="text-[11px] font-semibold text-white">{c.items.length}</span>}
                </button>

                {active && many && (
                  <div className="absolute w-[230px] rounded-md border border-primary/50 bg-popover p-2 shadow-lg"
                    style={{
                      [toLeft ? 'right' : 'left']: 14,
                      [toDown ? 'top' : 'bottom']: 14,
                    } as React.CSSProperties}>
                    <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>привл. {it.attract} · исполн. {it.feasible}</span>
                      <button type="button" className="ml-auto hover:text-foreground"
                        onClick={() => setOpenCluster(null)} aria-label="Закрыть">✕</button>
                    </div>
                    <div className="max-h-40 space-y-0.5 overflow-y-auto">
                      {c.items.map((p) => (
                        <button key={p.id} type="button" onClick={() => onPick(p.id)}
                          className="block w-full truncate rounded px-1.5 py-1 text-left text-xs hover:bg-muted">
                          <span className="font-mono">{p.projectNo ?? '—'}</span>
                          <span className="text-muted-foreground"> · {p.city ?? p.region ?? '—'}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Шкала исполнимости под полем — не поверх данных, как было. */}
        <div className="relative h-4">
          {AXIS_TICKS.map((t) => (
            <span key={t} className="absolute top-0 -translate-x-1/2 text-xs tabular-nums text-muted-foreground"
              style={{ left: `${t}%` }}>{t}</span>
          ))}
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>↑ привлекательность: спрос, покрытие, тип места</span>
          <span>исполнимость: мощность, деньги, право →</span>
        </div>

      </div>
    </div>
  )
}
