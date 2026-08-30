import { AlertCircle, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/services/apiClient'

interface QueryErrorProps {
  /** Общая фраза на случай, когда сервер ничего не объяснил. */
  message?: string
  /**
   * Сама ошибка. Её текст объясняет причину лучше любой общей фразы, а статус
   * различает две разные вещи: сбой, который стоит повторить, и отказ, который
   * повторять бессмысленно.
   */
  error?: unknown
  onRetry?: () => void
}

/**
 * Экран не загрузился — и человек должен понять, почему.
 *
 * Раньше здесь всегда стояла общая фраза и кнопка «Повторить». Для сбоя это
 * верно, для отказа — нет: сервер объяснял словами, за что отказал, текст
 * пропадал, а человек жал «Повторить», пока не шёл звонить. Отказ и сбой — не
 * одно и то же и выглядеть одинаково не должны.
 */
export function QueryError({ message, error, onRetry }: QueryErrorProps) {
  const отказ = error instanceof ApiError
    && (error.status === 403 || error.status === 404)
  const свой = error instanceof Error ? error.message.trim() : ''
  const текст = свой || message || 'Не удалось загрузить данные'
  const Значок = отказ ? Lock : AlertCircle

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <div className={отказ ? 'rounded-full bg-muted p-3' : 'rounded-full bg-destructive/10 p-3'}>
        <Значок className={отказ ? 'size-6 text-muted-foreground' : 'size-6 text-destructive'} />
      </div>
      <p className="max-w-sm text-sm text-muted-foreground">{текст}</p>
      {/* Повторять отказ нечего: право от нажатия не появится. */}
      {onRetry && !отказ && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  )
}
