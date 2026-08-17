import { RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ApiError, isNetworkError } from '@/services/apiClient'

export function DocsLoadingState({ children }: { children: string }) {
  return (
    <Card className="p-6 text-sm text-muted-foreground" role="status" aria-live="polite">
      {children}
    </Card>
  )
}

export function DocsErrorState({ error, title, detail, onRetry }: {
  error: unknown
  title: string
  detail?: string
  onRetry: () => void
}) {
  const denied = error instanceof ApiError && error.status === 403
  const offline = isNetworkError(error)
  const heading = denied ? 'Недостаточно прав'
    : offline ? 'Сервис Трека недоступен' : title
  const description = denied
    ? 'Этот раздел закрыт вашей ролью или правилами документа.'
    : detail ?? 'Данные не заменены пустым списком. Повторите запрос.'

  return (
    <Card role="alert" className="rounded-md border-destructive/30 bg-destructive/5 p-4">
      <div className="text-sm font-medium text-destructive">{heading}</div>
      <div className="mt-1 text-sm text-muted-foreground">{description}</div>
      {!denied && (
        <Button type="button" size="sm" variant="outline" className="mt-3" onClick={onRetry}>
          <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
        </Button>
      )}
    </Card>
  )
}
