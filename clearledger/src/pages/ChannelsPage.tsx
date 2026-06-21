/**
 * Каналы данных — список pipeline-каналов.
 * Клик → /channels/:id (детальная страница с вкладками).
 */

import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, CardContent, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { DimensionContractsPopover } from '@/components/reference/DimensionContractsPopover'
import { getChannels, loadChannels, deleteChannel } from '@/services/channelService'
import { getSources, loadSources } from '@/services/sourceService'
import { useCompany } from '@/contexts/CompanyContext'
import { EnergyChannelsSection } from '@/components/pipeline/EnergyPipelineSections'
import { getChannelSourceIds } from '@/types/channel'
import type { Channel } from '@/types/channel'
import { Plus, Trash2, Radio, Database, ChevronRight, Clock } from 'lucide-react'
import { format } from 'date-fns'
import { ChannelWizard } from '@/components/channels/ChannelWizard'
import { ScheduleOverview } from '@/components/channels/ScheduleOverview'

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
            <span onClick={(e) => e.stopPropagation()}>
              <DimensionContractsPopover dimType="channel" dimRef={channel.id} />
            </span>
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
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const { companyId, company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const [searchParams, setSearchParams] = useSearchParams()

  function refresh() { setChannels(getChannels()) }

  // API-режим: гидрация источников+каналов из бэкенда при монтировании
  useEffect(() => {
    void Promise.all([loadSources(companyId), loadChannels(companyId)])
      .then(refresh).catch(() => { /* офлайн → localStorage */ })
  }, [companyId])

  // Переход из каталога: ?wizard=1 → открыть мастер создания канала
  useEffect(() => {
    if (searchParams.get('wizard')) {
      setWizardOpen(true)
      searchParams.delete('wizard')
      setSearchParams(searchParams, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleDelete(id: string) {
    if (!confirm('Удалить канал и все его данные?')) return
    await deleteChannel(id)
    refresh()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Каналы данных</h1>
          <p className="text-sm text-muted-foreground">
            {isEnergy
              ? 'Каналы выводятся от подключённых разрезов учёта (разрез → каналы).'
              : 'Комбинация источников → загрузка → сверка → результат'}
          </p>
        </div>
        {!isEnergy && (
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setScheduleOpen(true)}>
            <Clock className="h-4 w-4" />
            Расписание
          </Button>
          <Button size="sm" className="gap-1.5" onClick={() => setWizardOpen(true)}>
            <Plus className="h-4 w-4" />
            Создать канал
          </Button>
        </div>
        )}
      </div>

      <ChannelWizard open={wizardOpen} onOpenChange={(v) => { setWizardOpen(v); if (!v) refresh() }} />
      <ScheduleOverview open={scheduleOpen} onOpenChange={setScheduleOpen} />

      {isEnergy ? (
        <EnergyChannelsSection />
      ) : channels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Radio className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Нет обработок</p>
            <p className="text-xs text-muted-foreground">
              Создайте канал из шаблона или настройте вручную
            </p>
            <Button variant="default" size="sm" className="gap-1.5 mt-2" onClick={() => setWizardOpen(true)}>
              <Plus className="h-4 w-4" />
              Создать канал
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
