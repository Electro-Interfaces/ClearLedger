/**
 * Переключатель режима работы: Простой ⇄ Расширенный.
 *
 * Сегменты, а не галочка: галочка «расширенный режим» не говорит, где ты
 * сейчас, а два сегмента показывают оба состояния и текущее из них.
 * Активный залит primary — единый язык выбора по всему приложению
 * (CLAUDE.md, «Иерархия управления рабочей области», правило 2).
 */
import { Gauge, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
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

/**
 * Компактный вариант для шапки — одна иконка рядом с лампочкой гид-режима.
 *
 * Два родственных инструмента стоят рядом осознанно: лампочка объясняет,
 * ГДЕ что находится, режим убирает лишнее с глаз. Первое лечит непонимание,
 * второе — перегрузку.
 *
 * Подсветка активного состояния повторяет лампочку (bg-primary/10 text-primary),
 * чтобы «включённый режим» читался одинаково у обоих.
 */
export function UiLevelHeaderButton() {
  const { isAdvanced, toggle } = useUiLevel()
  const Icon = isAdvanced ? Sparkles : Gauge

  // Без подтверждения переключатель кажется сломанным: на экранах, где скрывать
  // нечего, видимых изменений нет, и человек жмёт кнопку впустую.
  function handleToggle() {
    const next = isAdvanced ? 'простой' : 'расширенный'
    toggle()
    toast.success(`Режим: ${next}`, {
      description: isAdvanced
        ? 'Редкие настройки убраны с глаз. Там, где что-то скрыто, стоит пометка.'
        : 'Показаны все функции, включая экспертные настройки.',
    })
  }

  return (
    <button
      type="button"
      aria-pressed={isAdvanced}
      aria-label={isAdvanced ? 'Расширенный режим включён' : 'Простой режим включён'}
      onClick={handleToggle}
      title={isAdvanced
        ? 'Расширенный режим: показаны все функции. Нажмите, чтобы упростить экран'
        : 'Простой режим: на экранах только ежедневное. Нажмите, чтобы открыть все функции'}
      className={cn(
        'inline-flex h-10 w-10 items-center justify-center rounded-xl transition-colors',
        isAdvanced
          ? 'bg-primary/10 text-primary hover:bg-primary/15'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      <Icon className="h-[18px] w-[18px]" />
    </button>
  )
}

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
