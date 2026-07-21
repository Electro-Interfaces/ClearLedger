/**
 * Переключатель часового пояса для анализа «по времени суток»: МСК ⇄ Местное.
 *
 * По умолчанию МСК (сессии ЭЗС хранятся в московском времени). «Местное» сдвигает
 * час/день недели на часовой пояс региона станции (regions.msk_offset) — тогда
 * профиль читается как «во сколько по-местному заряжаются», а не по Москве.
 * Актуально для сети от Калининграда до Камчатки (до +9 часов от МСК).
 *
 * Единый язык активного выбора — залитый primary (как табы вида/ClientTypeToggle).
 */
import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'

export type Tz = 'msk' | 'local'

export function TzToggle({ value, onChange, className }: {
  value: Tz
  onChange: (tz: Tz) => void
  className?: string
}) {
  const opts: { key: Tz; label: string; title: string }[] = [
    { key: 'msk', label: 'МСК', title: 'Московское время (как хранится)' },
    { key: 'local', label: 'Местное', title: 'Местное время станции (сдвиг на часовой пояс региона)' },
  ]
  return (
    <div className={cn('inline-flex items-center gap-1', className)}>
      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
      <div className="inline-flex rounded-md border bg-muted/60 p-0.5">
        {opts.map((o) => (
          <button
            key={o.key}
            type="button"
            title={o.title}
            onClick={() => onChange(o.key)}
            className={cn(
              'px-2.5 py-1 text-xs rounded-[5px] transition-colors',
              value === o.key
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}
