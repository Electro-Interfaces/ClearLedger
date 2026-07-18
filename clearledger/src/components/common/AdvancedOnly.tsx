/**
 * Обёртки для функций, которые в простом режиме убираются с глаз.
 *
 * ⚠ Что сюда НЕЛЬЗЯ заворачивать (правило 1 из useUiLevel): всё, от чего
 * зависит правильность числа — профиль НДС, ключ привязки, метод
 * себестоимости, баннеры демо-данных, предупреждения о расхождениях.
 * Прятать удобное — экономия внимания; прятать основание числа — инцидент.
 *
 * Годится сюда: редкие настройки, экспертные срезы, отладочные источники,
 * массовые операции «для тех, кто знает, что делает».
 */
import type { ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import { useUiLevel } from '@/hooks/useUiLevel'
import { Button } from '@/components/ui/button'

/** Показывает детей только в расширенном режиме. */
export function AdvancedOnly({ children }: { children: ReactNode }) {
  const { isAdvanced } = useUiLevel()
  return isAdvanced ? <>{children}</> : null
}

/** Показывает детей только в простом режиме (подсказки, укороченные варианты). */
export function SimpleOnly({ children }: { children: ReactNode }) {
  const { isSimple } = useUiLevel()
  return isSimple ? <>{children}</> : null
}

/**
 * Строка «здесь есть ещё N настроек» с переходом в расширенный режим.
 *
 * Ставится РЯДОМ с местом, где что-то скрыто, — тогда скрытие перестаёт быть
 * тихим: человек видит, что функция существует, и знает, как её достать.
 * Без такой пометки простой режим превращается в «фичи пропали».
 */
export function AdvancedHint({ count, what = 'настройки' }: { count: number; what?: string }) {
  const { isSimple, setLevel } = useUiLevel()
  if (!isSimple || count <= 0) return null

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Sparkles className="size-3.5 shrink-0 opacity-70" />
      <span>
        Ещё {count} {what} — в расширенном режиме
      </span>
      <Button
        variant="link"
        size="sm"
        className="h-auto p-0 text-xs"
        onClick={() => setLevel('advanced')}
      >
        Включить
      </Button>
    </div>
  )
}
