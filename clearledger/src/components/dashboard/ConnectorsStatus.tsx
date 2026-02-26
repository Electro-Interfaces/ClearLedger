import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { mockConnectors } from '@/services/mockData'

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
  return new Date(lastSync).toLocaleDateString('ru-RU')
}

export function ConnectorsStatus() {
  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Коннекторы</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {mockConnectors.map((connector) => (
          <div key={connector.id} className="flex items-center gap-3">
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
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
