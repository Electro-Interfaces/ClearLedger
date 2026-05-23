import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { ru } from 'date-fns/locale'
import { RefreshCw, Settings } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChannelTypeIcon } from './ChannelTypeIcon'
import type { Channel } from '@/types'

const typeLabels: Record<string, string> = {
  email: 'Электронная почта',
  '1c': '1С',
  oneC: '1С',
  rest: 'REST API',
  api: 'API',
  ftp: 'FTP/SFTP',
  webhook: 'Вебхук',
  upload: 'Загрузка файлов',
  manual: 'Ручной ввод',
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  edi: 'ЭДО',
}

const statusConfig: Record<Channel['status'], { label: string; className: string }> = {
  active: { label: 'Активен', className: 'bg-green-600/20 text-green-400 border-green-600/30' },
  error: { label: 'Ошибка', className: 'bg-red-600/20 text-red-400 border-red-600/30' },
  disabled: { label: 'Отключён', className: 'bg-gray-600/20 text-gray-400 border-gray-600/30' },
  not_configured: { label: 'Не настроен', className: 'bg-yellow-600/20 text-yellow-400 border-yellow-600/30' },
}

interface Props {
  channel: Channel
  onSync?: (channel: Channel) => void
  syncing?: boolean
}

export function ChannelCard({ channel, onSync, syncing }: Props) {
  const status = statusConfig[channel.status]

  return (
    <Card className="hover:bg-muted/30 transition-colors">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <ChannelTypeIcon type={channel.type} className="size-5 text-primary" />
            </div>
            <div className="min-w-0">
              <p className="font-medium truncate">{channel.name}</p>
              <p className="text-xs text-muted-foreground">{typeLabels[channel.type] ?? channel.type}</p>
            </div>
          </div>
          <Badge variant="outline" className={status.className}>{status.label}</Badge>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <div className="text-muted-foreground">Сегодня:</div>
          <div className="font-medium">{channel.todayCount}</div>
          <div className="text-muted-foreground">Всего:</div>
          <div className="font-medium">{channel.totalCount}</div>
          {channel.errorsCount > 0 && (
            <>
              <div className="text-muted-foreground">Ошибок:</div>
              <div className="font-medium text-destructive">{channel.errorsCount}</div>
            </>
          )}
          <div className="text-muted-foreground">Посл. синх.:</div>
          <div className="font-medium text-xs">
            {channel.lastSyncAt
              ? formatDistanceToNow(new Date(channel.lastSyncAt), { addSuffix: true, locale: ru })
              : '—'}
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          {channel.kind !== 'manual' && onSync && (
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              disabled={channel.status === 'disabled' || syncing}
              onClick={() => onSync(channel)}
            >
              <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'Синхронизация...' : 'Синхронизировать'}
            </Button>
          )}
          <Link to={`/channels/${channel.id}`} className="flex-1">
            <Button variant="outline" size="sm" className="w-full">
              <Settings className="mr-1.5 h-3.5 w-3.5" />
              Настроить
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}
