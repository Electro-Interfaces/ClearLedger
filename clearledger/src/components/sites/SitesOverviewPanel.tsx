/**
 * Обзор пайплайна площадок (Банк ЗУ): воронка подбора с гейтами, регионы,
 * качество данных + импорт сводного Excel.
 *
 * Воронка идёт слева направо в порядке гейтов (лид → … → введена): раньше
 * лист «Согласованные» (договор на подписи) стоял первым как «в проработке»,
 * и картина читалась наоборот. Импорт — UPSERT, поэтому отчёт показывает не
 * «сколько строк», а что именно изменилось в банке.
 */
import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, Upload, MapPin, AlertTriangle } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import { ProjectPhaseStrip } from './ProjectPhaseStrip'
import { sitesModeForKey } from '@/config/workspaceMenus'
import {
  getSitesOverview, getSitesGaps, importSitesXlsx, STAGE_META,
  type SitesImportReport, type SiteStage,
} from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const pct = (n: number, total: number) => (total ? `${Math.round((n / total) * 100)}%` : '0%')

// Куда ведёт клик по этапу на ленте: у каждого этапа свой рабочий экран.
const PHASE_TAB: Record<string, string> = {
  select: 'sites_overview', land: 'pr_project', build: 'pr_tp', operate: 'pr_project',
}

export function SitesOverviewPanel({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [, setParams] = useSearchParams()
  // Клик по стадии = открыть банк площадок с этим фильтром. Стадия едет в URL,
  // чтобы ссылку можно было отправить коллеге, а не пересказывать словами.
  const goSub = (sub: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('mode', sitesModeForKey(sub))
      next.set('sub', sub)
      return next
    })
  }
  const goStage = (stage: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('mode', 'projects')      // работу ведут в разделе «Работа»
      next.set('sub', 'pr_project')
      next.set('stage', stage)
      return next
    })
  }
  const q = useQuery({
    queryKey: ['sites-overview', companyId],
    queryFn: () => getSitesOverview(companyId),
  })
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<SitesImportReport | null>(null)
  const [pending, setPending] = useState<File | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const onPick = async (f: File | null) => {
    if (!f) return
    setErr(null); setBusy(true); setReport(null); setPending(null)
    try {
      const r = await importSitesXlsx(companyId, f, true)  // dry-run
      setReport(r); setPending(f)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка чтения файла')
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const doImport = async () => {
    if (!pending) return
    setBusy(true); setErr(null)
    try {
      const r = await importSitesXlsx(companyId, pending, false)
      setReport(r); setPending(null)
      await qc.invalidateQueries({ queryKey: ['sites-overview', companyId] })
      await qc.invalidateQueries({ queryKey: ['sites-list', companyId] })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка импорта')
    } finally { setBusy(false) }
  }

  const d = q.data
  const total = d?.total ?? 0
  const active = d?.active ?? 0
  const maxFunnel = Math.max(...(d?.funnel ?? []).map((s) => s.count), 1)
  const maxRegion = Math.max(...(d?.byRegion ?? []).map((r) => r.count), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Воронка</h2>
          <p className="text-sm text-muted-foreground">
            Первый этап проекта: от лида до решения строить. Дальше проект уходит в оформление
            земли и реализацию — весь путь виден в карточке проекта, вкладка «Схема».
          </p>
        </div>
        <div>
          <input ref={fileRef} type="file" accept=".xlsx,.xls" hidden onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
          <Button variant="outline" size="sm" className="h-8 text-sm" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
            Импорт «Банк данных ЗУ» (xlsx)
          </Button>
        </div>
      </div>

      {/* Клик по этапу — тоже переход через границу разделов: «Реализация» ведёт
          в присоединения, а они в «Работе». */}
      <ProjectPhaseStrip current="select" onPick={(ph) => goSub(PHASE_TAB[ph] ?? 'pr_project')}
        counts={d ? {
          select: d.funnel.filter((f) => ['lead', 'screening', 'negotiation', 'dd', 'decision'].includes(f.stage))
            .reduce((a, f) => a + f.count, 0),
          land: d.funnel.find((f) => f.stage === 'contracting')?.count ?? 0,
          build: d.funnel.filter((f) => ['construction', 'commissioning'].includes(f.stage))
            .reduce((a, f) => a + f.count, 0),
          operate: d.funnel.find((f) => f.stage === 'live')?.count ?? 0,
        } : undefined}
        note="Это один и тот же путь проекта. Ниже — первый этап в деталях по стадиям." />

      {err && <div className="rounded-lg border border-red-400/50 bg-red-400/5 px-3 py-2 text-sm text-red-600 dark:text-red-400">{err}</div>}
      {report && <ImportReport report={report} pending={!!pending} busy={busy} onConfirm={doImport} />}

      {q.isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : total === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Данных нет. Загрузите сводный «Банк данных ЗУ» кнопкой выше.
        </CardContent></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="В работе" value={nf0.format(active)} accent="info"
              hint={`${pct(active, total)} банка · всего ${nf0.format(total)}`} />
            <KpiCard label="Оформление" value={nf0.format(stage(d, 'contracting'))} accent="warning"
              hint="договор / сервитут" />
            <KpiCard label="Введено в сеть" value={nf0.format(stage(d, 'live'))}
              hint="дошли до работающей ЭЗС" />
            <KpiCard label="Отклонено" value={nf0.format(d!.archived)}
              hint={`${pct(d!.archived, total)} банка`} />
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
Этап 1 «Подбор площадки» — стадии проекта по порядку гейтов
              </div>
              <div className="p-3 space-y-2">
                {/* Строка стадии — вход в работу, а не картинка: клик ведёт в банк
                    площадок с уже включённым фильтром. Раньше человек видел
                    «Переговоры 183» и не мог до них добраться. */}
                {d!.funnel.map((s) => (
                  <button key={s.stage} type="button"
                    onClick={() => goStage(s.stage)}
                    title={`Открыть банк площадок: ${s.label}`}
                    className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-muted/60">
                    <span className="inline-flex items-center gap-1.5 text-sm w-32 shrink-0">
                      <span className={`h-2 w-2 rounded-full ${STAGE_META[s.stage].dot}`} />{s.label}
                    </span>
                    <span className="text-xs text-muted-foreground w-44 shrink-0 truncate hidden md:block">{s.hint}</span>
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div className={`h-full ${STAGE_META[s.stage].dot}`} style={{ width: `${(s.count / maxFunnel) * 100}%` }} />
                    </div>
                    <span className="font-mono text-sm text-muted-foreground w-16 text-right">{nf0.format(s.count)}</span>
                  </button>
                ))}
                <div className="flex items-center gap-3 pt-1 border-t text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${STAGE_META.on_hold.dot}`} />Заморожено: {nf0.format(d!.onHold)}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${STAGE_META.archive.dot}`} />Архив: {nf0.format(d!.archived)}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <KpiCard label="План ЭЗС к установке" value={nf0.format(d!.plannedEzs)} hint="суммарно по заполненным" />
            <KpiCard label="План мощности, кВт" value={nf0.format(d!.plannedPowerKwt)} hint="суммарно по заполненным" />
            <KpiCard label="Затраты на подключение" value={`${nf0.format(d!.connectionCostSum)} ₽`}
              hint={`по ${nf0.format(d!.withKnownCost)} из ${nf0.format(total)} площадок`} />
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
                Управляемость активной части ({nf0.format(active)} площадок)
              </div>
              <div className="p-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <Risk label="Без ответственного" n={d!.work.noOwner} total={active} />
                <Risk label="Без следующего шага" n={d!.work.noNextAction} total={active} />
                <Risk label="Срок просрочен" n={d!.work.overdue} total={active} />
                <Risk label={`Без касания > ${d!.work.staleDays} дн`} n={d!.work.stale} total={active} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
                Чем заполнен банк
              </div>
              <div className="p-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <Fill label="Координаты" n={d!.quality.withCoords} total={total} />
                <Fill label="Регион по справочнику сети" n={d!.quality.regionMatched} total={total} />
                <Fill label="Кадастровый номер" n={d!.quality.withCadastral} total={total} />
                <Fill label="Стоимость подключения" n={d!.withKnownCost} total={total} />
              </div>
            </CardContent>
          </Card>

          <GapsCard companyId={companyId} />

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40 flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />Топ-регионы по числу площадок
              </div>
              <div className="p-3 space-y-1.5">
                {d!.byRegion.map((r) => (
                  <div key={r.region} className="flex items-center gap-2">
                    <span className="text-sm w-48 shrink-0 truncate" title={r.region}>{r.region}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary/60" style={{ width: `${(r.count / maxRegion) * 100}%` }} />
                    </div>
                    <span className="font-mono text-sm text-muted-foreground w-10 text-right">{nf0.format(r.count)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function stage(d: { funnel: { stage: SiteStage; count: number }[] } | undefined, s: SiteStage): number {
  return d?.funnel.find((x) => x.stage === s)?.count ?? 0
}

/**
 * Разрывы покрытия: где сеть работает без пайплайна (развитие остановилось),
 * где пайплайн без сети (заходим в новый регион) и где новая площадка встанет
 * вплотную к нашей же станции.
 */
function GapsCard({ companyId }: { companyId: string }) {
  const q = useQuery({ queryKey: ['sites-gaps', companyId], queryFn: () => getSitesGaps(companyId) })
  const d = q.data
  if (q.isLoading || !d) return null
  const noPipe = d.networkNoPipeline.slice(0, 8)
  const noNet = d.pipelineNoNetwork.slice(0, 8)
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-2 text-sm font-semibold text-muted-foreground border-b bg-muted/40">
          Разрывы покрытия — сеть и пайплайн не совпадают
        </div>
        <div className="p-3 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Сеть есть — площадок нет ({d.networkNoPipeline.length})
            </div>
            {noPipe.length === 0 ? <div className="text-muted-foreground">—</div> : noPipe.map((r) => (
              <div key={r.region} className="flex justify-between border-b border-border/20 py-0.5">
                <span className="truncate pr-2">{r.region}</span>
                <span className="font-mono text-muted-foreground">{r.stations} ст.</span>
              </div>
            ))}
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Площадки есть — сети нет ({d.pipelineNoNetwork.length})
            </div>
            {noNet.length === 0 ? <div className="text-muted-foreground">—</div> : noNet.map((r) => (
              <div key={r.region} className="flex justify-between border-b border-border/20 py-0.5">
                <span className="truncate pr-2">{r.region}</span>
                <span className="font-mono text-muted-foreground">{r.sites} пл.</span>
              </div>
            ))}
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Вплотную к своей станции ({d.cannibalization.length})
            </div>
            {d.cannibalization.length === 0 ? <div className="text-muted-foreground">—</div> : (
              <>
                {d.cannibalization.slice(0, 8).map((c) => (
                  <div key={c.id} className="flex justify-between border-b border-border/20 py-0.5">
                    <span className="truncate pr-2" title={`${c.region ?? ''} · ${c.address ?? ''}`}>
                      {c.city ?? c.region ?? '—'} · {c.stageLabel}
                    </span>
                    <span className="font-mono text-amber-600 dark:text-amber-400">{c.km} км</span>
                  </div>
                ))}
                <div className="text-xs text-muted-foreground mt-1">
                  Ближе {d.thresholds.cannibalKm * 1000} м — площадка скорее делит трафик, чем добавляет покрытие.
                </div>
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** Пробел в ведении: чем больше доля, тем тревожнее цвет (обратная шкала к Fill). */
function Risk({ label, n, total }: { label: string; n: number; total: number }) {
  const share = total ? n / total : 0
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">{nf0.format(n)} <span className="text-muted-foreground">({pct(n, total)})</span></span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${share >= 0.5 ? 'bg-red-400/60' : share >= 0.2 ? 'bg-amber-500/70' : 'bg-emerald-500/70'}`}
          style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  )
}

function Fill({ label, n, total }: { label: string; n: number; total: number }) {
  const share = total ? n / total : 0
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">{nf0.format(n)} <span className="text-muted-foreground">({pct(n, total)})</span></span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${share >= 0.8 ? 'bg-emerald-500/70' : share >= 0.4 ? 'bg-amber-500/70' : 'bg-red-400/60'}`}
          style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  )
}

/** Отчёт импорта: что изменится в банке и что в файле требует внимания. */
function ImportReport({ report, pending, busy, onConfirm }: {
  report: SitesImportReport; pending: boolean; busy: boolean; onConfirm: () => void
}) {
  const [details, setDetails] = useState(false)
  const warn = report.fileDuplicates.length + report.nearConflicts.length + report.skippedNoKey
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm space-y-2">
      <div className="font-medium text-foreground">
        {report.dryRun ? 'Предпросмотр импорта (данные пока не записаны)' : 'Импорт выполнен ✓'}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
        <span>новых площадок: <b className="text-foreground">{nf0.format(report.created)}</b></span>
        <span>дополнено: <b className="text-foreground">{nf0.format(report.updated)}</b></span>
        <span>без изменений: {nf0.format(report.unchanged)}</span>
        {report.stageMoved > 0 && <span>продвинулось по воронке: <b className="text-foreground">{report.stageMoved}</b></span>}
        {report.reactivated > 0 && <span>вернулось из архива: <b className="text-foreground">{report.reactivated}</b></span>}
        {report.archived > 0 && <span>ушло в архив: <b className="text-foreground">{report.archived}</b></span>}
      </div>
      <div className="text-muted-foreground">
        {report.sheets.map((s) => `${s.sheet} → ${STAGE_META[s.stage as SiteStage]?.label ?? s.stage}: ${s.rows}`).join(' · ')}
        {report.unknownSheets.length > 0 && (
          <span className="text-amber-600 dark:text-amber-400"> · нераспознанные листы: {report.unknownSheets.join(', ')}</span>
        )}
      </div>

      {warn > 0 && (
        <div className="rounded border border-amber-400/40 bg-amber-400/5 px-2 py-1.5 space-y-1">
          <button type="button" onClick={() => setDetails((v) => !v)}
            className="flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>Требует внимания: {warn}</span>
            <span className="text-muted-foreground">{details ? '▾' : '▸'}</span>
          </button>
          <div className="text-xs text-muted-foreground">
            {report.fileDuplicates.length > 0 && <div>дублей в файле (две строки на одну площадку): {report.fileDuplicates.length}</div>}
            {report.nearConflicts.length > 0 && <div>координаты в 50 м от другой площадки, но адрес иной: {report.nearConflicts.length}</div>}
            {report.skippedNoKey > 0 && <div>строк пропущено — нет ни адреса, ни координат, ни собственника: {report.skippedNoKey}</div>}
          </div>
          {details && (
            <div className="pt-1 space-y-1 max-h-56 overflow-y-auto">
              {report.fileDuplicates.slice(0, 30).map((x, i) => (
                <div key={`d${i}`} className="text-xs">
                  <span className="text-muted-foreground">[{x.sheet}:{x.row}]</span> {x.address || '—'}
                  <span className="text-muted-foreground"> ← совпала с «{x.first || '—'}»</span>
                </div>
              ))}
              {report.nearConflicts.slice(0, 30).map((x, i) => (
                <div key={`n${i}`} className="text-xs">
                  <span className="text-muted-foreground">[{x.sheet}:{x.row}]</span> {x.address || '—'}
                  <span className="text-muted-foreground"> ≈ 50 м от «{x.near || '—'}»</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {report.regionsUnmatched.length > 0 && (
        <div className="text-xs text-muted-foreground">
          Регионы вне справочника сети (там ещё нет наших станций):{' '}
          {report.regionsUnmatched.slice(0, 8).map((r) => `${r.value} (${r.count})`).join(', ')}
          {report.regionsUnmatched.length > 8 && ` и ещё ${report.regionsUnmatched.length - 8}`}
        </div>
      )}

      {report.dryRun && pending && (
        <div className="pt-1 flex items-center gap-2">
          <Button size="sm" className="h-8 text-sm" disabled={busy} onClick={onConfirm}>Загрузить в банк</Button>
          <span className="text-xs text-muted-foreground">
            Файл дополнит банк: известные площадки обновятся, ручные правки сохранятся.
          </span>
        </div>
      )}
    </div>
  )
}
