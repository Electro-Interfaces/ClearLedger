/**
 * Чтение сводок сверки с бухгалтерией — хуки отметки.
 *
 * Отдельно от компонента отметки: списки и карточки берут данные одним и тем же
 * способом, а правила подписей живут в `@/lib/accountingMark`.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { markKey, markState, type MarkState } from '@/lib/accountingMark'
import {
  getAccountingLinkSummaries, getAccountingLinkSummary,
  type AccountingEntityType,
} from '@/services/accountingSpaceService'

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
