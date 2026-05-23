import { useState } from 'react'
import { Radio, AlertTriangle, CheckCircle2, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { ChannelCard } from './ChannelCard'
import { useSyncConnector } from '@/hooks/useConnectors'
import { useSyncFull } from '@/hooks/useOneCSync'
import type { Channel, ChannelStats } from '@/types'

interface Props {
  channels: Channel[]
  stats?: ChannelStats
}

function StatBox({ icon: Icon, label, value, color }: { icon: React.ElementType; label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${color}`}>
        <Icon className="size-4" />
      </div>
      <div>
        <p className="text-xl font-bold leading-none">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  )
}

export function ChannelsGrid({ channels, stats }: Props) {
  const queryClient = useQueryClient()
  const syncConnector = useSyncConnector()
  const syncOneCFull = useSyncFull()
  const [syncingId, setSyncingId] = useState<string | null>(null)

  function handleSync(channel: Channel) {
    if (channel.kind === 'connector' && channel.connectorId) {
      setSyncingId(channel.id)
      syncConnector.mutate(channel.connectorId, {
        onSuccess: (result) => {
          if (result.error) {
            toast.error(result.error)
          } else {
            toast.success(`Синхронизировано: ${result.entries.length} записей`)
          }
          queryClient.invalidateQueries({ queryKey: ['channels'] })
          queryClient.invalidateQueries({ queryKey: ['channel-stats'] })
          setSyncingId(null)
        },
        onError: () => {
          toast.error('Ошибка синхронизации')
          setSyncingId(null)
        },
      })
    } else if (channel.kind === 'oneC' && channel.connectionId) {
      setSyncingId(channel.id)
      syncOneCFull.mutate(channel.connectionId, {
        onSuccess: (result) => {
          const { created, updated } = result.stats
          toast.success(`1С: создано ${created}, обновлено ${updated} записей`)
          queryClient.invalidateQueries({ queryKey: ['channels'] })
          queryClient.invalidateQueries({ queryKey: ['channel-stats'] })
          setSyncingId(null)
        },
        onError: () => {
          toast.error('Ошибка синхронизации 1С')
          setSyncingId(null)
        },
      })
    }
  }

  return (
    <div className="space-y-6">
      {stats && (
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap gap-6 sm:gap-10">
              <StatBox icon={Radio} label="Каналов" value={stats.total} color="bg-primary/10 text-primary" />
              <StatBox icon={CheckCircle2} label="Активных" value={stats.active} color="bg-green-600/10 text-green-500" />
              <StatBox icon={AlertTriangle} label="Ошибок" value={stats.errors} color="bg-red-600/10 text-red-500" />
              <StatBox icon={FileText} label="Записей сегодня" value={stats.todayEntries} color="bg-blue-600/10 text-blue-500" />
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {channels.map((ch) => (
          <ChannelCard
            key={ch.id}
            channel={ch}
            onSync={ch.kind !== 'manual' ? handleSync : undefined}
            syncing={syncingId === ch.id}
          />
        ))}
      </div>
    </div>
  )
}
