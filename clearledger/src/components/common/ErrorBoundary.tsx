import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { AlertTriangle } from 'lucide-react'
import { reportClientError } from '@/lib/reportClientError'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  /** Где стоит граница: «Чат», «Маркетинг · Расклад сил». Уезжает в журнал сбоев. */
  screen?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  // Человек видит «Что-то пошло не так», мы — где именно. Прежде падение экрана
  // не оставляло следа нигде, и разбор начинался с угадывания (МАГ, 18.09.2026).
  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportClientError({
      message: error?.message || String(error),
      stack: error?.stack,
      componentStack: info?.componentStack,
      screen: this.props.screen,
    })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div className="flex flex-col items-center justify-center gap-4 py-16 px-4 text-center">
          <AlertTriangle className="size-12 text-destructive" />
          <h2 className="text-lg font-semibold">Что-то пошло не так</h2>
          <p className="text-sm text-muted-foreground max-w-md">
            {this.state.error?.message ?? 'Произошла непредвиденная ошибка'}
          </p>
          <div className="flex gap-2">
            <Button onClick={this.handleReset}>Попробовать снова</Button>
            <Button variant="outline" onClick={() => window.location.assign('/')}>
              На главную
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
