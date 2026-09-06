/**
 * «Трек» в карточке проекта: документооборот и поручения по этой площадке.
 *
 * Связь между проектом и «Треком» была односторонней и невидимой. Маршрут умел
 * попросить завести документ, собрать визы, поручить работу — и исход двигал
 * проект. Но человек, открывший карточку, ничего этого не видел: вкладка
 * «Документы» показывает файлы, приложенные к площадке (ЕГРН, ТУ, договор), а
 * не то, что по ней идёт. Вопрос «на чём стоим» задавали голосом.
 *
 * Здесь обе стороны сходятся. Лента — документы и поручения вместе: разделять
 * их значило бы заставить читать два списка и складывать в уме. Кнопка
 * «Завести» ставит работу отсюда же, сразу с привязкой к проекту, — иначе
 * заведённое в общем «Треке» в эту ленту уже не попадёт.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ClipboardList, ExternalLink, FileText, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ProjectWorkActions } from './ProjectWorkActions'
import { WorkOriginLink } from '@/components/work/WorkOriginLink'
import { retryProjectResult, setProjectNext } from '@/services/projectWorkspaceService'
import { resolveWorkContext } from '@/services/workContextService'
import * as docsService from '@/services/docsService'
import { getSiteTrack, type SiteDetail, type SiteTrackItem } from '@/services/sitesService'

/** Тон колонки общей оси: слева заведённое, справа завершённое. */
const STATE_TONE: Record<string, string> = {
  new: 'bg-muted text-muted-foreground',
  in_work: 'bg-blue-500/10 text-blue-700 dark:text-blue-300',
  approval: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  external: 'bg-purple-500/10 text-purple-700 dark:text-purple-300',
  done: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
}

export function ProjectTrackTab({ site, companyId }: {
  site: SiteDetail; companyId: string
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [scope, setScope] = useState(() => params.get('workScope') === 'pending' ? 'pending' : 'all')
  const [offset, setOffset] = useState(0)
  const [common, setCommon] = useState(false)
  const [starting, setStarting] = useState<string | null>(null)
  const context = useQuery({ queryKey: ['work-context', companyId, `site:${site.id}`], queryFn: () => resolveWorkContext(companyId, `site:${site.id}`) })

  const track = useQuery({
    queryKey: ['site-track', companyId, site.id, scope, offset, common],
    queryFn: () => getSiteTrack(companyId, site.id, { scope, offset, common }),
    enabled: !!companyId && !!site.id,
  })
  const templatesQ = useQuery({
    queryKey: ['process-templates', companyId],
    queryFn: () => docsService.listProcessTemplates(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })

  const start = useMutation({
    mutationFn: (template: docsService.ProcessTemplate) =>
      docsService.startProcessTemplate(template.id, companyId, {
        // Проект как предмет: объект сети появляется только со вводом в
        // эксплуатацию, а работа нужна с первого дня. Документ цепляется
        // СВЯЗЬЮ — предмет карточки уникален на компанию, а по проекту бумаг
        // десяток; поручению уникальность не мешает, и оно берёт предмет.
        relateTo: `site:${site.id}`,
        objectId: track.data?.object_id || undefined,
        responsibleId: context.data?.defaults.responsible_id || site.ownerUserId || undefined,
        title: context.data?.defaults.template_ids?.includes(template.id) ? context.data.defaults.title || undefined : undefined,
      }),
    onMutate: (template) => setStarting(template.id),
    onSettled: () => setStarting(null),
    onSuccess: (result) => {
      toast.success('Заведено по этому проекту')
      void qc.invalidateQueries({ queryKey: ['site-track', companyId, site.id] })
      void qc.invalidateQueries({ queryKey: ['work'] })
      navigate(result.kind === 'document'
        ? `/docs?view=all&doc=${result.docId}`
        : `/docs/company?view=errands&task=${result.taskId}`)
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const items = track.data?.items ?? []
  const waiting = track.data?.waiting ?? 0
  const preferred = context.data?.defaults.template_ids ?? []
  const ready = [...(templatesQ.data?.templates ?? [])].sort((a, b) => Number(preferred.includes(b.id)) - Number(preferred.includes(a.id)))

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium">Работа по проекту</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Документы и поручения «Трека», привязанные к этой площадке.
            {waiting > 0 && (
              <> Обязательные ожидания: <span className="text-amber-700 dark:text-amber-300">{waiting}</span>.</>
            )}
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" className="h-8" disabled={start.isPending}>
              {start.isPending
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <Plus className="mr-1.5 h-3.5 w-3.5" />}
              Завести
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-[290px]">
            <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">
              По заготовке — сразу с привязкой к проекту
            </DropdownMenuLabel>
            {ready.map((template) => (
              <DropdownMenuItem key={template.id} disabled={start.isPending}
                onSelect={() => start.mutate(template)}>
                {starting === template.id
                  ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  : template.kind === 'document'
                    ? <FileText className="mr-2 h-3.5 w-3.5" />
                    : <ClipboardList className="mr-2 h-3.5 w-3.5" />}
                <span className="flex-1 truncate">{template.name}{preferred.includes(template.id) ? ' · для этапа' : ''}</span>
              </DropdownMenuItem>
            ))}
            {!templatesQ.isLoading && ready.length === 0 && (
              <DropdownMenuItem disabled className="text-[11px]">
                Заготовки не заведены — «Трек» → «Настройка» → «Шаблоны»
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            {/* В ленту работы, а не в реестр документов: реестр покажет
                документы и промолчит о поручениях, хотя предмет у них общий. */}
            <DropdownMenuItem
              onSelect={() => navigate(
                `/docs/company?view=work&scope=all&ref=site:${site.id}`)}>
              <ExternalLink className="mr-2 h-3.5 w-3.5" />
              Открыть в «Треке»
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <ProjectWorkActions site={site} companyId={companyId} />
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Отбор работы" className="h-9 rounded-md border bg-background px-2 text-sm" value={scope} onChange={(e) => { setScope(e.target.value); setOffset(0) }}>
          <option value="all">Вся работа</option><option value="open">Открытые</option><option value="mine">Мои</option><option value="overdue">Просроченные</option><option value="pending">Результаты ждут доставки</option>
        </select>
        {site.locationId && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={common} onChange={(e) => { setCommon(e.target.checked); setOffset(0) }} />Общая работа объекта</label>}
        <span className="text-sm text-muted-foreground">Всего: {track.data?.total ?? '…'}</span>
      </div>
      {common && <p className="text-sm text-muted-foreground">Общая работа объекта, не привязанная непосредственно к этому проекту.</p>}
      {track.isError ? <div role="alert" className="rounded-md border p-4 text-sm"><p>Не удалось загрузить работу: {track.error.message}</p><Button variant="outline" className="mt-2" onClick={() => void track.refetch()}>Повторить</Button></div> : track.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Смотрю, что идёт по проекту…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
          По этому проекту в «Треке» ничего не заведено. Кнопка «Завести» ставит
          работу отсюда — она привяжется к проекту и будет видна здесь.
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((item) => (
            <TrackRow key={`${item.kind}-${item.id}`} item={item} site={common ? undefined : site} companyId={companyId} />
          ))}
        </div>
      )}
      {!track.isError && (track.data?.total ?? 0) > 40 && <div className="flex items-center justify-between"><Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(offset - 40)}>Назад</Button><span className="text-sm">{offset + 1}–{Math.min(offset + 40, track.data?.total ?? 0)}</span><Button variant="outline" size="sm" disabled={offset + 40 >= (track.data?.total ?? 0)} onClick={() => setOffset(offset + 40)}>Далее</Button></div>}
    </div>
  )
}

export function TrackRow({ item, site, companyId }: { item: SiteTrackItem; site?: SiteDetail; companyId: string }) {
  const qc = useQueryClient()
  const action = useMutation({ mutationFn: (requestId?: string) => requestId
    ? retryProjectResult(companyId, site!.id, requestId)
    : setProjectNext(companyId, site!.id, { work: { kind: item.kind, id: item.id } }),
    onSuccess: () => { for (const key of ['project-workspace', 'site-track', 'site-detail', 'pr-projects', 'pr-overview']) void qc.invalidateQueries({ queryKey: [key] }); toast.success('Сохранено') }, onError: (e) => toast.error(e.message) })
  const href = item.kind === 'doc'
    ? `/docs?view=all&doc=${item.id}`
    : `/docs/company?view=errands&task=${item.id}`
  const Icon = item.kind === 'doc' ? FileText : ClipboardList
  return (
    <div className="flex items-start gap-2 rounded-md bg-muted/20 px-2.5 py-2 transition-colors hover:bg-muted/40">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground">{item.key}</span>
          <span className={cn('rounded px-1.5 py-0.5 text-[10px]',
            STATE_TONE[item.state] || 'bg-muted text-muted-foreground')}>
            {item.state_name || item.state}
          </span>
        </div>
        <Link to={href} className="mt-1 block break-words text-sm font-medium text-foreground hover:underline">{item.title}</Link>
        <p className="mt-1 text-xs text-muted-foreground">{item.responsible_name || 'Исполнитель не назначен'} · {item.due_at ? new Date(item.due_at).toLocaleDateString('ru') : 'Без срока'}{item.overdue ? ' · Просрочено' : ''}</p>
        {!!item.waiting_for_names?.length && <p className="mt-1 text-xs text-muted-foreground">Ждём: {item.waiting_for_names.join(', ')}</p>}
        {item.kind === 'doc' && <p className="mt-1 text-xs text-muted-foreground">{item.document_state} · редакция {item.revision ?? 1}</p>}
        {item.required && <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">Обязательная работа — удерживает маршрут</p>}
        {item.deliveries?.map((d) => <div key={d.id} className="mt-2 text-xs"><span>{d.pending ? d.error ? 'Результат принят, обновление проекта не удалось' : 'Результат принят, обновление проекта ожидается' : d.outcome ? `Результат: ${d.outcome === 'approved' || d.outcome === 'done' ? 'принят' : 'отклонён или отменён'}` : ''}</span>{d.pending && d.error && site && <Button variant="outline" size="sm" className="ml-2" disabled={action.isPending} onClick={() => action.mutate(d.id)}>Повторить доставку</Button>}</div>)}
        <div className="mt-2 flex flex-wrap items-center gap-3"><WorkOriginLink companyId={companyId} kind={item.kind} id={item.id} />{site && item.state !== 'done' && <Button variant="ghost" size="sm" disabled={action.isPending} onClick={() => action.mutate(undefined)}>Следующий результат</Button>}</div>
      </div>
    </div>
  )
}
