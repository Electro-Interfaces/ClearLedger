/**
 * Как предмет работы представляется человеку (этап 13е).
 *
 * Одна строка на документ и на поручение: ключ, вид работы и состояние на общей
 * оси пространства. До сих пор карточки представлялись по-разному — документ
 * показывал состояние делопроизводства, поручение статус движка, — и человек,
 * переходя между ними, читал разные слова об одном и том же.
 *
 * Ленты событий сознательно НЕ сведены в один компонент: у поручения в ней
 * закрепление и реплики из писем, у документа — значения реквизитов до и после.
 * Общее в них — время, автор и действие — и это уже одинаково; свести остальное
 * значило бы потерять то, ради чего ленты вообще читают.
 */
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** Тон колонки. Красный не используем: «Ждём внешних» это не беда, а состояние. */
const STATE_TONE: Record<string, string> = {
  new: 'text-muted-foreground',
  in_work: 'text-sky-700 dark:text-sky-300 border-sky-500/40',
  approval: 'text-amber-700 dark:text-amber-400 border-amber-500/40',
  external: 'text-violet-700 dark:text-violet-300 border-violet-500/40',
  done: 'text-emerald-700 dark:text-emerald-400 border-emerald-500/40',
}

export function WorkStateBadge({ state, stateName, className }: {
  state?: string | null
  stateName?: string | null
  className?: string
}) {
  if (!state || !stateName) return null
  return (
    <Badge variant="outline"
      className={cn('h-5 px-1.5 text-xs font-normal', STATE_TONE[state], className)}>
      {stateName}
    </Badge>
  )
}

/** Ключ, вид и состояние — то, чем предмет одинаково представляется в обеих
 *  карточках. Всё остальное различается по существу и живёт внутри карточки. */
export function WorkIdentity({ itemKey, type, state, stateName, extra, className }: {
  itemKey: string
  type?: string | null
  state?: string | null
  stateName?: string | null
  /** Что добавляет контур: организация и контрагент у документа, проект у работы. */
  extra?: string | null
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2 text-xs text-muted-foreground',
      className)}>
      <span className="font-mono text-[13px] font-semibold text-foreground">{itemKey}</span>
      {type && <span>{type}</span>}
      <WorkStateBadge state={state} stateName={stateName} />
      {extra && <span>{extra}</span>}
    </div>
  )
}
