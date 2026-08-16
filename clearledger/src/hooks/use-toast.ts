/**
 * Адаптер `useToast` поверх общего тостера пространства (sonner).
 *
 * В пространстве один тостер — `sonner`, и подключён он один раз в `App`. Но часть
 * экранов написана в стиле shadcn-хука `useToast({ title, description, variant })`,
 * и без этого файла сборка фронта падала целиком: модуль просто не существовал.
 *
 * Заводить второй тостер ради другого интерфейса нельзя — на экране появились бы
 * две системы уведомлений с разным поведением. Поэтому здесь только перевод
 * вызова: заголовок становится текстом, описание — подписью, `destructive` —
 * ошибкой.
 */
import { toast as sonner } from 'sonner'

export interface ToastInput {
  title?: string
  description?: string
  variant?: 'default' | 'destructive'
}

export function useToast() {
  return {
    toast: ({ title, description, variant }: ToastInput) => {
      const text = title || description || ''
      const opts = title && description ? { description } : undefined
      return variant === 'destructive'
        ? sonner.error(text, opts)
        : sonner.success(text, opts)
    },
    dismiss: (id?: string | number) => sonner.dismiss(id),
  }
}

/** Прямой вызов без хука — для мест вне компонентов. */
export const toast = (input: ToastInput) => {
  const text = input.title || input.description || ''
  const opts = input.title && input.description ? { description: input.description } : undefined
  return input.variant === 'destructive' ? sonner.error(text, opts) : sonner.success(text, opts)
}
