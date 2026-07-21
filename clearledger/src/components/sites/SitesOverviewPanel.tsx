/**
 * Обзор пайплайна площадок (Банк ЗУ): распределение по стадиям, топ-регионы,
 * план ЭЗС/мощности + импорт сводного Excel. Стадии: проработка → работа → архив.
 */
import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, Upload, MapPin } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import { getSitesOverview, importSitesXlsx, STAGE_META, type SitesImportReport, type SiteStage } from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export function SitesOverviewPanel({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
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
      const r = await importSitesXlsx(companyId, pending, false)  // реальный импорт (REPLACE-ALL)
      setReport(r); setPending(null)
      await qc.invalidateQueries({ queryKey: ['sites-overview', companyId] })
      await qc.invalidateQueries({ queryKey: ['sites-list', companyId] })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка импорта')
    } finally { setBusy(false) }
  }

  const d = q.data
  const total = d?.total ?? 0
  const stageCount = (s: SiteStage) => d?.byStage.find((x) => x.stage === s)?.count ?? 0
  const maxRegion = Math.max(...(d?.byRegion ?? []).map((r) => r.count), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Банк ЗУ — пайплайн площадок</h2>
          <p className="text-xs text-muted-foreground">Места под установку ЭЗС на стадиях проработки → работы → архива. Не путать со складом оборудования.</p>
        </div>
        <div>
          <input ref={fileRef} type="file" accept=".xlsx,.xls" hidden onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
          <Button variant="outline" size="sm" className="h-8 text-xs" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
            Импорт «Банк данных ЗУ» (xlsx)
          </Button>
        </div>
      </div>

      {err && <div className="rounded-lg border border-red-400/50 bg-red-400/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">{err}</div>}
      {report && (
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs space-y-1">
          <div className="font-medium text-foreground">
            {report.dryRun ? 'Предпросмотр импорта (данные пока не записаны)' : 'Импорт выполнен ✓'} — строк: {nf0.format(report.total)}, с координатами: {nf0.format(report.withCoords)}
          </div>
          <div className="text-muted-foreground">
            {report.sheets.map((s) => `${s.sheet} → ${STAGE_META[s.stage as SiteStage]?.label ?? s.stage}: ${s.rows}`).join(' · ')}
            {report.unknownSheets.length > 0 && <span className="text-amber-600 dark:text-amber-400"> · нераспознанные листы: {report.unknownSheets.join(', ')}</span>}
          </div>
          {report.dryRun && pending && (
            <div className="pt-1 flex items-center gap-2">
              <Button size="sm" className="h-7 text-xs" disabled={busy} onClick={doImport}>Заменить данные и загрузить</Button>
              <span className="text-[11px] text-muted-foreground">Импорт заменит все площадки компании данными из файла.</span>
            </div>
          )}
        </div>
      )}

      {q.isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : total === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Данных нет. Загрузите сводный «Банк данных ЗУ» кнопкой выше.
        </CardContent></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Всего площадок" value={nf0.format(total)} hint={`${nf0.format(d!.withCoords)} с координатами`} />
            <KpiCard label="В проработке" value={nf0.format(stageCount('prospect'))} accent="info" hint="согласование / ТУ" />
            <KpiCard label="В работе" value={nf0.format(stageCount('in_work'))} accent="warning" hint="стройка / подключение" />
            <KpiCard label="В архиве" value={nf0.format(stageCount('archive'))} hint="отложены / отклонены" />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <KpiCard label="План ЭЗС к установке" value={nf0.format(d!.plannedEzs)} hint="суммарно по заполненным" />
            <KpiCard label="План мощности, кВт" value={nf0.format(d!.plannedPowerKwt)} hint="суммарно по заполненным" />
            <KpiCard label="Затраты на подключение" value={`${nf0.format(d!.connectionCostSum)} ₽`} hint={`по ${nf0.format(d!.withKnownCost)} площадкам с ценой`} />
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Распределение по стадиям</div>
              <div className="p-3 space-y-2">
                {d!.byStage.map((s) => (
                  <div key={s.stage} className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 text-xs w-28 shrink-0`}>
                      <span className={`h-2 w-2 rounded-full ${STAGE_META[s.stage].dot}`} />{s.label}
                    </span>
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div className={`h-full ${STAGE_META[s.stage].dot}`} style={{ width: `${total ? s.count / total * 100 : 0}%` }} />
                    </div>
                    <span className="font-mono text-xs text-muted-foreground w-24 text-right">{nf0.format(s.count)} ({total ? (s.count / total * 100).toFixed(0) : 0}%)</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40 flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />Топ-регионы по числу площадок
              </div>
              <div className="p-3 space-y-1.5">
                {d!.byRegion.map((r) => (
                  <div key={r.region} className="flex items-center gap-2">
                    <span className="text-xs w-48 shrink-0 truncate" title={r.region}>{r.region}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary/60" style={{ width: `${r.count / maxRegion * 100}%` }} />
                    </div>
                    <span className="font-mono text-xs text-muted-foreground w-10 text-right">{nf0.format(r.count)}</span>
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
