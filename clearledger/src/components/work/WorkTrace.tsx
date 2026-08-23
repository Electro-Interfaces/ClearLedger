/**
 * След работы: одна лента на документ и на поручение (этап 13е).
 *
 * До сих пор один и тот же вопрос — «что с этим делали и кто» — отвечался двумя
 * разными представлениями: у документа своя разметка, у поручения своя. Человек,
 * перешедший из ленты работы в карточку, читал одно и то же по-разному.
 *
 * Общее у следов: время, автор, действие, значение до и после, реплика. Оно и
 * живёт здесь. Особенное — закрепление у поручения, реплики из писем, ссылка на
 * оригинал в архиве Поддержки — приходит слотами: свести его в один компонент
 * значило бы либо потерять эти вещи, либо превратить компонент в свалку
 * необязательных флагов.
 */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface TraceEvent {
  id: string
  /** ISO-время события; пусто — след пришёл без отметки. */
  at: string | null
  actor: string | null
  /** Что сделано, словами: «двинул стадию», «изменил срок», «поставил визу». */
  action: string
  from?: string | null
  to?: string | null
  note?: ReactNode
  /** `mail` — реплика пришла письмом: автор мог не видеть остального контекста. */
  tone?: 'default' | 'mail'
}

function stamp(value: string | null): string {
  if (!value) return ''
  const at = new Date(value)
  return at.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

export function WorkTrace({ events, empty, renderBadge, renderActions, renderExtra }: {
  events: TraceEvent[]
  empty?: ReactNode
  /** Отметка рядом с действием: «письмом», «за коллегу». */
  renderBadge?: (event: TraceEvent) => ReactNode
  /** Действия над записью следа: закрепить, открепить. */
  renderActions?: (event: TraceEvent) => ReactNode
  /** Что добавляет контур под записью: ссылка на оригинал письма, вложение. */
  renderExtra?: (event: TraceEvent) => ReactNode
}) {
  if (events.length === 0) {
    return (
      <p className="px-1 py-3 text-xs text-muted-foreground">
        {empty ?? 'Ходов пока нет.'}
      </p>
    )
  }
  return (
    <div className="space-y-2">
      {events.map((event) => (
        <div key={event.id}
          className={cn('rounded-md border px-3 py-1.5 text-xs',
            event.tone === 'mail'
              ? 'border-sky-500/40 bg-sky-500/5'
              : 'border-border/70 bg-card/60')}>
          <div className="flex flex-wrap items-baseline gap-1.5">
            <span className="font-medium">{event.actor ?? 'система'}</span>
            <span className="text-muted-foreground">{event.action}</span>
            {renderBadge?.(event)}
            <span className="ml-auto text-[11px] text-muted-foreground">
              {stamp(event.at)}
            </span>
            {renderActions?.(event)}
          </div>
          {(event.from || event.to) && (
            <div className="pt-1 text-[13px]">
              {event.from && <span>{event.from}</span>}
              {event.from && event.to && (
                <span className="px-1.5 text-muted-foreground" aria-label="стало">→</span>
              )}
              {event.to && <span>{event.to}</span>}
            </div>
          )}
          {event.note}
          {renderExtra?.(event)}
        </div>
      ))}
    </div>
  )
}
