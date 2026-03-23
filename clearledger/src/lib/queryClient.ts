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
