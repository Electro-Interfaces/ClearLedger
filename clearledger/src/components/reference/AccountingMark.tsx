/**
 * Общая отметка сверки с бухгалтерией — один компонент на все экраны пространства.
 *
 * «Сверено» в интерфейсе означает конкретные поля (номер и дата — других значений
 * выгрузка не даёт), а не все реквизиты договора. Отметка — кнопка: на телефоне
 * подсказки по наведению нет, и основание должно открываться пальцем и с клавиатуры.
 *
 * Правила и подписи живут в `@/lib/accountingMark` и проверяются тестом; здесь
 * только представление и чтение данных. Три оси канона сверки (сопряжение,
 * проверка, свежесть) раздельны, сводное состояние считает сервер.
 */
import { Loader2 } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { MARK_LABEL, isDerived, markHint, markLines, type MarkState } from '@/lib/accountingMark'
import { useAccountingMark, useAccountingMarks } from '@/hooks/useAccountingMarks'
import type { AccountingEntityType, AccountingLinkSummary } from '@/services/accountingSpaceService'

/** Приглушённая палитра DESIGN.md: цвет помогает различить, подпись говорит сама. */
const MARK_CLS: Record<MarkState, string> = {
  matched_checked: 'border-emerald-400/50 text-emerald-700 dark:text-emerald-300/80',
  contracts_checked: 'border-emerald-400/50 text-emerald-700 dark:text-emerald-300/80',
  differences: 'border-destructive/50 text-destructive',
  stale: 'border-amber-400/50 text-amber-700 dark:text-amber-300/80',
  needs_check: 'border-blue-400/50 text-blue-700 dark:text-blue-300/80',
  no_source: 'border-zinc-600/40 text-muted-foreground',
  loading: 'border-zinc-600/40 text-muted-foreground',
  error: 'border-zinc-600/40 text-muted-foreground',
}

/**
 * Отметка сверки одной карточки.
 *
 * У контрагента и площадки отметка собрана из их договоров, и выдавать её за
 * проверку самой карточки нельзя: слово «договоры» стоит в самом чипе. Число
 * справа — сколько строк выгрузки за отметкой стоит.
 *
 * Нажатие открывает основание: что сверено с выгрузкой, что не сверялось и
 * почему, источник и дата. Подсказки по наведению для этого недостаточно —
 * на телефоне её нет.
 */
const ЧИП = (compact?: boolean) => cn(
  'inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 text-left',
  compact ? 'min-h-6 py-0.5 text-[10px] leading-4' : 'min-h-7 py-1 text-[11px] leading-5')

function Чип({ state, summary }: { state: MarkState; summary?: AccountingLinkSummary }) {
  return <>
    {state === 'loading' && <Loader2 className="size-3 shrink-0 animate-spin" />}
    {isDerived(summary) && <span className="shrink-0 text-muted-foreground">договоры ·</span>}
    <span className="truncate">{MARK_LABEL[state]}</span>
    {!!summary?.records && state !== 'no_source' && <span className="shrink-0 tabular-nums opacity-70">
      {summary.records}</span>}
  </>
}

export function AccountingMark({ state, summary, compact, className }: {
  state: MarkState
  summary?: AccountingLinkSummary
  compact?: boolean
  className?: string
}) {
  const lines = markLines(summary, state)
  const hint = markHint(summary, state)
  const договоры = isDerived(summary)
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" title={hint} aria-label={(договоры ? 'Договоры: ' : '')
        + MARK_LABEL[state] + '. Открыть основание сверки. ' + hint}
        className={cn(ЧИП(compact),
          'hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          MARK_CLS[state], className)}>
        <Чип state={state} summary={summary} />
      </button>
    </PopoverTrigger>
    <PopoverContent align="start" collisionPadding={8} className="max-h-[min(70dvh,var(--radix-popover-content-available-height))] w-[min(92vw,26rem)] overflow-y-auto overscroll-contain text-xs">
      <p className="mb-1.5 font-semibold">{(договоры ? 'Договоры: ' : '') + MARK_LABEL[state]}</p>
      <ul className="flex flex-col gap-1 text-muted-foreground">
        {lines.map((t, i) => <li key={i}>{t}</li>)}
      </ul>
    </PopoverContent>
  </Popover>
}

/**
 * Та же отметка без раскрытия — для строки, которая сама является кнопкой.
 *
 * Кнопка внутри кнопки — недопустимая разметка, и нажатие перестаёт выбирать
 * строку. В списке контрагентов отметка только называет состояние, а основание
 * открывается в карточке, куда строка и ведёт.
 */
export function AccountingMarkLabel({ state, summary, compact, className }: {
  state: MarkState
  summary?: AccountingLinkSummary
  compact?: boolean
  className?: string
}) {
  return <span title={markHint(summary, state)}
    aria-label={(isDerived(summary) ? 'Договоры: ' : '') + MARK_LABEL[state]
      + '. Основание — в карточке.'}
    className={cn('flex', ЧИП(compact), MARK_CLS[state], className)}>
    <Чип state={state} summary={summary} />
  </span>
}

/** Отметка строки списка: один вызов вместо повторения useQuery в каждой таблице. */
export function AccountingMarkCell({ marks, id, compact = true, className }: {
  marks: ReturnType<typeof useAccountingMarks>
  id: string
  compact?: boolean
  className?: string
}) {
  return <AccountingMark state={marks.state(id)} summary={marks.summary(id)}
    compact={compact} className={className} />
}

/** Отметка карточки по её собственной сводке — для заголовков карточек. */
export function AccountingMarkFor({ entityType, id, compact }: {
  entityType: AccountingEntityType
  id: string
  compact?: boolean
}) {
  const { summary, state } = useAccountingMark(entityType, id)
  return <AccountingMark state={state} summary={summary} compact={compact} />
}
