import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ScheduleConfig, ScheduleMode } from '@/types/channel'
import { INTERVAL_OPTIONS } from '@/types/channel'

interface Props {
  config: ScheduleConfig
  onChange: (config: ScheduleConfig) => void
}

export function ChannelScheduleForm({ config, onChange }: Props) {
  function set<K extends keyof ScheduleConfig>(key: K, value: ScheduleConfig[K]) {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="space-y-5">
      {/* Mode selection */}
      <div className="space-y-2">
        {([
          { value: 'manual' as ScheduleMode, label: 'Вручную', desc: 'Загружать по кнопке' },
          { value: 'interval' as ScheduleMode, label: 'По интервалу', desc: 'Автоматически с заданной частотой' },
          { value: 'cron' as ScheduleMode, label: 'По расписанию', desc: 'Cron-выражение' },
        ]).map((opt) => (
          <label
            key={opt.value}
            className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
              config.mode === opt.value ? 'bg-primary/10' : 'hover:bg-accent/40'
            }`}
          >
            <input
              type="radio"
              name="scheduleMode"
              value={opt.value}
              checked={config.mode === opt.value}
              onChange={() => set('mode', opt.value)}
              className="mt-0.5 accent-primary"
            />
            <div>
              <div className="text-sm font-medium">{opt.label}</div>
              <div className="text-xs text-muted-foreground">{opt.desc}</div>
            </div>
          </label>
        ))}
      </div>

      {/* Interval settings */}
      {config.mode === 'interval' && (
        <div>
          <Label className="text-sm mb-1.5 block">Частота</Label>
          <Select
            value={String(config.intervalMinutes ?? 60)}
            onValueChange={(v) => set('intervalMinutes', Number(v))}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {INTERVAL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)}>{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Cron expression */}
      {config.mode === 'cron' && (
        <div>
          <Label className="text-sm mb-1.5 block">Cron-выражение</Label>
          <Input
            value={config.cronExpression ?? ''}
            onChange={(e) => set('cronExpression', e.target.value)}
            placeholder="0 8 * * *"
            className="font-mono"
          />
          <p className="text-xs text-muted-foreground mt-1">Например: 0 8 * * * = каждый день в 08:00</p>
        </div>
      )}

      {/* Active hours */}
      {config.mode !== 'manual' && (
        <div>
          <Label className="text-sm mb-1.5 block">Активные часы</Label>
          <div className="grid grid-cols-2 gap-3">
            <Input
              type="time"
              value={config.activeHoursFrom ?? ''}
              onChange={(e) => set('activeHoursFrom', e.target.value)}
              placeholder="С"
            />
            <Input
              type="time"
              value={config.activeHoursTo ?? ''}
              onChange={(e) => set('activeHoursTo', e.target.value)}
              placeholder="По"
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1">Оставьте пустым для круглосуточной работы</p>
        </div>
      )}

      {/* Pause on error */}
      {config.mode !== 'manual' && (
        <label className="flex items-center gap-2 cursor-pointer">
          <Checkbox
            checked={config.pauseOnError}
            onCheckedChange={(v) => set('pauseOnError', !!v)}
          />
          <span className="text-sm">Пауза при ошибках</span>
        </label>
      )}
    </div>
  )
}
