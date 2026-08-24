/**
 * «Трек» в карточке объекта: документы и поручения по этой площадке.
 *
 * Тот же вопрос, что в карточке проекта, только с другой стороны жизни объекта.
 * Проект отвечает «что нужно, чтобы станция появилась», эксплуатация — «что по
 * ней идёт сейчас»: приказ о выводе в ремонт, поручение на замену модуля, акт
 * обследования. Раньше всё это лежало в «Треке» и из карточки объекта видно не
 * было — вкладка «Обслуживание» показывает заявки, а не документооборот.
 *
 * Заводить работу отсюда намеренно нельзя. У объекта в эксплуатации нет
 * заготовок «своего» вида: наряд ставят из заявки, приказ — из «Трека», и
 * третья точка входа только запутала бы. Здесь смотрят, а не начинают.
 */
import { useQuery } from '@tanstack/react-query'
import { ClipboardList, ExternalLink, FileText, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { listWork, type WorkItem } from '@/services/workService'

const STATE_TONE: Record<string, string> = {
  new: 'bg-muted text-muted-foreground',
  in_work: 'bg-blue-500/10 text-blue-300',
  approval: 'bg-amber-500/10 text-amber-300',
  external: 'bg-purple-500/10 text-purple-300',
  done: 'bg-emerald-500/10 text-emerald-300',
}

export function TrackTab({ location }: { location: { id: string } }) {
  const { company } = useCompany()
  const companyId = company?.id ?? ''
  const locationId = location.id
  const work = useQuery({
    queryKey: ['location-track', companyId, locationId],
    queryFn: () => listWork(companyId, {
      ref: `object:${locationId}`, scope: 'all', limit: 100,
    }),
    enabled: !!companyId && !!locationId,
  })

  const items = work.data?.work ?? []
  const waiting = items.filter((i) => i.state === 'approval' || i.state === 'external')

  if (work.isLoading) {
    return (
      <div className="flex items-center gap-2 p-6 text-xs text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Смотрю, что идёт по объекту…
      </div>
    )
  }

  return (
    <div className="space-y-3 p-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Документы и поручения «Трека», привязанные к объекту.
          {waiting.length > 0 && (
            <> Держат ход: <span className="text-amber-300">{waiting.length}</span>.</>
          )}
        </p>
        {items.length > 0 && (
          <a href={`/docs/company?view=work&scope=all&ref=object:${locationId}`}
            className="inline-flex items-center gap-1 text-xs text-blue-400 hover:underline">
            <ExternalLink className="h-3 w-3" />Открыть в «Треке»
          </a>
        )}
      </div>

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
          По этому объекту в «Треке» ничего не заведено. Работа появится здесь,
          когда её привяжут к объекту — из заявки, из проекта или из самого «Трека».
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((item) => <Row key={`${item.kind}-${item.id}`} item={item} />)}
        </div>
      )}
    </div>
  )
}

function Row({ item }: { item: WorkItem }) {
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
          {item.type && <span className="text-[10px] text-muted-foreground">· {item.type}</span>}
          <span className={cn('rounded px-1.5 py-0.5 text-[10px]',
            STATE_TONE[item.state] || 'bg-muted text-muted-foreground')}>
            {item.state_name}
          </span>
          {/* Просрочку называем на месте: в карточке объекта она объясняет,
              почему работа стоит, и искать её в общем реестре незачем. */}
          {item.overdue && (
            <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-300">
              просрочено
            </span>
          )}
        </div>
        <div className="truncate text-xs text-foreground" title={item.title}>{item.title}</div>
        {(item.responsible || item.stage) && (
          <div className="text-[10px] text-muted-foreground">
            {[item.stage, item.responsible].filter(Boolean).join(' · ')}
          </div>
        )}
      </div>
    </a>
  )
}
