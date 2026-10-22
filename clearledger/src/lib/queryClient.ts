import { QueryClient, MutationCache, QueryCache } from '@tanstack/react-query'
import { toast } from 'sonner'

function formatErrorMessage(error: unknown): { title: string; description: string } {
  if (error instanceof Error) {
    return { title: 'Ошибка', description: error.message }
  }
  return { title: 'Ошибка', description: String(error) }
}

const queryCache = new QueryCache({
  onError: (error, query) => {
    if (query.state.data !== undefined) {
      const { title, description } = formatErrorMessage(error)
      toast.error(title, { description })
    }
  },
})

const mutationCache = new MutationCache({
  onError: (error) => {
    const { title, description } = formatErrorMessage(error)
    toast.error(title, { description })
  },
})

export const queryClient = new QueryClient({
  queryCache,
  mutationCache,
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// Каталог — проекция тех же карточек, справочников и документов площадок.
// Их штатная инвалидация должна обновлять и проводник, включая скрытую
// закреплённую вкладку. Собираем компанию один раз за пачку инвалидаций.
const pendingCatalogCompanies = new Set<string>()
queryCache.subscribe((event) => {
  if (event.type !== 'updated' || event.action.type !== 'invalidate') return
  const [source, first, second] = event.query.queryKey
  if (!['docs', 'doc', 'references', 'site-docs'].includes(String(source))) return
  const companyId = source === 'doc' ? second : first
  if (typeof companyId !== 'string' || !companyId || pendingCatalogCompanies.has(companyId)) return
  pendingCatalogCompanies.add(companyId)
  queueMicrotask(() => {
    pendingCatalogCompanies.delete(companyId)
    void queryClient.invalidateQueries({ queryKey: ['raw-docs-space', companyId] })
  })
})
