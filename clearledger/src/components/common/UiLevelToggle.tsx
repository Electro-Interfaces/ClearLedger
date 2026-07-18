/**
 * Переключатель режима работы: Простой ⇄ Расширенный.
 *
 * Сегменты, а не галочка: галочка «расширенный режим» не говорит, где ты
 * сейчас, а два сегмента показывают оба состояния и текущее из них.
 * Активный залит primary — единый язык выбора по всему приложению
 * (CLAUDE.md, «Иерархия управления рабочей области», правило 2).
 */
import { Gauge, Sparkles } from 'lucide-react'
import { useUiLevel, type UiLevel } from '@/hooks/useUiLevel'
import { cn } from '@/lib/utils'

const OPTIONS: { value: UiLevel; label: string; icon: typeof Gauge; hint: string }[] = [
  {
    value: 'simple',
    label: 'Простой',
    icon: Gauge,
    hint: 'Только то, что нужно каждый день. Ничего не отключается — редкое убрано с глаз.',
  },
  {
    value: 'advanced',
    label: 'Расширенный',
    icon: Sparkles,
    hint: 'Все функции приложения, включая экспертные настройки и редкие срезы.',
  },
]

export function UiLevelToggle({ className }: { className?: string }) {
  const { level, setLevel } = useUiLevel()

  return (
    <div
      role="radiogroup"
      aria-label="Режим работы"
      className={cn('inline-flex items-center gap-0.5 rounded-lg border bg-muted/60 p-0.5', className)}
    >
      {OPTIONS.map((o) => {
        const active = level === o.value
        const Icon = o.icon
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.hint}
            onClick={() => setLevel(o.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground',
            )}
          >
            <Icon className="size-3.5" />
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
