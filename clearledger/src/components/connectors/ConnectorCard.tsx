import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Plug, Clock, FileText, AlertTriangle } from 'lucide-react'
import type { Connector } from '@/types'

interface ConnectorCardProps {
  connector: Connector
}

const statusConfig = {
  active: { label: 'Активен', className: 'bg-green-600/20 text-green-400 border-green-600/30' },
  error: { label: 'Ошибка', className: 'bg-red-600/20 text-red-400 border-red-600/30' },
  disabled: { label: 'Отключён', className: 'bg-gray-600/20 text-gray-400 border-gray-600/30' },
}

function formatRelativeTime(dateStr?: string): string {
  if (!dateStr) return 'Никогда'
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Только что'
  if (mins < 60) return `${mins} мин. назад`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} ч. назад`
  return `${Math.floor(hours / 24)} дн. назад`
}

export function ConnectorCard({ connector }: ConnectorCardProps) {
  const status = statusConfig[connector.status]

  return (
    <Link to={`/connectors/${connector.id}`}>
      <Card className="hover:bg-accent/30 transition-colors cursor-pointer">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <Plug className="h-5 w-5 text-primary" />
              </div>
              <CardTitle className="text-base">{connector.name}</CardTitle>
            </div>
            <Badge variant="outline" className={status.className}>
              {status.label}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <Clock className="h-3.5 w-3.5" />
              <span>Синхр.: {formatRelativeTime(connector.lastSync)}</span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="h-3.5 w-3.5" />
                <span>{connector.recordsCount.toLocaleString('ru-RU')} записей</span>
              </div>
              {connector.errorsCount > 0 && (
                <div className="flex items-center gap-1 text-red-400">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span>{connector.errorsCount}</span>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
