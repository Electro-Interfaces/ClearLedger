/**
 * Реестр площадок (Банк ЗУ) с фильтрами (стадия/регион/поиск) и карточкой.
 * Клик по строке → все исходные поля площадки (raw).
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2, Search, X, ExternalLink, ChevronLeft, ChevronRight } from 'lucide-react'
import { getSites, getSite, getSitesOverview, STAGE_META, type SiteStage } from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE = 200

const STAGE_TABS: { v: '' | SiteStage; label: string }[] = [
  { v: '', label: 'Все' },
  { v: 'prospect', label: 'В проработке' },
  { v: 'in_work', label: 'В работе' },
  { v: 'archive', label: 'В архиве' },
]

function StageBadge({ stage, label }: { stage: SiteStage; label: string }) {
  return <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[stage].cls}`}>{label}</span>
}

export function SitesListPanel({ companyId }: { companyId: string }) {
  const [stage, setStage] = useState<'' | SiteStage>('')
  const [region, setRegion] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [detailId, setDetailId] = useState<string | null>(null)

  const ov = useQuery({ queryKey: ['sites-overview', companyId], queryFn: () => getSitesOverview(companyId) })
  const q = useQuery({
    queryKey: ['sites-list', companyId, stage, region, search, page],
    queryFn: () => getSites({ companyId, stage: stage || undefined, region: region || undefined, search: search || undefined, page, pageSize: PAGE }),
  })
  const reset = () => setPage(1)

  const d = q.data
  const total = d?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))

  return (
    <div className="p-4 space-y-3">
      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
          {STAGE_TABS.map((t) => (
            <button key={t.v} type="button" onClick={() => { setStage(t.v); reset() }}
              className={`px-2.5 py-1 text-xs rounded-[5px] transition-colors ${stage === t.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{t.label}</button>
          ))}
        </div>
        <Select value={region || '__all__'} onValueChange={(v) => { setRegion(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue placeholder="Все регионы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-xs">Все регионы</SelectItem>
            {(ov.data?.byRegion ?? []).map((r) => (
              <SelectItem key={r.region} value={r.region} className="text-xs">{r.region} ({r.count})</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); reset() }} placeholder="Адрес, город, собственник"
            className="h-8 w-[230px] pl-7 pr-7 text-xs" />
          {search && <button type="button" onClick={() => { setSearch(''); reset() }} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
        </div>
        <span className="text-[11px] text-muted-foreground ml-auto">{q.isLoading ? '…' : `${nf0.format(total)} площадок`}</span>
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {q.isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : total === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">Ничего не найдено</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Регион</th>
                  <th className="text-left p-2 font-medium">Город</th>
                  <th className="text-left p-2 font-medium">Адрес / место</th>
                  <th className="text-left p-2 font-medium">Стадия</th>
                  <th className="text-left p-2 font-medium">Собственник</th>
                  <th className="text-right p-2 font-medium">ЭЗС</th>
                  <th className="text-right p-2 font-medium">Мощн.</th>
                  <th className="text-left p-2 font-medium">Статус ТУ</th>
                </tr>
              </thead>
              <tbody>
                {d!.items.map((s) => (
                  <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer" onClick={() => setDetailId(s.id)}>
                    <td className="p-2 whitespace-nowrap">{s.region ?? '—'}</td>
                    <td className="p-2 whitespace-nowrap">{s.city ?? '—'}</td>
                    <td className="p-2 max-w-[280px] truncate" title={s.fullAddress ?? s.address ?? s.installPlace ?? ''}>{s.address ?? s.installPlace ?? s.fullAddress ?? '—'}</td>
                    <td className="p-2"><StageBadge stage={s.stage} label={s.stageLabel} /></td>
                    <td className="p-2 max-w-[180px] truncate text-muted-foreground" title={s.owner ?? ''}>{s.owner ?? '—'}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{s.plannedEzsCount ?? ''}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{s.plannedPowerKwt ?? ''}</td>
                    <td className="p-2 max-w-[200px] truncate text-muted-foreground" title={s.tuStatus ?? ''}>{s.tuStatus ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button variant="outline" size="sm" className="h-7 px-2" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
          <span className="text-muted-foreground">стр. {page} из {pages}</span>
          <Button variant="outline" size="sm" className="h-7 px-2" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
        </div>
      )}

      {detailId && <SiteDetailModal companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-xs break-words">{value}</div>
    </div>
  )
}

function SiteDetailModal({ companyId, id, onClose }: { companyId: string; id: string; onClose: () => void }) {
  const [showRaw, setShowRaw] = useState(false)
  const q = useQuery({ queryKey: ['site-detail', companyId, id], queryFn: () => getSite(companyId, id) })
  const s = q.data
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-3xl w-[94vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base pr-6 flex flex-wrap items-center gap-2">
            {s ? (s.fullAddress || [s.region, s.city].filter(Boolean).join(', ') || 'Площадка') : 'Площадка'}
            {s && <StageBadge stage={s.stage} label={s.stageLabel} />}
          </DialogTitle>
        </DialogHeader>
        {q.isLoading || !s ? (
          <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <Field label="Регион" value={s.region} />
              <Field label="Город" value={s.city} />
              <Field label="Признак" value={s.placeKind} />
              <Field label="Место установки" value={s.installPlace} />
              <Field label="Трасса" value={s.route} />
              <Field label="Собственник" value={s.owner} />
              <Field label="Бренд" value={s.brand} />
              <Field label="Площадь, м²" value={s.areaM2} />
              <Field label="Владение" value={s.ownership} />
              <Field label="Свободная мощность" value={s.freePowerKwt} />
              <Field label="План ЭЗС" value={s.plannedEzsCount} />
              <Field label="План мощности, кВт" value={s.plannedPowerKwt} />
              <Field label="Порты" value={[s.portsGbt && `GBT ${s.portsGbt}`, s.portsCcs && `CCS ${s.portsCcs}`, s.portsChademo && `Chademo ${s.portsChademo}`, s.portsType && `Type ${s.portsType}`].filter(Boolean).join(' · ') || null} />
              <Field label="Поставщик" value={s.supplier} />
              <Field label="Подрядчик" value={s.contractor} />
              <Field label="Тип техприсоединения" value={s.techConnType} />
              <Field label="Дата поступления" value={s.receivedDate} />
              <Field label="Затраты на подключение, ₽" value={s.connectionCost != null ? nf0.format(s.connectionCost) : null} />
              <Field label="Аренда, ₽/мес" value={s.rentCostMonth != null ? nf0.format(s.rentCostMonth) : null} />
              <Field label="Доп.сервис" value={s.dopService} />
            </div>
            {(s.tuStatus || s.comment) && (
              <div className="space-y-2">
                {s.tuStatus && <Field label="Статус согласования / ТУ" value={s.tuStatus} />}
                {s.comment && <Field label="Комментарий" value={s.comment} />}
              </div>
            )}
            {(s.lat != null || s.mapUrl) && (
              <div className="flex items-center gap-3 text-xs">
                {s.lat != null && <span className="font-mono text-muted-foreground">{s.lat}, {s.lon}</span>}
                {s.mapUrl && <a href={s.mapUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">Карта <ExternalLink className="h-3 w-3" /></a>}
              </div>
            )}
            <div className="border-t pt-2">
              <button type="button" onClick={() => setShowRaw((v) => !v)} className="text-xs text-muted-foreground hover:text-foreground">
                {showRaw ? '▾' : '▸'} Все поля из файла ({Object.keys(s.raw || {}).length})
              </button>
              {showRaw && (
                <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1">
                  {Object.entries(s.raw || {}).map(([k, v]) => (
                    <div key={k} className="flex gap-2 text-[11px] border-b border-border/20 py-0.5">
                      <span className="text-muted-foreground shrink-0 max-w-[45%] truncate" title={k}>{k}</span>
                      <span className="break-words">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
