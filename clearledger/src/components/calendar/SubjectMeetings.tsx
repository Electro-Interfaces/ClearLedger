/**
 * Обсуждения по предмету: что назначено вокруг этого документа или поручения.
 *
 * Цепочка работы устроена так: предмет → встреча → решение → новые поручения.
 * До этого блока она проходилась только в одну сторону — встречу можно было
 * собрать, но из карточки не было видно, что собирались. Через месяц вопрос
 * «мы это вообще обсуждали?» решался поиском в чате.
 *
 * Круг видимости шире моего ровно на одну ступень: если человек видит предмет,
 * ФАКТ назначенного по нему совещания — часть истории предмета. Закрытая встреча
 * при этом остаётся закрытой, и отбор делает сервер, а не этот экран.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EventDialog } from '@/components/calendar/EventDialog'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'
import { cn } from '@/lib/utils'

/** Окно поиска обсуждений: полгода назад и год вперёд. Не «все за всё время» —
 *  выборка без границ на живом пространстве однажды вытащит тысячу строк ради
 *  трёх; и не «текущий месяц» — совещание по договору назначают за квартал. */
const НАЗАД_ДНЕЙ = 180
const ВПЕРЁД_ДНЕЙ = 365

export function SubjectMeetings({ companyId, subjectRef, title, canPlan = true }: {
  companyId: string
  /** Предмет словарём пространства: `doc:<uuid>`, `task:<uuid>`. */
  subjectRef: string
  /** Как называется предмет — станет заготовкой названия встречи. */
  title: string
  /** Право назначать. Смотреть назначенное вправе всякий, кто видит предмет. */
  canPlan?: boolean
}) {
  const qc = useQueryClient()
  const [собираем, setСобираем] = useState(false)
  const [открыта, setОткрыта] = useState<CalendarEvent | null>(null)

  const [от, до] = (() => {
    const н = new Date(); н.setDate(н.getDate() - НАЗАД_ДНЕЙ)
    const к = new Date(); к.setDate(к.getDate() + ВПЕРЁД_ДНЕЙ)
    return [н.toISOString(), к.toISOString()]
  })()

  const q = useQuery({
    queryKey: ['subject-meetings', companyId, subjectRef],
    queryFn: () => workService.listEvents(companyId, от, до, { subjectRef }),
    enabled: !!companyId && !!subjectRef,
  })

  const rows = (q.data?.events ?? [])
    .slice()
    .sort((a, b) => b.starts_at.localeCompare(a.starts_at))

  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['subject-meetings', companyId, subjectRef] })
    void qc.invalidateQueries({ queryKey: ['calendar'] })
  }

  if (!rows.length && !canPlan) return null

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Обсуждения
        </h3>
        {canPlan && (
          <Button size="sm" variant="ghost" className="ml-auto h-7 px-2 text-xs"
            onClick={() => setСобираем(true)}>
            <CalendarPlus className="mr-1 h-3.5 w-3.5" />Назначить
          </Button>
        )}
      </div>

      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          По этому предмету не собирались
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((e) => {
            const отменена = e.status === 'cancelled'
            return (
              <li key={e.id}>
                <button onClick={() => setОткрыта(e)}
                  className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-muted/60">
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {дата.format(new Date(e.starts_at))}
                  </span>
                  <span className={cn('min-w-0 flex-1 truncate',
                    отменена ? 'text-muted-foreground line-through' : 'text-foreground')}>
                    {e.title}
                  </span>
                  {e.conference_url && !отменена && (
                    <Video className="h-3 w-3 shrink-0 text-muted-foreground" />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {(собираем || открыта) && (
        <EventDialog companyId={companyId} event={открыта}
          startAt={собираем ? new Date() : null}
          subjectRef={subjectRef}
          initialTitle={собираем ? `Обсуждение: ${title}`.slice(0, 300) : undefined}
          onClose={() => { setСобираем(false); setОткрыта(null) }}
          onChanged={обновить} />
      )}
    </div>
  )
}

const дата = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' })

export default SubjectMeetings
