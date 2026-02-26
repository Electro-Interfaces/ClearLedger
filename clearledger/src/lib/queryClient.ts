import { QueryClient, MutationCache, QueryCache } from '@tanstack/react-query'
import { toast } from 'sonner'

const queryCache = new QueryCache({
  onError: (error, query) => {
    // Показываем toast только если данные уже были (background refetch failed)
    if (query.state.data !== undefined) {
      const message = error instanceof Error ? error.message : 'Неизвестная ошибка'
      toast.error('Ошибка загрузки данных', { description: message })
    }
  },
})

const mutationCache = new MutationCache({
  onError: (error) => {
    const message = error instanceof Error ? error.message : 'Неизвестная ошибка'
    toast.error('Ошибка операции', { description: message })
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
