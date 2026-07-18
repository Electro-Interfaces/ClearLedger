/**
 * Диалог подтверждения тяжёлого / массового действия.
 *
 * Реализует правило 5 стандарта управления сложностью («ничего не применяем
 * молча») и §6.7 (предпросмотр до применения): перед необратимой массовой
 * мутацией пользователь видит, что именно произойдёт (сколько записей
 * затрагивается), и подтверждает.
 *
 * Обёртка вокруг shadcn AlertDialog — единый жест подтверждения по всему
 * приложению вместо разрозненных inline-диалогов и молчаливых onClick.
 */
import type { ReactNode } from 'react'
import {
  AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader,
  AlertDialogFooter, AlertDialogTitle, AlertDialogDescription,
  AlertDialogAction, AlertDialogCancel,
} from '@/components/ui/alert-dialog'

export function ConfirmActionDialog({
  trigger,
  title,
  description,
  confirmLabel = 'Подтвердить',
  cancelLabel = 'Отмена',
  onConfirm,
  destructive = false,
}: {
  /** Кнопка-триггер (рендерится через asChild). */
  trigger: ReactNode
  title: string
  /** Что именно произойдёт — предпросмотр последствий (строка/inline). */
  description: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  onConfirm: () => void
  destructive?: boolean
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className={destructive ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : undefined}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
