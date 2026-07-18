/**
 * Диалог «Расписание» — обзор и настройка схемы загрузки для всех обработок.
 */

import { useState } from 'react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { getChannels, updateChannel } from '@/services/channelService'
import { getSources } from '@/services/sourceService'
import {
  getChannelSourceIds,
  getChannelStations,
  DEFAULT_SCHEDULE,
  INTERVAL_OPTIONS,
} from '@/types/channel'
import type { Channel, ScheduleConfig, ScheduleMode } from '@/types/channel'
import { format } from 'date-fns'
import { toast } from 'sonner'
import {
  Radio,
  ArrowRight,
  Clock,
  Pause,
  AlertCircle,
  CheckCircle2,
  Database,
  Fuel,
  Activity,
  Settings2,
  Save,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'

function getSchedule(ch: Channel): ScheduleConfig {
  if (typeof ch.schedule === 'string' || !ch.schedule) return { ...DEFAULT_SCHEDULE }
  return ch.schedule
}

const STATUS_COLORS: Record<string, string> = {
  active: 'text-green-500',
  draft: 'text-muted-foreground',
  paused: 'text-yellow-500',
  error: 'text-red-500',
}
const STATUS_ICONS: Record<string, typeof CheckCircle2> = {
  active: CheckCircle2,
  draft: Clock,
  paused: Pause,
  error: AlertCircle,
}

function ChannelCard({
  channel,
  onUpdate,
}: {
  channel: Channel
  onUpdate: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [schedule, setSchedule] = useState<ScheduleConfig>(getSchedule(channel))
  const [dirty, setDirty] = useState(false)

  const sources = getSources()
  const chSources = sources.filter((s) => getChannelSourceIds(channel).includes(s.id))
  const stations = getChannelStations(channel)
  const enabledStreams = channel.streams.filter((s) => s.enabled)
  const StatusIcon = STATUS_ICONS[channel.status] ?? Clock

  function patch(partial: Partial<ScheduleConfig>) {
    setSchedule((prev) => ({ ...prev, ...partial }))
    setDirty(true)
  }

  function handleSave() {
    updateChannel(channel.id, { schedule })
    setDirty(false)
    onUpdate()
    toast.success(`Расписание «${channel.name}» сохранено`, {
      description: 'Автозапуск по расписанию ещё не активен — загрузка выполняется вручную.',
    })
  }

  function modeLabel(mode: ScheduleMode) {
    if (mode === 'manual') return 'Вручную'
    if (mode === 'interval') return 'По интервалу'
    return 'Cron'
  }

  return (
    <div className="rounded-lg border bg-card">
      {/* Header row */}
      <div
        className="flex items-center gap-3 p-4 cursor-pointer hover:bg-accent/30 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <Radio className="h-4 w-4 text-primary shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{channel.name}</span>
            <StatusIcon className={`h-3.5 w-3.5 ${STATUS_COLORS[channel.status] ?? ''}`} />
            <Badge variant="outline" className="text-[10px]">
              {modeLabel(schedule.mode)}
              {schedule.mode === 'interval' && schedule.intervalMinutes
                ? ` (${schedule.intervalMinutes} мин)`
                : ''}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
          <span>{channel.docsLoaded} док.</span>
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </div>

      {/* Pipeline + schedule settings (expanded) */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          <Separator />

          {/* Pipeline: Source → Streams → Stations */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Схема загрузки
            </p>
            <div className="flex items-start gap-3 flex-wrap">
              {/* Source */}
              <div className="flex flex-col gap-1">
                {chSources.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center gap-1.5 rounded-md bg-blue-500/10 border border-blue-500/20 px-2.5 py-1.5"
                  >
                    <Database className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                    <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
                      {s.name}
                    </span>
                  </div>
                ))}
              </div>

              <ArrowRight className="h-4 w-4 text-muted-foreground/40 mt-2 shrink-0" />

              {/* Streams */}
              <div className="flex flex-col gap-1">
                {enabledStreams.map((st) => (
                  <div
                    key={st.id}
                    className="flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/20 px-2.5 py-1.5"
                  >
                    <Activity className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                    <span className="text-xs">{st.name}</span>
                  </div>
                ))}
              </div>

              <ArrowRight className="h-4 w-4 text-muted-foreground/40 mt-2 shrink-0" />

              {/* Stations */}
              <div className="flex flex-col gap-1">
                {stations.length > 0 ? (
                  stations.map((st) => (
                    <div
                      key={`${st.systemId}-${st.code}`}
                      className="flex items-center gap-1.5 rounded-md bg-green-500/10 border border-green-500/20 px-2.5 py-1.5"
                    >
                      <Fuel className="h-3.5 w-3.5 text-green-600 shrink-0" />
                      <span className="text-xs">
                        {st.name ?? `АЗС ${st.code}`}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="rounded-md bg-muted/50 border px-2.5 py-1.5">
                    <span className="text-xs text-muted-foreground">Все станции</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <Separator />

          {/* Schedule config */}
          <div className="space-y-3">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
              <Settings2 className="h-3.5 w-3.5" />
              Настройка расписания
            </p>

            <div className="grid grid-cols-2 gap-3">
              {/* Mode */}
              <div className="space-y-1.5">
                <Label className="text-xs">Режим загрузки</Label>
                <Select
                  value={schedule.mode}
                  onValueChange={(v) => patch({ mode: v as ScheduleMode })}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Вручную</SelectItem>
                    <SelectItem value="interval">По интервалу</SelectItem>
                    <SelectItem value="cron">Cron-расписание</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Interval */}
              {schedule.mode === 'interval' && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Интервал</Label>
                  <Select
                    value={String(schedule.intervalMinutes ?? 60)}
                    onValueChange={(v) => patch({ intervalMinutes: Number(v) })}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INTERVAL_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={String(opt.value)}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Cron */}
              {schedule.mode === 'cron' && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Cron-выражение</Label>
                  <Input
                    className="h-8 text-xs font-mono"
                    placeholder="0 */2 * * *"
                    value={schedule.cronExpression ?? ''}
                    onChange={(e) => patch({ cronExpression: e.target.value })}
                  />
                </div>
              )}
            </div>

            {/* Active hours + options */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Активные часы (от)</Label>
                <Input
                  type="time"
                  className="h-8 text-xs"
                  value={schedule.activeHoursFrom ?? ''}
                  onChange={(e) => patch({ activeHoursFrom: e.target.value || undefined })}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Активные часы (до)</Label>
                <Input
                  type="time"
                  className="h-8 text-xs"
                  value={schedule.activeHoursTo ?? ''}
                  onChange={(e) => patch({ activeHoursTo: e.target.value || undefined })}
                />
              </div>
            </div>

            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <Checkbox
                  checked={schedule.pauseOnError}
                  onCheckedChange={(v) => patch({ pauseOnError: !!v })}
                />
                Пауза при ошибках
              </label>
              <div className="flex items-center gap-2">
                <Label className="text-xs whitespace-nowrap">Повторов при ошибке:</Label>
                <Input
                  type="number"
                  min={0}
                  max={10}
                  className="h-7 w-16 text-xs"
                  value={schedule.maxRetries}
                  onChange={(e) => patch({ maxRetries: Number(e.target.value) || 0 })}
                />
              </div>
            </div>

            {/* Save + status line */}
            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                {channel.lastSync && (
                  <span>Синхр: {format(new Date(channel.lastSync), 'dd.MM HH:mm')}</span>
                )}
                {schedule.mode !== 'manual' && (
                  <span className="text-muted-foreground/70">Автозапуск не активен</span>
                )}
              </div>
              {dirty && (
                <Button size="sm" className="h-7 text-xs gap-1.5" onClick={handleSave}>
                  <Save className="h-3.5 w-3.5" />
                  Сохранить
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
}

export function ScheduleOverview({ open, onOpenChange }: Props) {
  const [channels, setChannels] = useState(getChannels)

  function refresh() {
    setChannels(getChannels())
  }

  const autoCount = channels.filter((ch) => {
    const s = getSchedule(ch)
    return s.mode !== 'manual'
  }).length

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Расписание загрузки данных
          </SheetTitle>
          <p className="text-sm text-muted-foreground">
            {channels.length} обработок, {autoCount} с настроенным расписанием
          </p>
        </SheetHeader>

        <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          Автозапуск по расписанию ещё не реализован. Настройки ниже сохраняются на будущее,
          но загрузка сейчас выполняется только вручную — кнопкой «Загрузить» в карточке обработки.
        </div>

        <Separator className="my-4" />

        {channels.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2 text-muted-foreground">
            <Radio className="h-8 w-8 opacity-30" />
            <p className="text-sm">Нет обработок</p>
          </div>
        ) : (
          <div className="space-y-3">
            {channels.map((ch) => (
              <ChannelCard key={ch.id} channel={ch} onUpdate={refresh} />
            ))}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
