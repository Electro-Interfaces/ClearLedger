import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useConnectors } from '@/hooks/useConnectors'
import { formatDate } from '@/lib/formatDate'

const statusDotColor: Record<string, string> = {
  active: 'bg-green-500',
  error: 'bg-red-500',
  disabled: 'bg-gray-500',
}

function formatLastSync(lastSync?: string): string {
  if (!lastSync) return 'Отключен'

  const diff = Date.now() - new Date(lastSync).getTime()
  const minutes = Math.floor(diff / 60_000)
  const hours = Math.floor(minutes / 60)

  if (minutes < 1) return 'Только что'
  if (minutes < 60) return `${minutes} мин. назад`
  if (hours < 24) return `${hours} ч. назад`
  return formatDate(lastSync)
}

export function ConnectorsStatus() {
  const { data: connectors = [] } = useConnectors()

  if (connectors.length === 0) {
    return (
      <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
        <CardHeader>
          <CardTitle>Коннекторы</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-3 py-6">
          <p className="text-sm text-muted-foreground">Не настроены</p>
          <Button variant="outline" size="sm" asChild>
            <Link to="/connectors">
              <Plus className="mr-2 h-4 w-4" />
              Настроить
            </Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Коннекторы</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {connectors.map((connector) => (
          <Link
            key={connector.id}
            to={`/connectors/${connector.id}`}
            className="flex items-center gap-3 hover:bg-accent/30 rounded-md p-1 -m-1 transition-colors"
          >
            <span
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusDotColor[connector.status] ?? 'bg-gray-500'}`}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{connector.name}</p>
              <p className="text-xs text-muted-foreground">
                {connector.status === 'disabled'
                  ? 'Отключен'
                  : formatLastSync(connector.lastSync)}
              </p>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}
