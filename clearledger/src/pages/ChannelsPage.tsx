import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Radio, Plus, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { ChannelsGrid } from '@/components/channels/ChannelsGrid'
import { useChannels, useChannelStats } from '@/hooks/useChannels'
import { useSyncConnector } from '@/hooks/useConnectors'
import { useSyncFull } from '@/hooks/useOneCSync'

export function ChannelsPage() {
  const { data: channels, isLoading } = useChannels()
  const { data: stats } = useChannelStats()
  const queryClient = useQueryClient()
  const syncConnector = useSyncConnector()
  const syncOneCFull = useSyncFull()
  const [syncingAll, setSyncingAll] = useState(false)

  const hasSyncable = channels?.some(
    (ch) => ch.kind !== 'manual' && ch.status !== 'disabled'
  )

  async function handleSyncAll() {
    if (!channels) return
    const syncable = channels.filter(
      (ch) => ch.kind !== 'manual' && ch.status !== 'disabled'
    )
    if (syncable.length === 0) {
      toast.info('Нет каналов для синхронизации')
      return
    }

    setSyncingAll(true)
    let ok = 0
    let fail = 0

    for (const ch of syncable) {
      try {
        if (ch.kind === 'connector' && ch.connectorId) {
          await syncConnector.mutateAsync(ch.connectorId)
          ok++
        } else if (ch.kind === 'oneC' && ch.connectionId) {
          await syncOneCFull.mutateAsync(ch.connectionId)
          ok++
        }
      } catch {
        fail++
      }
    }

    setSyncingAll(false)
    queryClient.invalidateQueries({ queryKey: ['channels'] })
    queryClient.invalidateQueries({ queryKey: ['channel-stats'] })
    queryClient.invalidateQueries({ queryKey: ['entries'] })

    if (fail === 0) {
      toast.success(`Синхронизировано ${ok} каналов`)
    } else {
      toast.warning(`Синхронизировано ${ok}, ошибок: ${fail}`)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radio className="size-6 text-primary" />
          <h1 className="text-2xl font-bold">Каналы поступления</h1>
        </div>
        <div className="flex items-center gap-2">
          {hasSyncable && (
            <Button variant="outline" size="sm" disabled={syncingAll} onClick={handleSyncAll}>
              <RefreshCw className={`mr-1.5 h-4 w-4 ${syncingAll ? 'animate-spin' : ''}`} />
              {syncingAll ? 'Синхронизация...' : 'Обновить всё'}
            </Button>
          )}
          <Link to="/connectors/new">
            <Button size="sm">
              <Plus className="mr-1.5 h-4 w-4" />
              Канал
            </Button>
          </Link>
        </div>
      </div>

      {channels && channels.length > 0 ? (
        <ChannelsGrid channels={channels} stats={stats} />
      ) : (
        <div className="text-center py-16 space-y-4">
          <Radio className="mx-auto size-12 text-muted-foreground/50" />
          <div>
            <p className="text-lg font-medium">Каналы не настроены</p>
            <p className="text-sm text-muted-foreground mt-1">
              Настройте первый канал для автоматического получения документов — почта, API, 1С или другие источники.
            </p>
          </div>
          <Link to="/connectors/new">
            <Button className="mt-2">
              <Plus className="mr-2 h-4 w-4" />
              Добавить канал
            </Button>
          </Link>
        </div>
      )}
    </div>
  )
}
