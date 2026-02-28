import { useParams, Link, Navigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useChannels } from '@/hooks/useChannels'
import { useOneCConnections } from '@/hooks/useOneCSync'
import { OneCConnectionForm } from '@/components/settings/OneCConnectionForm'
import { OneCSyncStatus } from '@/components/settings/OneCSyncStatus'
import { OneCSyncHistory } from '@/components/settings/OneCSyncHistory'

function OneCChannelDetail({ connectionId }: { connectionId: string }) {
  const { data: connections } = useOneCConnections()
  const connection = connections?.find((c) => c.id === connectionId)

  if (!connection) {
    return <div className="text-center py-12 text-muted-foreground">Подключение 1С не найдено</div>
  }

  return (
    <div className="space-y-4">
      <OneCConnectionForm />
      <OneCSyncStatus connectionId={connection.id} exchangePath={connection.exchangePath} />
      <OneCSyncHistory connectionId={connection.id} />
    </div>
  )
}

function ManualChannelDetail() {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border p-6 text-center space-y-2">
        <p className="text-lg font-medium">Ручная загрузка</p>
        <p className="text-sm text-muted-foreground">
          Документы загружаются через страницу «Загрузить» — перетаскивание файлов, фото или ручной ввод.
        </p>
        <Link to="/input" className="inline-block mt-3 text-primary hover:underline text-sm">
          Перейти к загрузке
        </Link>
      </div>
    </div>
  )
}

export function ChannelDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: channels, isLoading } = useChannels()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!id) return <Navigate to="/channels" replace />

  const channel = channels?.find((c) => c.id === id)

  if (!channel) {
    return (
      <div className="space-y-4">
        <Link to="/channels" className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Назад к каналам
        </Link>
        <div className="text-center py-12 text-muted-foreground">Канал не найден</div>
      </div>
    )
  }

  // Коннектор — редирект на существующую страницу ConnectorDetailPage
  if (channel.kind === 'connector' && channel.connectorId) {
    return <Navigate to={`/connectors/${channel.connectorId}`} replace />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/channels" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <h1 className="text-2xl font-bold">{channel.name}</h1>
      </div>

      {channel.kind === 'oneC' && channel.connectionId && (
        <OneCChannelDetail connectionId={channel.connectionId} />
      )}

      {channel.kind === 'manual' && <ManualChannelDetail />}
    </div>
  )
}
