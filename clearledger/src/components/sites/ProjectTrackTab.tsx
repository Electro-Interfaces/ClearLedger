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
import { useNavigate } from 'react-router-dom'
import { ClipboardList, ExternalLink, FileText, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import * as docsService from '@/services/docsService'
import { getSiteTrack, type SiteDetail, type SiteTrackItem } from '@/services/sitesService'

/** Тон колонки общей оси: слева заведённое, справа завершённое. */
const STATE_TONE: Record<string, string> = {
  new: 'bg-muted text-muted-foreground',
  in_work: 'bg-blue-500/10 text-blue-300',
  approval: 'bg-amber-500/10 text-amber-300',
  external: 'bg-purple-500/10 text-purple-300',
  done: 'bg-emerald-500/10 text-emerald-300',
}

export function ProjectTrackTab({ site, companyId }: {
  site: SiteDetail; companyId: string
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [starting, setStarting] = useState<string | null>(null)

  const track = useQuery({
    queryKey: ['site-track', companyId, site.id],
    queryFn: () => getSiteTrack(companyId, site.id),
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
        // Предмет — сам проект: объект сети появляется только со вводом в
        // эксплуатацию, а бумаги нужны с первого дня. Есть объект — цепляем и
        // к нему, чтобы работа нашлась с обеих сторон.
        subjectRef: `site:${site.id}`,
        objectId: track.data?.object_id || undefined,
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
  const ready = (templatesQ.data?.templates ?? []).filter((t) => !t.requiresPreparation)

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium">Работа по проекту</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Документы и поручения «Трека», привязанные к этой площадке.
            {waiting > 0 && (
              <> Держат ход: <span className="text-amber-300">{waiting}</span>.</>
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
                <span className="flex-1 truncate">{template.name}</span>
              </DropdownMenuItem>
            ))}
            {!templatesQ.isLoading && ready.length === 0 && (
              <DropdownMenuItem disabled className="text-[11px]">
                Заготовки не заведены — «Трек» → «Регламент» → «Шаблоны»
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => navigate(`/docs?view=all&ref=site:${site.id}`)}>
              <ExternalLink className="mr-2 h-3.5 w-3.5" />
              Открыть в «Треке»
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {track.isLoading ? (
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
            <TrackRow key={`${item.kind}-${item.id}`} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}

function TrackRow({ item }: { item: SiteTrackItem }) {
  const href = item.kind === 'doc'
    ? `/docs?view=all&doc=${item.id}`
    : `/docs/company?view=errands&task=${item.id}`
  const Icon = item.kind === 'doc' ? FileText : ClipboardList
  return (
    <a href={href}
      className="flex items-start gap-2 rounded-md bg-muted/20 px-2.5 py-2 transition-colors hover:bg-muted/40">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground">{item.key}</span>
          <span className={cn('rounded px-1.5 py-0.5 text-[10px]',
            STATE_TONE[item.state] || 'bg-muted text-muted-foreground')}>
            {item.state_name || item.state}
          </span>
        </div>
        <div className="truncate text-xs text-foreground" title={item.title}>{item.title}</div>
      </div>
    </a>
  )
}
