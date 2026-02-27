import { QueryClient, MutationCache, QueryCache } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiValidationError, ApiError, isNetworkError } from '@/services/apiClient'

function formatErrorMessage(error: unknown): { title: string; description: string } {
  if (isNetworkError(error)) {
    return {
      title: 'Нет подключения к серверу',
      description: 'Проверьте сетевое соединение или попробуйте позже',
    }
  }
  if (error instanceof ApiValidationError) {
    return {
      title: 'Ошибка валидации',
      description: error.fieldErrors.length > 0
        ? error.fieldErrors.map((e) => `${e.loc.join('.')}: ${e.msg}`).join('\n')
        : error.message,
    }
  }
  if (error instanceof ApiError) {
    return {
      title: `Ошибка ${error.status}`,
      description: error.detail,
    }
  }
  return {
    title: 'Неизвестная ошибка',
    description: error instanceof Error ? error.message : String(error),
  }
}

const queryCache = new QueryCache({
  onError: (error, query) => {
    // Показываем toast только если данные уже были (background refetch failed)
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
