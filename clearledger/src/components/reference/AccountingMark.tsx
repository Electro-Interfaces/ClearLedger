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
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  MARK_LABEL, isDerived, markHint, markKey, markLines, markState, type MarkState,
} from '@/lib/accountingMark'
import {
  getAccountingLinkSummaries, getAccountingLinkSummary,
  type AccountingEntityType, type AccountingLinkSummary,
} from '@/services/accountingSpaceService'

export {
  MARK_KEYS, MARK_LABEL, MATCHING_LABEL, VERIFICATION_LABEL, markHint, markLines,
  markState, полеRU, дата, type MarkState,
} from '@/lib/accountingMark'

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
 * Сводки сверки для отображаемых строк списка — один запрос на экран.
 *
 * `ids` передаются только видимые: строка своего запроса не делает, иначе реестр
 * из девятисот договоров даёт девятьсот обращений. `companyId` и организация стоят
 * и в ключе, и в параметрах: без них React Query отдал бы кеш прошлого разреза,
 * а заголовок `X-Organization-Id` уже ушёл бы новый.
 *
 * Повтор один: отметка состояния обязана быстро сказать «недоступна», а не висеть
 * «загружается», пока клиент трижды переспрашивает упавший сервис.
 */
export function useAccountingMarks(entityType: AccountingEntityType, ids: string[], enabled = true) {
  const { companyId, organizationId } = useCompany()
  // Порядок строк меняет сортировка, состав — нет: ключ по составу, не по порядку.
  const состав = useMemo(() => [...new Set(ids)].sort(), [ids])
  const q = useQuery({
    queryKey: ['acct-space-marks', companyId, organizationId, entityType, markKey(состав)],
    queryFn: () => getAccountingLinkSummaries(companyId, entityType, состав, organizationId),
    enabled: !!companyId && enabled && состав.length > 0, staleTime: 60_000, retry: 1,
  })
  // Ссылка стабильна, пока не изменились данные: иначе useMemo у вызывающих
  // пересобирал бы таблицу на каждый рендер.
  return useMemo(() => ({
    summary: (id: string) => q.data?.[id],
    state: (id: string): MarkState => markState(q.data?.[id], q.isLoading, q.isError),
    loading: q.isLoading, error: q.isError, ready: !!q.data, refetch: q.refetch,
  }), [q.data, q.isLoading, q.isError, q.refetch])
}

/** Сводка одной карточки — для её собственного экрана. */
export function useAccountingMark(entityType: AccountingEntityType, id: string | undefined) {
  const { companyId, organizationId } = useCompany()
  const q = useQuery({
    queryKey: ['acct-space-mark', companyId, organizationId, entityType, id],
    queryFn: () => getAccountingLinkSummary(companyId, entityType, id!, organizationId),
    enabled: !!companyId && !!id, staleTime: 60_000, retry: 1,
  })
  return {
    summary: q.data,
    state: markState(q.data, q.isLoading, q.isError),
    loading: q.isLoading, error: q.isError, refetch: q.refetch,
  }
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
        className={cn('inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 text-left',
          compact ? 'min-h-6 py-0.5 text-[10px] leading-4' : 'min-h-7 py-1 text-[11px] leading-5',
          'hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          MARK_CLS[state], className)}>
        {state === 'loading' && <Loader2 className="size-3 shrink-0 animate-spin" />}
        {договоры && <span className="shrink-0 text-muted-foreground">договоры ·</span>}
        <span className="truncate">{MARK_LABEL[state]}</span>
        {!!summary?.records && state !== 'no_source' && <span className="shrink-0 tabular-nums opacity-70">
          {summary.records}</span>}
      </button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-[min(92vw,26rem)] text-xs">
      <p className="mb-1.5 font-semibold">{(договоры ? 'Договоры: ' : '') + MARK_LABEL[state]}</p>
      <ul className="flex flex-col gap-1 text-muted-foreground">
        {lines.map((t, i) => <li key={i}>{t}</li>)}
      </ul>
    </PopoverContent>
  </Popover>
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
