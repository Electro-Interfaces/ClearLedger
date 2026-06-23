/**
 * Энергоцепочка на страницах «Источники» и «Каналы»: содержимое выводится ОБРАТНО
 * от подключённых разрезов учёта (разрез → каналы → источники). Единый источник
 * правды — config/energyPipeline.ts. Профиль energy наполняет пустые страницы.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Upload } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { loadChannels } from '@/services/channelService'
import {
  ALL_ENERGY_CUT_IDS, ENERGY_CHANNELS, PIPE_STATUS_META,
  neededSources, neededChannels, cutsForSource, cutsForChannel, energySource,
} from '@/config/energyPipeline'
import type { PipeStatus } from '@/config/energyPipeline'

/** Резолв id операционного backend-канала по template_id (для перехода на загрузку+обработку). */
function useBackendChannelId(templateId: string): string | null {
  const { companyId } = useCompany()
  const [id, setId] = useState<string | null>(null)
  useEffect(() => {
    if (!companyId) return
    loadChannels(companyId)
      .then((chs) => setId(chs.find((c) => c.templateId === templateId)?.id ?? null))
      .catch(() => { /* офлайн */ })
  }, [companyId, templateId])
  return id
}

/** Бейдж статуса элемента энергоцепочки (источник/канал): demo — нейтрально-позитивно, planned — приглушённо. */
function StatusBadge({ status, className }: { status: PipeStatus; className?: string }) {
  const meta = PIPE_STATUS_META[status]
  return <Badge variant="secondary" className={`text-[10px] ${meta.cls} ${className ?? ''}`}>{meta.label}</Badge>
}

export function EnergySourcesSection() {
  const sources = neededSources(ALL_ENERGY_CUT_IDS)
  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <p className="text-xs text-muted-foreground">
          Источники выводятся обратно от подключённых разрезов учёта (разрез → каналы → источники):
          {' '}{sources.length} источников под {ALL_ENERGY_CUT_IDS.length} разрезов.
        </p>
        {sources.map((s) => {
          const ch = ENERGY_CHANNELS.find((c) => c.sourceId === s.id)
          const cuts = cutsForSource(s.id)
          return (
            <div key={s.id} className="rounded-md border border-border/50 p-3">
              <div className="mb-1 flex items-center gap-2">
                <span className="text-sm font-medium">{s.label}</span>
                <Badge variant="outline" className="text-[10px]">{s.level === 'station' ? 'станция' : 'компания'}</Badge>
                <StatusBadge status={s.status} className="ml-auto" />
              </div>
              <div className="text-xs text-muted-foreground">Потоки: {s.streams.join(' · ')}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span>→ {ch?.label ?? '—'}</span>
                <span className="text-muted-foreground/60">· питает разрезы:</span>
                {cuts.map((c) => <Badge key={c.id} variant="outline" className="text-[10px]">{c.label}</Badge>)}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

export function EnergyChannelsSection() {
  const channels = neededChannels(ALL_ENERGY_CUT_IDS)
  const navigate = useNavigate()
  const reestrChannelId = useBackendChannelId('reestr_contracts_payments')
  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <p className="text-xs text-muted-foreground">
          Каналы выводятся обратно от подключённых разрезов учёта (разрез → каналы):
          {' '}{channels.length} каналов нормализации.
        </p>
        {channels.map((ch) => {
          const src = energySource(ch.sourceId)
          const cuts = cutsForChannel(ch.id)
          return (
            <div key={ch.id} className="rounded-md border border-border/50 p-3">
              <div className="mb-1 flex items-center gap-2">
                <span className="text-sm font-medium">{ch.label}</span>
                <StatusBadge status={ch.status} className="ml-auto" />
              </div>
              <div className="text-xs text-muted-foreground">
                Источник: <span className="text-foreground">{src?.label ?? ch.sourceId}</span> · {ch.produces}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span>питает разрезы:</span>
                {cuts.map((c) => <Badge key={c.id} variant="outline" className="text-[10px]">{c.label}</Badge>)}
              </div>
              {ch.id === 'ch_reestr' && reestrChannelId && (
                <div className="mt-2 border-t border-border/40 pt-2">
                  <Button size="sm" className="h-7 gap-1.5 text-xs"
                    onClick={() => navigate(`/channels/${reestrChannelId}`)}>
                    <Upload className="h-3.5 w-3.5" />
                    Загрузить таблицу и запустить обработку
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
