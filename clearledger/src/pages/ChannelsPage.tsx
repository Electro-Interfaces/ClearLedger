/**
 * Каналы данных — список pipeline-каналов.
 * Клик → /channels/:id (детальная страница с вкладками).
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { getChannels, deleteChannel } from '@/services/channelService'
import { getSources } from '@/services/sourceService'
import { getChannelSourceIds } from '@/types/channel'
import type { Channel } from '@/types/channel'
import { Plus, Trash2, Radio, Database, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'
import { ChannelWizard } from '@/components/channels/ChannelWizard'

const STATUS_MAP: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  active: { label: 'Активен', variant: 'default' },
  paused: { label: 'Пауза', variant: 'secondary' },
  error: { label: 'Ошибка', variant: 'destructive' },
  draft: { label: 'Черновик', variant: 'outline' },
}

/** Карточка канала в списке */
function ChannelListItem({ channel, onDelete }: { channel: Channel; onDelete: () => void }) {
  const navigate = useNavigate()
  const sources = getSources()
  const channelSourceIds = getChannelSourceIds(channel)
  const channelSources = sources.filter((s) => channelSourceIds.includes(s.id))
  const statusMeta = STATUS_MAP[channel.status] ?? STATUS_MAP.draft

  return (
    <Card className="cursor-pointer hover:bg-accent/30 transition-colors group"
      onClick={() => navigate(`/channels/${channel.id}`)}>
      <CardContent className="py-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 shrink-0">
            <Radio className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">{channel.name}</CardTitle>
              <Badge variant={statusMeta.variant} className="text-[10px]">{statusMeta.label}</Badge>
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <Database className="h-3 w-3" />
                {channelSources.length} источник{channelSources.length !== 1 ? 'ов' : ''}
              </span>
              <span>{channel.streams.filter((s) => s.enabled).length} потоков</span>
              {channel.lastSync && (
                <span>Синхр: {format(new Date(channel.lastSync), 'dd.MM.yyyy HH:mm')}</span>
              )}
              <span>Документов: {channel.docsLoaded}</span>
            </div>
            {channelSources.length > 0 && (
              <div className="flex items-center gap-1.5 mt-1.5">
                {channelSources.map((s) => (
                  <Badge key={s.id} variant="outline" className="text-[9px] h-4 px-1.5">
                    {s.name}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100"
              onClick={(e) => { e.stopPropagation(); onDelete() }}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
            <ChevronRight className="h-4 w-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>(getChannels)
  const [wizardOpen, setWizardOpen] = useState(false)
  const navigate = useNavigate()

  function refresh() { setChannels(getChannels()) }

  function handleDelete(id: string) {
    if (!confirm('Удалить обработку и все её данные?')) return
    deleteChannel(id)
    refresh()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Обработки данных</h1>
          <p className="text-sm text-muted-foreground">
            Комбинация источников → загрузка → сверка → результат
          </p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={() => setWizardOpen(true)}>
          <Plus className="h-4 w-4" />
          Создать обработку
        </Button>
      </div>

      <ChannelWizard open={wizardOpen} onOpenChange={(v) => { setWizardOpen(v); if (!v) refresh() }} />

      {channels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Radio className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Нет обработок</p>
            <p className="text-xs text-muted-foreground">
              Создайте обработку из шаблона или настройте вручную
            </p>
            <Button variant="default" size="sm" className="gap-1.5 mt-2" onClick={() => setWizardOpen(true)}>
              <Plus className="h-4 w-4" />
              Создать обработку
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {channels.map((ch) => (
            <ChannelListItem key={ch.id} channel={ch} onDelete={() => handleDelete(ch.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

export default ChannelsPage
