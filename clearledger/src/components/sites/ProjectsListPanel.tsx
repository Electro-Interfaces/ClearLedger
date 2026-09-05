/**
 * «Проекты» — реестр проектов с номером, этапом и ведением.
 *
 * Отличие от «Банка площадок»: там воронка подбора (где строить), здесь —
 * ход стройки (как доводим до станции). Поэтому первым столбцом номер проекта,
 * а фильтр — по этапу, а не по стадии подбора.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTabParams } from '@/hooks/useTabParams'
import { useAuth } from '@/contexts/AuthContext'
import { ProjectsWorkspaceControls } from './ProjectsWorkspaceControls'
import { PROJECT_WORKSPACE_DEFAULTS, type ProjectWorkspacePreferences } from './projectWorkspacePreferences'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Search, X, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { ExportButton } from './ExportButton'
import {
  getSites, getRouteNodes, getPortfolio, getSiteMembers, getSitesOverview, bulkAssignOwner, getProjectKinds, projectObjectLabel,
  PHASE_META, STAGE_META, FUNNEL_STAGES, type SiteStage,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { useOpenProject } from './useOpenProject'
import { NewProjectDialog } from './NewProjectDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE = 100
/** Порция колонки доски: столько карточек стадии подтягивается за одну прокрутку. */
const COLUMN_PAGE = 50
const today = () => new Date().toISOString().slice(0, 10)

/** Отбор доски без стадии: стадию каждая колонка подставляет свою. */
type BoardFilters = Omit<Parameters<typeof getSites>[0], 'companyId' | 'stage' | 'page' | 'pageSize'>

/**
 * Колонка доски: своя стадия, свой запрос, свой скролл.
 *
 * Раньше доска раскладывала по колонкам одну страницу общего списка, и остаток
 * стадии человек добирал переключением страниц внизу — просьба сотрудников
 * РусГидро 31.08.2026 была ровно про это. Теперь колонка грузит свою стадию сама
 * и добирает следующую порцию по прокрутке, а счётчик в шапке показывает всю
 * стадию, а не сколько её попало на страницу.
 */
function StageColumn({ companyId, stage, filters, onOpen }: {
  companyId: string; stage: SiteStage; filters: BoardFilters; onOpen: (id: string) => void
}) {
  const q = useInfiniteQuery({
    queryKey: ['pr-board', companyId, stage, filters],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      getSites({ ...filters, companyId, stage, page: pageParam, pageSize: COLUMN_PAGE }),
    getNextPageParam: (last, all) => (all.length * COLUMN_PAGE < last.total ? all.length + 1 : undefined),
  })
  const total = q.data?.pages[0]?.total ?? 0
  const list = useMemo(() => q.data?.pages.flatMap((p) => p.items) ?? [], [q.data])
  // Пустая стадия колонки не занимает: воронка из девяти стадий иначе растянулась
  // бы вбок пустотой, ради которой доску пришлось бы листать вправо.
  if (!q.isLoading && !q.isError && total === 0) return null

  return (
    <div className="min-w-[240px] max-w-[280px] flex-1 rounded-lg border border-border bg-muted/20">
      <div className="px-2.5 py-1.5 border-b flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium">
          <span className={`h-2 w-2 rounded-full ${STAGE_META[stage]?.dot ?? 'bg-zinc-400'}`} />
          {STAGE_META[stage]?.label ?? stage}
        </span>
        <span className="font-mono text-xs text-muted-foreground">
          {q.isLoading ? '…' : nf0.format(total)}
        </span>
      </div>
      <div className="p-1.5 space-y-1.5 max-h-[70vh] overflow-y-auto"
        onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 240
              && q.hasNextPage && !q.isFetchingNextPage) void q.fetchNextPage()
        }}>
        {list.map((s) => {
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
        {(q.isLoading || q.isFetchingNextPage) && (
          <div className="flex justify-center py-3">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}
        {/* Обрыв связи и пустая стадия — разные вещи: молча схлопнуть колонку
            значит показать воронку без стадии, которой на самом деле полно. */}
        {q.isError && (
          <div className="px-1 py-2 text-xs space-y-1">
            <div className="text-muted-foreground">Стадия не загрузилась</div>
            <button type="button" className="text-primary hover:underline"
              onClick={() => void q.refetch()}>повторить</button>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Доска по стадиям — «где скопилось» вместо «что с проектом».
 *
 * Колонка = стадия воронки, карточка = проект. Перетаскивания нет намеренно:
 * переход между стадиями держит гейт с обязательными пунктами, и таскание
 * карточки мышью его бы обошло. Клик открывает проект, где переход делается
 * с проверкой.
 */
function StageBoard({ companyId, stages, filters, onOpen }: {
  companyId: string; stages: SiteStage[]; filters: BoardFilters; onOpen: (id: string) => void
}) {
  if (stages.length === 0) {
    return (
      <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
        Проектов не найдено
      </CardContent></Card>
    )
  }
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {stages.map((st) => (
        <StageColumn key={st} companyId={companyId} stage={st} filters={filters} onOpen={onOpen} />
      ))}
    </div>
  )
}

export function ProjectsListPanel({ companyId }: { companyId: string }) {
  const { user } = useAuth()
  const [workspace, patchWorkspace] = useTabParams(`pr_workspace_${user?.id ?? 'anonymous'}`, PROJECT_WORKSPACE_DEFAULTS)
  const { kind, placeKind, columns } = workspace
  const kinds = useQuery({ queryKey: ['pr-kinds', companyId], queryFn: () => getProjectKinds(companyId) })
  const kindLabel = (key?: string) => kinds.data?.kinds.find((item) => item.key === (key || 'new_build'))?.label ?? key ?? '—'
  // Отбор живёт в параметрах пункта, а не в useState: уход в проект размонтирует
  // реестр, и по «вернуться к списку» человек получал полный список со сброшенным
  // отбором — искать свой населённый пункт заново (замечание И. Ступина 10.08.2026).
  const [f, patch, setF] = useTabParams('pr_list', {
    phase: '', stage: '', node: '', ownerId: '', region: '', closed: false,
    overdue: false, search: '', view: 'table' as 'table' | 'board', page: 1,
  })
  const { phase, node, ownerId, region, closed, overdue, search, view, page } = f
  // Блок и этап взаимно исключают друг друга: выбрали этап — блок снимается.
  // Этап воронки и узел маршрута отвечают на разные вопросы («далеко ли до
  // станции» и «у кого сейчас работа»), но в одном списке выбирается одно: два
  // отбора разом дали бы пустую выдачу там, где человек ждёт пересечения.
  const setPhase = (v: string) => patch({ phase: v, stage: '', node: '', closed: false })
  const setStage = (v: string) => patch({ stage: v, phase: '', node: '', closed: false })
  const setNode = (v: string) => patch({ node: v, phase: '', stage: '', closed: false })
  const setOwnerId = (v: string) => patch({ ownerId: v })
  const setRegion = (v: string) => patch({ region: v })
  const setOverdue = (v: boolean) => patch({ overdue: v })
  const setSearch = (v: string) => patch({ search: v })
  const setView = (v: 'table' | 'board') => patch({ view: v })
  const setPage = (v: number | ((p: number) => number)) =>
    setF((c) => ({ ...c, page: typeof v === 'function' ? v(c.page) : v }))
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [assignTo, setAssignTo] = useState('')
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

  // Выбранная стадия: из URL (приход из воронки) либо из отбора реестра.
  const stagePick = stageFromUrl || f.stage

  // Колонки доски: выбранный отбор сужает набор стадий, по умолчанию — вся воронка.
  // Приостановленные и архив колонками не показываются, пока их не выбрали явно:
  // доска отвечает на вопрос «где скопилась работа», а не «что мы закрыли».
  const boardStages = useMemo<SiteStage[]>(() => {
    if (closed) return ['archive']
    if (stagePick) return [stagePick as SiteStage]
    if (phase && stagesOfPhase.length > 0) return stagesOfPhase as SiteStage[]
    return FUNNEL_STAGES
  }, [closed, stagePick, phase, stagesOfPhase])
  const boardFilters = useMemo(() => ({
    region: region || undefined, ownerId: ownerId || undefined, overdue,
    kind: kind || undefined, placeKind: placeKind || undefined,
    search: search || undefined, risk: risk || undefined, node: node || undefined,
  }), [region, ownerId, overdue, search, risk, node, kind, placeKind])

  const q = useQuery({
    queryKey: ['pr-projects', companyId, phase, stagePick, node, ownerId, region, closed, overdue, search, risk, page, kind, placeKind],
    queryFn: () => getSites({
      companyId,
      // «Отклонённые» — тоже проекты, просто закрытые с причиной: держим их за
      // фильтром, а не в отдельном разделе, иначе теряется история места.
      stage: closed ? 'archive'
        : stagePick
        || (phase && stagesOfPhase.length === 1 ? stagesOfPhase[0] : (phase ? undefined : 'active')),
      region: region || undefined,
      kind: kind || undefined, placeKind: placeKind || undefined,
      ownerId: ownerId || undefined, overdue, search: search || undefined,
      risk: risk || undefined, node: node || undefined, page, pageSize: PAGE,
    }),
  })
  const nodes = useQuery({
    queryKey: ['pr-nodes', companyId],
    queryFn: () => getRouteNodes(companyId),
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
  const changeWorkspace = (next: Partial<ProjectWorkspacePreferences>) => {
    patchWorkspace(next)
    if ('kind' in next || 'placeKind' in next) { reset(); setPicked(new Set()) }
  }
  // Сколько фильтров сейчас сужают выдачу — чтобы свёрнутая панель не скрывала
  // того, что список показан не целиком.
  const activeFilters = [phase, region, ownerId, overdue ? '1' : '', closed ? '1' : '',
    risk, stagePick, node, search, kind, placeKind].filter(Boolean).length

  return (
    <div className="p-4 space-y-3">
      <ProjectsWorkspaceControls value={workspace} onChange={changeWorkspace} kinds={kinds.data?.kinds ?? []} />
      <label className="inline-flex flex-wrap items-center gap-2 text-sm">Контроль работы
        <select className="h-9 max-w-full rounded-md border bg-background px-2" value={risk} onChange={(e) => { const value = e.target.value; setParams((prev) => { const next = new URLSearchParams(prev); if (value) next.set('risk', value); else next.delete('risk'); return next }, { replace: true }); reset() }}>
          <option value="">Все проекты</option><option value="no_next">Без следующего действия</option><option value="step_overdue">Просрочен следующий шаг</option><option value="external_wait">Ждём внешних</option><option value="contact_overdue">Просрочен контакт</option><option value="result_pending">Ожидается возврат результата</option><option value="no_owner">Без ответственного</option>
          {risk && !['no_next', 'step_overdue', 'external_wait', 'contact_overdue', 'result_pending', 'no_owner'].includes(risk) && <option value={risk}>Фильтр из обзора</option>}
        </select>
      </label>
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
        {/* Блок и его этапы в одном списке. Раньше выбирать можно было только блок
            («Подбор 272»), и по нему не видно, у кого проект в работе: на переговорах,
            в проработке или уже на пусконаладке (замечание И. Ступина 10.08.2026). */}
        <Select value={node ? `nd:${node}` : stagePick ? `st:${stagePick}` : phase ? `ph:${phase}` : '__all__'}
          onValueChange={(v) => {
            if (v === '__all__') { patch({ phase: '', stage: '', node: '', page: 1 }); clearStage(); return }
            if (v.startsWith('nd:')) setNode(v.slice(3))
            else if (v.startsWith('st:')) setStage(v.slice(3))
            else setPhase(v.slice(3))
            clearStage()
            reset()
          }}>
          <SelectTrigger className="h-8 w-[260px] text-sm"><SelectValue placeholder="Все этапы" /></SelectTrigger>
          <SelectContent className="max-h-[420px]">
            <SelectItem value="__all__" className="text-sm">Все этапы ({nf0.format(pf.data?.active ?? 0)})</SelectItem>
            {(pf.data?.phases ?? []).filter((p) => p.key !== 'closed').map((p) => (
              <SelectGroup key={p.key}>
                <SelectItem value={`ph:${p.key}`} className="text-sm font-medium">
                  {p.label} ({p.count})
                </SelectItem>
                {p.stages.map((s) => (
                  <SelectItem key={s.stage} value={`st:${s.stage}`}
                    className="text-sm pl-8 text-muted-foreground">
                    {s.label} ({s.count})
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
            <SelectGroup>
              <SelectItem value="st:on_hold" className="text-sm">
                Не трогать ({nf0.format(regions.data?.onHold ?? 0)})
              </SelectItem>
            </SelectGroup>
            {/* Узел маршрута — второй способ спросить о том же списке: «у кого
                сейчас работа». По маршруту ведётся не всякий проект: пока по нему
                не сделали ни шага, узла у него нет вовсе — поэтому под группой
                стоит, сколько проектов маршрут вообще ведёт. */}
            {(nodes.data?.nodes ?? []).length > 0 && (
              <SelectGroup>
                <div className="mt-1 border-t px-2 pb-0.5 pt-1 text-xs uppercase tracking-wide text-muted-foreground">
                  узел маршрута
                </div>
                {(nodes.data?.nodes ?? []).map((n) => (
                  <SelectItem key={n.code} value={`nd:${n.code}`} className="text-sm">
                    {n.label} ({nf0.format(n.count)})
                  </SelectItem>
                ))}
                <div className="px-2 pb-1 pt-0.5 text-[11px] text-muted-foreground">
                  по маршруту ведутся {nf0.format(nodes.data?.known ?? 0)} из{' '}
                  {nf0.format(nodes.data?.active ?? 0)} проектов в работе
                </div>
              </SelectGroup>
            )}
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

        <button type="button" onClick={() => { setOverdue(!overdue); reset() }}
          className={`px-2.5 py-1 text-sm rounded-md border transition-colors ${overdue ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Просрочено
        </button>

        <button type="button" onClick={() => {
          patch({ stage: !closed && stagePick === 'on_hold' ? '' : 'on_hold', phase: '', closed: false, page: 1 })
          clearStage()
        }}
          title="Проекты, поставленные на паузу со статусом «Не трогать»"
          className={`px-2.5 py-1 text-sm rounded-md border transition-colors ${!closed && stagePick === 'on_hold' ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Не трогать
        </button>

        <button type="button" onClick={() => {
          patch({ closed: !closed, stage: '', phase: '', page: 1 })
          clearStage()
        }}
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
        {/* Счётчик считает весь отбор, а не текущую страницу: «100 проектов» при
            271 в выдаче читается как потеря данных. Исключение — фильтр по этапу
            из нескольких стадий: он досеивается на клиенте, и честно только видимое. */}
        <span className="text-xs text-muted-foreground ml-auto">
          {q.isLoading ? '…'
            : `${nf0.format(phase && stagesOfPhase.length > 1 ? rows.length : total)} проектов`}
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
      {view === 'table' && !q.isLoading && ownerless > 0 && picked.size === 0 && (
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

      {view === 'board' && (
        <StageBoard companyId={companyId} stages={boardStages} filters={boardFilters}
          onOpen={openProject} />
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
                        {columns.includes('stage') && <span className={`text-[11px] rounded border px-1.5 py-0.5 shrink-0 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
                          {s.stageLabel}
                        </span>}
                      </div>
                      <div className="mt-1 text-sm">
                        {s.title || s.address || s.installPlace || s.fullAddress || '—'}
                        <span className="text-muted-foreground"> · {s.city ?? s.region ?? ''}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                        {columns.includes('phase') && s.phaseLabel && <span>{s.phaseLabel}</span>}
                        {columns.includes('kind') && <span>{kindLabel(s.kind)}</span>}
                        {columns.includes('placeKind') && s.placeKind && <span>{projectObjectLabel(s.placeKind)}</span>}
                        {columns.includes('owner') && <span>{s.ownerName ?? 'ответственный не назначен'}</span>}
                        {columns.includes('nextAction') && s.nextAction && <span className="truncate max-w-[60%]">{s.nextAction}</span>}
                        {columns.includes('due') && s.nextActionDue && (
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
                  {columns.includes('kind') && <th className="text-left p-2 font-medium">Вид работ</th>}
                  {columns.includes('placeKind') && <th className="text-left p-2 font-medium">Тип объекта</th>}
                  {columns.includes('phase') && <th className="text-left p-2 font-medium">Этап проекта</th>}
                  {columns.includes('stage') && <th className="text-left p-2 font-medium">Стадия</th>}
                  {columns.includes('owner') && <th className="text-left p-2 font-medium">Ответственный</th>}
                  {columns.includes('nextAction') && <th className="text-left p-2 font-medium">Следующий шаг</th>}
                  {columns.includes('due') && <th className="text-left p-2 font-medium">Срок</th>}
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
                      {columns.includes('kind') && <td className="p-2">{kindLabel(s.kind)}</td>}
                      {columns.includes('placeKind') && <td className="p-2">{projectObjectLabel(s.placeKind)}</td>}
                      {columns.includes('phase') && <td className="p-2">
                        {s.phase && (
                          <span className={`text-xs rounded border px-1.5 py-0.5 ${PHASE_META[s.phase]?.cls ?? ''}`}>
                            {s.phaseLabel ?? PHASE_META[s.phase]?.label}
                          </span>
                        )}
                      </td>}
                      {columns.includes('stage') && <td className="p-2">
                        <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
                          {s.stageLabel}
                        </span>
                      </td>}
                      {columns.includes('owner') && <td className="p-2 whitespace-nowrap text-muted-foreground">{s.ownerName ?? '—'}</td>}
                      {columns.includes('nextAction') && <td className="p-2 max-w-[220px] truncate text-muted-foreground" title={s.nextAction ?? ''}>
                        {s.nextAction ?? '—'}
                      </td>}
                      {columns.includes('due') && <td className={`p-2 whitespace-nowrap font-mono ${late ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {s.nextActionDue ?? '—'}
                      </td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </>
          )}
        </CardContent>
      </Card>

      {/* Страницы — только у таблицы: на доске остаток стадии добирается прокруткой колонки. */}
      {view === 'table' && pages > 1 && !phase && (
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
