import { AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface QueryErrorProps {
  message?: string
  onRetry?: () => void
}

export function QueryError({ message, onRetry }: QueryErrorProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center gap-3">
      <div className="rounded-full bg-destructive/10 p-3">
        <AlertCircle className="size-6 text-destructive" />
      </div>
      <p className="text-sm text-muted-foreground max-w-sm">
        {message ?? 'Не удалось загрузить данные'}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  )
}
