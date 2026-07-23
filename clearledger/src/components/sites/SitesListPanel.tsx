/**
 * Реестр площадок (Банк ЗУ): фильтры (стадия/регион/ответственный/просрочка/поиск),
 * колонки ведения и переход в рабочую карточку.
 *
 * Столбцы «Ответственный» и «Следующий шаг» — не украшение: без них список
 * отвечает на вопрос «что у нас есть», но не на «что делать и кому».
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Search, X, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import {
  getSites, getSitesOverview, getSiteMembers,
  STAGE_META, FUNNEL_STAGES, type SiteStage,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { useOpenProject } from './useOpenProject'
import { NewProjectDialog } from './NewProjectDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE = 200
const today = () => new Date().toISOString().slice(0, 10)

function StageBadge({ stage, label }: { stage: SiteStage; label: string }) {
  const meta = STAGE_META[stage]
  return (
    <span className={`text-[11px] rounded border px-1.5 py-0.5 ${meta?.cls ?? ''}`} title={meta?.hint}>
      {label}
    </span>
  )
}

export function SitesListPanel({ companyId }: { companyId: string }) {
  const [stage, setStage] = useState<'' | SiteStage | 'active'>('')
  const [region, setRegion] = useState('')
  const [ownerId, setOwnerId] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [detailId, setDetailId] = useState<string | null>(null)
  // Клик — рабочий экран проекта, Alt+клик — быстрый просмотр.
  const openProject = useOpenProject()
  const [creating, setCreating] = useState(false)

  const ov = useQuery({ queryKey: ['sites-overview', companyId], queryFn: () => getSitesOverview(companyId) })
  const members = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })
  const stageCount = (s: SiteStage) => ov.data?.funnel.find((x) => x.stage === s)?.count ?? 0
  const q = useQuery({
    queryKey: ['sites-list', companyId, stage, region, ownerId, overdue, search, page],
    queryFn: () => getSites({
      companyId, stage: stage || undefined, region: region || undefined,
      ownerId: ownerId || undefined, overdue, search: search || undefined,
      page, pageSize: PAGE,
    }),
  })
  const reset = () => setPage(1)

  const d = q.data
  const total = d?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-base font-semibold">Банк площадок</h2>
        <p className="text-xs text-muted-foreground">
          Первый этап проекта — где строить. Каждая площадка это проект на ранней стадии:
          клик открывает его рабочий экран, Alt+клик — быстрый просмотр.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {/* Стадий десять — таблице хватает селекта; счётчики берём из обзора,
            чтобы не гадать, где сейчас работа. */}
        <Select value={stage || '__all__'} onValueChange={(v) => { setStage(v === '__all__' ? '' : v as SiteStage | 'active'); reset() }}>
          <SelectTrigger className="h-8 w-[210px] text-xs"><SelectValue placeholder="Все стадии" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-xs">Все стадии ({nf0.format(ov.data?.total ?? 0)})</SelectItem>
            <SelectItem value="active" className="text-xs">В работе — активные ({nf0.format(ov.data?.active ?? 0)})</SelectItem>
            {FUNNEL_STAGES.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">
                {STAGE_META[s].label} ({nf0.format(stageCount(s))})
              </SelectItem>
            ))}
            <SelectItem value="on_hold" className="text-xs">{STAGE_META.on_hold.label} ({nf0.format(ov.data?.onHold ?? 0)})</SelectItem>
            <SelectItem value="archive" className="text-xs">{STAGE_META.archive.label} ({nf0.format(ov.data?.archived ?? 0)})</SelectItem>
          </SelectContent>
        </Select>

        <Select value={region || '__all__'} onValueChange={(v) => { setRegion(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue placeholder="Все регионы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-xs">Все регионы</SelectItem>
            {(ov.data?.byRegion ?? []).map((r) => (
              <SelectItem key={r.region} value={r.region} className="text-xs">{r.region} ({r.count})</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={ownerId || '__all__'} onValueChange={(v) => { setOwnerId(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue placeholder="Любой ответственный" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-xs">Любой ответственный</SelectItem>
            {(members.data ?? []).map((m) => (
              <SelectItem key={m.id} value={m.id} className="text-xs">{m.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <button type="button" onClick={() => { setOverdue((v) => !v); reset() }}
          className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${overdue ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Просрочено{ov.data?.work ? ` (${ov.data.work.overdue})` : ''}
        </button>

        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); reset() }} placeholder="Адрес, город, собственник"
            className="h-8 w-[220px] pl-7 pr-7 text-xs" />
          {search && <button type="button" onClick={() => { setSearch(''); reset() }} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
        </div>

        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" />Новый проект
        </Button>
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
                  <th className="text-left p-2 font-medium">Ответственный</th>
                  <th className="text-left p-2 font-medium">Следующий шаг</th>
                  <th className="text-left p-2 font-medium">Срок</th>
                  <th className="text-left p-2 font-medium">Собственник</th>
                </tr>
              </thead>
              <tbody>
                {d!.items.map((s) => {
                  const late = !!s.nextActionDue && s.nextActionDue < today() && s.stage !== 'archive'
                  return (
                    <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer" onClick={(ev) => (ev.altKey ? setDetailId(s.id) : openProject(s.id))}>
                      <td className="p-2 whitespace-nowrap">{s.region ?? '—'}</td>
                      <td className="p-2 whitespace-nowrap">{s.city ?? '—'}</td>
                      <td className="p-2 max-w-[260px] truncate" title={s.fullAddress ?? s.address ?? s.installPlace ?? ''}>
                        {s.address ?? s.installPlace ?? s.fullAddress ?? '—'}
                      </td>
                      <td className="p-2"><StageBadge stage={s.stage} label={s.stageLabel} /></td>
                      <td className="p-2 whitespace-nowrap text-muted-foreground">{s.ownerName ?? '—'}</td>
                      <td className="p-2 max-w-[220px] truncate text-muted-foreground" title={s.nextAction ?? ''}>{s.nextAction ?? '—'}</td>
                      <td className={`p-2 whitespace-nowrap font-mono ${late ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {s.nextActionDue ?? '—'}
                      </td>
                      <td className="p-2 max-w-[160px] truncate text-muted-foreground" title={s.owner ?? ''}>{s.owner ?? '—'}</td>
                    </tr>
                  )
                })}
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

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
      {creating && <NewProjectDialog companyId={companyId} onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); setDetailId(id) }} />}
    </div>
  )
}
