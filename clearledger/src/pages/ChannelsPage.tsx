/**
 * Каналы данных — список pipeline-каналов.
 * Клик → /channels/:id (детальная страница с вкладками).
 */

import { useState, useEffect, type ComponentType } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DimensionContractsPopover } from '@/components/reference/DimensionContractsPopover'
import { getChannels, loadChannels, deleteChannel } from '@/services/channelService'
import { getSources, loadSources } from '@/services/sourceService'
import { isApiEnabled } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { getChannelSourceIds } from '@/types/channel'
import type { Channel } from '@/types/channel'
import { Plus, Trash2, Radio, Database, Clock, Loader2, ArrowRightLeft, CheckCircle2, XCircle, Circle, PauseCircle } from 'lucide-react'
import { FuelMappingsPanel } from '@/components/fuel/FuelMappingsPanel'
import { format } from 'date-fns'
import { ConnectorWizard } from '@/components/channels/ConnectorWizard'
import { SpaceConnectors } from '@/components/channels/SpaceConnectors'
import { ScheduleOverview } from '@/components/channels/ScheduleOverview'
import { AdvancedOnly, AdvancedHint } from '@/components/common/AdvancedOnly'

const STATUS_MAP: Record<string, { label: string; cls: string; Icon: ComponentType<{ className?: string }> }> = {
  active: { label: 'Активен', cls: 'text-emerald-500', Icon: CheckCircle2 },
  paused: { label: 'Пауза', cls: 'text-amber-500', Icon: PauseCircle },
  error: { label: 'Ошибка', cls: 'text-destructive', Icon: XCircle },
  draft: { label: 'Черновик', cls: 'text-muted-foreground', Icon: Circle },
}

/** Карточка канала в списке */
function ChannelListItem({ channel, onDelete }: { channel: Channel; onDelete: () => void }) {
  const navigate = useNavigate()
  const sources = getSources()
  const channelSourceIds = getChannelSourceIds(channel)
  const channelSources = sources.filter((s) => channelSourceIds.includes(s.id))
  const st = STATUS_MAP[channel.status] ?? STATUS_MAP.draft
  const label = channelSources[0]?.name ?? 'Канал данных'
  const cuts = channel.streams.length
  const reconcilable = channel.streams.filter((s) => s.role === 'control').length

  return (
    <div onClick={() => navigate(`/channels/${channel.id}`)}
      className="group/head rounded-2xl border border-border/60 hover:border-border bg-card cursor-pointer p-4 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-di-surface-low shrink-0">
          <Radio className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="flex items-center gap-1">
          <span className={`flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide ${st.cls}`}>
            <st.Icon className="h-3.5 w-3.5" />
            {st.label}
          </span>
          <span onClick={(e) => e.stopPropagation()} className="opacity-0 group-hover/head:opacity-100 transition-opacity">
            <DimensionContractsPopover dimType="channel" dimRef={channel.id} />
          </span>
          <Button variant="ghost" size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-destructive opacity-0 group-hover/head:opacity-100 transition-opacity"
            onClick={(e) => { e.stopPropagation(); onDelete() }}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="mt-3">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70 truncate">{label}</div>
        <div className="mt-0.5 text-base font-bold tracking-tight truncate">{channel.name}</div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <Database className="h-3 w-3" />{channelSources.length} вход{channelSources.length === 1 ? '' : channelSources.length >= 2 && channelSources.length <= 4 ? 'а' : 'ов'}
          </span>
          <span>{cuts} разрез{cuts === 1 ? '' : 'ов'} учёта</span>
          {reconcilable > 0 && <span className="text-emerald-500">{reconcilable} сверяемых</span>}
          {/* docs_loaded накапливается ТОЛЬКО прогонами канала (channels_router:381),
              поэтому остаётся нулём, если данные пришли импортом или переносом.
              Голое «Документов: 0» рядом с непустой нормализацией читается как
              «данных нет» — показываем происхождение числа.
              Считать документы через getAllLoadedDocs() здесь НЕЛЬЗЯ: их кэш
              наполняется только при заходе внутрь канала, и в списке получалось
              «Документов нет» при 200 реально загруженных. */}
          {channel.docsLoaded > 0 ? (
            <span>Принято прогонами: {channel.docsLoaded}</span>
          ) : (
            <span
              className="text-muted-foreground/70"
              title="Счётчик считает документы, принятые прогонами этого канала. Данные могли попасть в систему другим путём — импортом или переносом. Что реально лежит в канале — на вкладке «Данные»."
            >
              Прогонов не было
            </span>
          )}
          {channel.lastSync && (
            <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{format(new Date(channel.lastSync), 'dd.MM HH:mm')}</span>
          )}
        </div>
      </div>
    </div>
  )
}

export function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>(getChannels)
  const [loading, setLoading] = useState(getChannels().length === 0)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const { companyId } = useCompany()
  const [searchParams, setSearchParams] = useSearchParams()

  function refresh() { setChannels(getChannels()) }

  // API-режим: гидрация из бэкенда. Каналы грузим первыми и показываем СРАЗУ,
  // не дожидаясь источников (раньше Promise.all держал список до загрузки обоих).
  useEffect(() => {
    let cancelled = false
    setLoading(getChannels().length === 0)
    loadChannels(companyId)
      .then(() => { if (!cancelled) refresh() })
      .catch(() => { /* офлайн → localStorage */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    // источники — параллельно, не блокируют показ каналов
    loadSources(companyId).then(() => { if (!cancelled) refresh() }).catch(() => {})
    return () => { cancelled = true }
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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold">Коннекторы</h1>
          <p className="text-sm text-muted-foreground">
            Подключения к системам → загрузка → сверка → результат
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Периодичность автозагрузки настраивают один раз — в простом режиме
              убрана. «Создать коннектор» остаётся: без неё раздел бессмыслен. */}
          <AdvancedHint count={1} what="настройка — расписание загрузок" />
          <AdvancedOnly>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setScheduleOpen(true)}>
              <Clock className="h-4 w-4" />
              Расписание
            </Button>
          </AdvancedOnly>
          <Button size="sm" className="gap-1.5" onClick={() => setWizardOpen(true)}>
            <Plus className="h-4 w-4" />
            Создать коннектор
          </Button>
        </div>
      </div>

      <ConnectorWizard open={wizardOpen} onOpenChange={(v) => { setWizardOpen(v); if (!v) refresh() }} />
      <ScheduleOverview open={scheduleOpen} onOpenChange={setScheduleOpen} />

      {/* Все источники пространства одним списком: свои каналы и живые интеграции
          соседних приложений. Ниже — настройка каналов этого продукта. */}
      {isApiEnabled() && <SpaceConnectors />}

      {/* Канонические маппинги компании — единый источник для всех каналов */}
      {isApiEnabled() && (
        <details className="rounded-lg border border-border/50 bg-card/40">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold flex items-center gap-2 select-none">
            <ArrowRightLeft className="h-4 w-4 text-muted-foreground shrink-0" />
            Маппинги компании (НСИ)
            <span className="text-xs font-normal text-muted-foreground ml-1">
              виды топлива · каналы оплаты — единый справочник, общий для всех каналов
            </span>
          </summary>
          <div className="px-4 pb-4 pt-1">
            <FuelMappingsPanel />
          </div>
        </details>
      )}

      {channels.length === 0 && loading ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 className="h-8 w-8 text-muted-foreground/40 animate-spin" />
            <p className="text-sm text-muted-foreground">Загрузка каналов…</p>
          </CardContent>
        </Card>
      ) : channels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Radio className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm font-medium">Пока нет коннекторов</p>
            <p className="max-w-md text-center text-xs text-muted-foreground">
              Коннектор подключает источник данных (STS, ЦБ, файлы) и превращает его в готовые
              документы. Создайте первый из шаблона или настройте вручную.
            </p>
            <Button variant="default" size="sm" className="gap-1.5 mt-2" onClick={() => setWizardOpen(true)}>
              <Plus className="h-4 w-4" />
              Создать коннектор
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
          {channels.map((ch) => (
            <ChannelListItem key={ch.id} channel={ch} onDelete={() => handleDelete(ch.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

export default ChannelsPage
