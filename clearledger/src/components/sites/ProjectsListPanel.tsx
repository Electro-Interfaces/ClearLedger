/**
 * «Проекты» — реестр проектов с номером, этапом и ведением.
 *
 * Отличие от «Банка площадок»: там воронка подбора (где строить), здесь —
 * ход стройки (как доводим до станции). Поэтому первым столбцом номер проекта,
 * а фильтр — по этапу, а не по стадии подбора.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Search, X, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { ExportButton } from './ExportButton'
import {
  getSites, getPortfolio, getSiteMembers, getSitesOverview, bulkAssignOwner,
  PHASE_META, STAGE_META, FUNNEL_STAGES, type SiteStage, type SiteRow,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { useOpenProject } from './useOpenProject'
import { NewProjectDialog } from './NewProjectDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE = 100
const today = () => new Date().toISOString().slice(0, 10)

/**
 * Доска по стадиям — «где скопилось» вместо «что с проектом».
 *
 * Колонка = стадия воронки, карточка = проект. Перетаскивания нет намеренно:
 * переход между стадиями держит гейт с обязательными пунктами, и таскание
 * карточки мышью его бы обошло. Клик открывает проект, где переход делается
 * с проверкой.
 */
function StageBoard({ rows, onOpen }: { rows: SiteRow[]; onOpen: (id: string) => void }) {
  const byStage = useMemo(() => {
    const m = new Map<string, SiteRow[]>()
    for (const r of rows) {
      const list = m.get(r.stage) ?? []
      list.push(r)
      m.set(r.stage, list)
    }
    return m
  }, [rows])
  const stages = FUNNEL_STAGES.filter((s) => (byStage.get(s)?.length ?? 0) > 0)

  if (stages.length === 0) {
    return (
      <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
        Проектов не найдено
      </CardContent></Card>
    )
  }
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {stages.map((st) => {
        const list = byStage.get(st) ?? []
        return (
          <div key={st} className="min-w-[240px] max-w-[280px] flex-1 rounded-lg border border-border bg-muted/20">
            <div className="px-2.5 py-1.5 border-b flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium">
                <span className={`h-2 w-2 rounded-full ${STAGE_META[st]?.dot ?? 'bg-zinc-400'}`} />
                {STAGE_META[st]?.label ?? st}
              </span>
              <span className="font-mono text-xs text-muted-foreground">{list.length}</span>
            </div>
            <div className="p-1.5 space-y-1.5 max-h-[70vh] overflow-y-auto">
              {list.slice(0, 50).map((s) => {
                const late = !!s.nextActionDue && s.nextActionDue < today()
                return (
                  <button key={s.id} type="button" onClick={() => onOpen(s.id)}
                    className="w-full text-left rounded-md border border-border bg-background px-2 py-1.5 hover:border-primary/50 transition-colors">
                    <div className="flex items-center justify-between gap-1">
                      <span className="font-mono text-xs text-muted-foreground">{s.projectNo ?? '—'}</span>
                      {late && <span className="text-xs text-red-600 dark:text-red-400">просрочен шаг</span>}
                    </div>
                    <div className="text-sm truncate" title={s.fullAddress ?? s.address ?? ''}>
                      {s.title || s.address || s.installPlace || s.city || '—'}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {s.city ?? s.region ?? ''}{s.ownerName ? ` · ${s.ownerName}` : ' · без ответственного'}
                    </div>
                  </button>
                )
              })}
              {list.length > 50 && (
                <div className="px-1 py-1 text-xs text-muted-foreground">
                  показаны первые 50 из {list.length} — сузьте фильтр
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function ProjectsListPanel({ companyId }: { companyId: string }) {
  const [phase, setPhase] = useState('')
  const [ownerId, setOwnerId] = useState('')
  // Реестр «Площадок» схлопнут сюда (решение МАГа 28.07.2026): место и работа на
  // нём — одна сущность, два одинаковых списка только путали. Регион и показ
  // отклонённых пришли оттуда, без них реестр мест не заменить.
  const [region, setRegion] = useState('')
  const [closed, setClosed] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [assignTo, setAssignTo] = useState('')
  const [view, setView] = useState<'table' | 'board'>('table')
  const [overdue, setOverdue] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // Переход из обзора портфеля приносит фильтр риска в URL — реестр обязан его
  // применить, иначе пользователь увидит не тот список, по которому кликнул.
  const [params, setParams] = useSearchParams()
  const risk = params.get('risk') ?? ''
  // Из воронки приходят с конкретной стадией («Переговоры 183»): реестр обязан
  // её применить, иначе клик по цифре открывает не тот список.
  const stageFromUrl = params.get('stage') ?? ''
  const clearStage = () => setParams((prev) => {
    const next = new URLSearchParams(prev); next.delete('stage'); return next
  }, { replace: true })
  const clearRisk = () => setParams((prev) => {
    const next = new URLSearchParams(prev); next.delete('risk'); return next
  }, { replace: true })
  // Клик по строке открывает рабочий экран проекта; Alt+клик — быстрый просмотр.
  const openProject = useOpenProject()

  const pf = useQuery({ queryKey: ['pr-portfolio', companyId], queryFn: () => getPortfolio(companyId) })
  const members = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })

  // Фильтр по этапу разворачивается в набор стадий: бэкенд фильтрует по стадии,
  // а руководитель мыслит этапами.
  const stagesOfPhase = useMemo(() => {
    const p = pf.data?.phases.find((x) => x.key === phase)
    return p ? p.stages.map((s) => s.stage) : []
  }, [pf.data, phase])

  const q = useQuery({
    queryKey: ['pr-projects', companyId, phase, ownerId, region, closed, overdue, search, risk, stageFromUrl, page],
    queryFn: () => getSites({
      companyId,
      // «Отклонённые» — тоже проекты, просто закрытые с причиной: держим их за
      // фильтром, а не в отдельном разделе, иначе теряется история места.
      stage: closed ? 'archive'
        : stageFromUrl
        || (phase && stagesOfPhase.length === 1 ? stagesOfPhase[0] : (phase ? undefined : 'active')),
      region: region || undefined,
      ownerId: ownerId || undefined, overdue, search: search || undefined,
      risk: risk || undefined, page, pageSize: PAGE,
    }),
  })
  const regions = useQuery({
    queryKey: ['sites-overview', companyId],
    queryFn: () => getSitesOverview(companyId),
  })

  const rows = useMemo(() => {
    const items = q.data?.items ?? []
    if (!phase || stagesOfPhase.length <= 1) return items
    return items.filter((i) => (stagesOfPhase as string[]).includes(i.stage))
  }, [q.data, phase, stagesOfPhase])

  const total = q.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))
  const reset = () => setPage(1)
  const ownerless = rows.filter((r) => !r.ownerName).length

  const mAssign = useMutation({
    mutationFn: () => bulkAssignOwner(companyId, [...picked],
      assignTo === '__none__' ? null : assignTo),
    onSuccess: async (r) => {
      toast.success(`Назначено: ${r.assigned}`)
      setPicked(new Set()); setAssignTo('')
      await q.refetch()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось назначить'),
  })

  const [filtersOpen, setFiltersOpen] = useState(false)
  // Сколько фильтров сейчас сужают выдачу — чтобы свёрнутая панель не скрывала
  // того, что список показан не целиком.
  const activeFilters = [phase, region, ownerId, overdue ? '1' : '', closed ? '1' : '',
    risk, stageFromUrl].filter(Boolean).length

  return (
    <div className="p-4 space-y-3">
      {/* Телефон: сначала данные, настройки по требованию. На широком экране
          панель всегда развёрнута — там она ничего не заслоняет. */}
      <div className="sm:hidden flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); reset() }}
            placeholder="Номер, адрес" className="h-10 w-full pl-7 pr-7 text-sm" />
          {search && <button type="button" onClick={() => { setSearch(''); reset() }}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground"><X className="h-4 w-4" /></button>}
        </div>
        <Button size="sm" variant={filtersOpen ? 'default' : 'outline'} className="h-10 shrink-0"
          onClick={() => setFiltersOpen((v) => !v)}>
          Фильтры{activeFilters > 0 ? ` · ${activeFilters}` : ''}
        </Button>
      </div>

      <div className={`${filtersOpen ? 'flex' : 'hidden'} sm:flex flex-wrap items-center gap-2`}>
        <Select value={phase || '__all__'} onValueChange={(v) => { setPhase(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[210px] text-sm"><SelectValue placeholder="Все этапы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-sm">Все этапы ({nf0.format(pf.data?.active ?? 0)})</SelectItem>
            {(pf.data?.phases ?? []).filter((p) => p.key !== 'closed').map((p) => (
              <SelectItem key={p.key} value={p.key} className="text-sm">{p.label} ({p.count})</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={region || '__all__'} onValueChange={(v) => { setRegion(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[180px] text-sm"><SelectValue placeholder="Все регионы" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-sm">Все регионы</SelectItem>
            {(regions.data?.byRegion ?? []).map((r) => (
              <SelectItem key={r.region} value={r.region} className="text-sm">
                {r.region} ({nf0.format(r.count)})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={ownerId || '__all__'} onValueChange={(v) => { setOwnerId(v === '__all__' ? '' : v); reset() }}>
          <SelectTrigger className="h-8 w-[180px] text-sm"><SelectValue placeholder="Любой ответственный" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__" className="text-sm">Любой ответственный</SelectItem>
            {(members.data ?? []).map((m) => (
              <SelectItem key={m.id} value={m.id} className="text-sm">{m.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <button type="button" onClick={() => { setOverdue((v) => !v); reset() }}
          className={`px-2.5 py-1 text-sm rounded-md border transition-colors ${overdue ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Просрочено
        </button>

        <button type="button" onClick={() => { setClosed((v) => !v); reset() }}
          title="Проекты, закрытые с причиной: место рассмотрели и отказались"
          className={`px-2.5 py-1 text-sm rounded-md border transition-colors ${closed ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Отклонённые
        </button>

        {/* Два взгляда на один список: таблица отвечает «что с конкретным
            проектом», доска — «где скопилось». Фильтры общие, переключение их
            не сбрасывает. */}
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
          {([['table', 'Таблица'], ['board', 'Доска']] as const).map(([v, label]) => (
            <button key={v} type="button" onClick={() => setView(v)}
              className={`px-2 py-1 text-sm rounded-[5px] ${view === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
              {label}
            </button>
          ))}
        </div>

        <div className="relative hidden sm:block">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); reset() }}
            placeholder="Название, номер, адрес" className="h-8 w-[220px] pl-7 pr-7 text-sm" />
          {search && <button type="button" onClick={() => { setSearch(''); reset() }}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
        </div>
        <Button size="sm" variant="outline" className="h-8 text-sm" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" />Новый проект
        </Button>
        {/* Реестр тоже уходит на совещание — своей выгрузкой, а не пересказом. */}
        <ExportButton companyId={companyId} report="portfolio" fileName="projects_portfolio.xlsx" />
        {risk && (
          <button type="button" onClick={clearRisk}
            className="px-2.5 py-1 text-sm rounded-md border border-primary bg-primary/10 text-primary">
            фильтр из обзора ✕
          </button>
        )}
        {stageFromUrl && (
          <button type="button" onClick={clearStage}
            className="px-2.5 py-1 text-sm rounded-md border border-primary bg-primary/10 text-primary">
            {STAGE_META[stageFromUrl as SiteStage]?.label ?? stageFromUrl} ✕
          </button>
        )}
        <span className="text-xs text-muted-foreground ml-auto">
          {q.isLoading ? '…' : `${nf0.format(rows.length)} проектов`}
        </span>
      </div>

      {/* Раздача проектов пачкой: по одному триста карточек не назначить, и
          «кто ведёт» остаётся пустым, а с ним половина строк «что горит». */}
      {picked.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
          <span className="font-medium">Выбрано {picked.size}</span>
          <Select value={assignTo} onValueChange={setAssignTo}>
            <SelectTrigger className="h-8 w-[220px] text-sm"><SelectValue placeholder="Ответственный" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-sm">— снять ответственного</SelectItem>
              {(members.data ?? []).map((m) => (
                <SelectItem key={m.id} value={m.id} className="text-sm">{m.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" className="h-8 text-sm" disabled={!assignTo || mAssign.isPending}
            onClick={() => mAssign.mutate()}>
            {mAssign.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Назначить
          </Button>
          <button type="button" className="text-muted-foreground hover:text-foreground"
            onClick={() => setPicked(new Set())}>сбросить</button>
        </div>
      )}

      {/* Три колонки прочерков — не отчёт, а тишина: реестр молчит о том, что у
          проектов нет ни ведущего, ни следующего шага. Говорим числом и даём
          действие прямо здесь, вместо того чтобы менеджер листал строки. */}
      {!q.isLoading && ownerless > 0 && picked.size === 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm">
          <span>
            Без ответственного {nf0.format(ownerless)} из {nf0.format(rows.length)} на странице —
            колонки «Ответственный» и «Следующий шаг» у них пустые не по ошибке.
          </span>
          <button type="button" className="text-primary hover:underline"
            onClick={() => setPicked(new Set(rows.filter((r) => !r.ownerName).map((r) => r.id)))}>
            выбрать их и назначить
          </button>
        </div>
      )}

      {view === 'board' && !q.isLoading && (
        <StageBoard rows={rows} onOpen={openProject} />
      )}

      <Card className={view === 'board' ? 'hidden' : undefined}>
        <CardContent className="p-0 overflow-x-auto">
          {q.isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : q.isError ? (
            /* Отказ сети и пустой реестр — разные вещи. «Проектов не найдено» на
               обрыве связи заставляет искать пропавшие проекты, которых никто не терял. */
            <div className="py-10 text-center text-sm space-y-2">
              <div>Список не загрузился: {q.error instanceof Error ? q.error.message : 'нет связи с сервером'}</div>
              <Button size="sm" variant="outline" onClick={() => q.refetch()}>Повторить</Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              Ничего не найдено по заданным условиям — измените поиск или снимите фильтры.
            </div>
          ) : (
            <>
            {/* Телефон: строка-карточка. Всё, что нужно для выбора проекта, видно
                сразу — номер, место, стадия, ответственный и срок, без прокрутки вбок. */}
            <ul className="sm:hidden divide-y divide-border/40">
              {rows.map((s) => {
                const late = !!s.nextActionDue && s.nextActionDue < today()
                return (
                  <li key={s.id}>
                    <button type="button" onClick={() => openProject(s.id)}
                      className="w-full text-left px-3 py-3 active:bg-muted/40">
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-xs text-muted-foreground shrink-0">{s.projectNo ?? '—'}</span>
                        <span className={`text-[11px] rounded border px-1.5 py-0.5 shrink-0 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
                          {s.stageLabel}
                        </span>
                      </div>
                      <div className="mt-1 text-sm">
                        {s.title || s.address || s.installPlace || s.fullAddress || '—'}
                        <span className="text-muted-foreground"> · {s.city ?? s.region ?? ''}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                        <span>{s.ownerName ?? 'ответственный не назначен'}</span>
                        {s.nextAction && <span className="truncate max-w-[60%]">{s.nextAction}</span>}
                        {s.nextActionDue && (
                          <span className={late ? 'text-red-600 dark:text-red-400' : ''}>до {s.nextActionDue}</span>
                        )}
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
            <table className="hidden sm:table w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="w-8 p-2">
                    <input type="checkbox" className="cursor-pointer"
                      checked={picked.size > 0 && picked.size === rows.length}
                      onChange={(e) => setPicked(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())} />
                  </th>
                  <th className="text-left p-2 font-medium">Проект</th>
                  <th className="text-left p-2 font-medium">Объект</th>
                  <th className="text-left p-2 font-medium">Этап проекта</th>
                  <th className="text-left p-2 font-medium">Стадия</th>
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
                      onClick={(ev) => (ev.altKey ? setDetailId(s.id) : openProject(s.id))}>
                      <td className="p-2" onClick={(ev) => ev.stopPropagation()}>
                        <input type="checkbox" className="cursor-pointer" checked={picked.has(s.id)}
                          onChange={(e) => setPicked((prev) => {
                            const next = new Set(prev)
                            if (e.target.checked) next.add(s.id); else next.delete(s.id)
                            return next
                          })} />
                      </td>
                      <td className="p-2 whitespace-nowrap font-mono">{s.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[300px] truncate" title={s.fullAddress ?? s.address ?? ''}>
                        {s.title || s.address || s.installPlace || s.fullAddress || '—'}
                        <span className="text-muted-foreground"> · {s.city ?? s.region ?? ''}</span>
                      </td>
                      <td className="p-2">
                        {s.phase && (
                          <span className={`text-xs rounded border px-1.5 py-0.5 ${PHASE_META[s.phase]?.cls ?? ''}`}>
                            {s.phaseLabel ?? PHASE_META[s.phase]?.label}
                          </span>
                        )}
                      </td>
                      <td className="p-2">
                        <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
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
            </>
          )}
        </CardContent>
      </Card>

      {pages > 1 && !phase && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button variant="outline" size="sm" className="h-8 px-2" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
          <span className="text-muted-foreground">стр. {page} из {pages}</span>
          <Button variant="outline" size="sm" className="h-8 px-2" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
        </div>
      )}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
      {creating && (
        <NewProjectDialog companyId={companyId} onClose={() => setCreating(false)}
          onCreated={(id) => { setCreating(false); setDetailId(id) }} />
      )}
    </div>
  )
}
