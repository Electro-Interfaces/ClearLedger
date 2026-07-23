/**
 * «Проекты» — реестр проектов с номером, этапом и ведением.
 *
 * Отличие от «Банка площадок»: там воронка подбора (где строить), здесь —
 * ход стройки (как доводим до станции). Поэтому первым столбцом номер проекта,
 * а фильтр — по этапу, а не по стадии подбора.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Search, X, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  getSites, getPortfolio, getSiteMembers, PHASE_META, STAGE_META,
  type SiteStage,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE = 100
const today = () => new Date().toISOString().slice(0, 10)

export function ProjectsListPanel({ companyId }: { companyId: string }) {
  const [phase, setPhase] = useState('')
  const [ownerId, setOwnerId] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [detailId, setDetailId] = useState<string | null>(null)

  const pf = useQuery({ queryKey: ['pr-portfolio', companyId], queryFn: () => getPortfolio(companyId) })
  const members = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })

  // Фильтр по этапу разворачивается в набор стадий: бэкенд фильтрует по стадии,
  // а руководитель мыслит этапами.
  const stagesOfPhase = useMemo(() => {
    const p = pf.data?.phases.find((x) => x.key === phase)
    return p ? p.stages.map((s) => s.stage) : []
  }, [pf.data, phase])

  const q = useQuery({
    queryKey: ['pr-projects', companyId, phase, ownerId, overdue, search, page],
    queryFn: () => getSites({
      companyId,
      stage: phase && stagesOfPhase.length === 1 ? stagesOfPhase[0] : (phase ? undefined : 'active'),
      ownerId: ownerId || undefined, overdue, search: search || undefined,
      page, pageSize: PAGE,
    }),
  })

  const rows = useMemo(() => {
    const items = q.data?.items ?? []
    if (!phase || stagesOfPhase.length <= 1) return items
    return items.filter((i) => (stagesOfPhase as string[]).includes(i.stage))
  }, [q.data, phase, stagesOfPhase])

  const total = q.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))
  const reset = () => setPage(1)

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={phase || '__all__'} onValueChange={(v) => { setPhase(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[210px] text-xs"><SelectValue placeholder="Все этапы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-xs">Все этапы ({nf0.format(pf.data?.active ?? 0)})</SelectItem>
            {(pf.data?.phases ?? []).filter((p) => p.key !== 'closed').map((p) => (
              <SelectItem key={p.key} value={p.key} className="text-xs">{p.label} ({p.count})</SelectItem>
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
          Просрочено
        </button>

        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); reset() }}
            placeholder="Адрес, город, собственник" className="h-8 w-[220px] pl-7 pr-7 text-xs" />
          {search && <button type="button" onClick={() => { setSearch(''); reset() }}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
        </div>
        <span className="text-[11px] text-muted-foreground ml-auto">
          {q.isLoading ? '…' : `${nf0.format(rows.length)} проектов`}
        </span>
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {q.isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">Проектов не найдено</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Проект</th>
                  <th className="text-left p-2 font-medium">Объект</th>
                  <th className="text-left p-2 font-medium">Этап</th>
                  <th className="text-left p-2 font-medium">Статус</th>
                  <th className="text-left p-2 font-medium">Ответственный</th>
                  <th className="text-left p-2 font-medium">Следующий шаг</th>
                  <th className="text-left p-2 font-medium">Срок</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const late = !!s.nextActionDue && s.nextActionDue < today()
                  return (
                    <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                      onClick={() => setDetailId(s.id)}>
                      <td className="p-2 whitespace-nowrap font-mono">{s.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[300px] truncate" title={s.fullAddress ?? s.address ?? ''}>
                        {s.title || s.address || s.installPlace || s.fullAddress || '—'}
                        <span className="text-muted-foreground"> · {s.city ?? s.region ?? ''}</span>
                      </td>
                      <td className="p-2">
                        {s.phase && (
                          <span className={`text-[11px] rounded border px-1.5 py-0.5 ${PHASE_META[s.phase]?.cls ?? ''}`}>
                            {s.phaseLabel ?? PHASE_META[s.phase]?.label}
                          </span>
                        )}
                      </td>
                      <td className="p-2">
                        <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
                          {s.stageLabel}
                        </span>
                      </td>
                      <td className="p-2 whitespace-nowrap text-muted-foreground">{s.ownerName ?? '—'}</td>
                      <td className="p-2 max-w-[220px] truncate text-muted-foreground" title={s.nextAction ?? ''}>
                        {s.nextAction ?? '—'}
                      </td>
                      <td className={`p-2 whitespace-nowrap font-mono ${late ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {s.nextActionDue ?? '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {pages > 1 && !phase && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button variant="outline" size="sm" className="h-7 px-2" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
          <span className="text-muted-foreground">стр. {page} из {pages}</span>
          <Button variant="outline" size="sm" className="h-7 px-2" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
        </div>
      )}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}
