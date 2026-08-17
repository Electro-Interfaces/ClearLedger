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
import { useState, type MouseEvent, type ReactNode } from 'react'
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
  content,
  confirmDisabled = false,
  pending: externalPending = false,
  pendingLabel = 'Выполняем…',
  onOpenChange,
}: {
  /** Кнопка-триггер (рендерится через asChild). */
  trigger: ReactNode
  title: string
  /** Что именно произойдёт — предпросмотр последствий (строка/inline). */
  description: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  onConfirm: () => void | Promise<unknown>
  destructive?: boolean
  content?: ReactNode
  confirmDisabled?: boolean
  pending?: boolean
  pendingLabel?: string
  onOpenChange?: (open: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const [internalPending, setInternalPending] = useState(false)
  const pending = externalPending || internalPending
  const changeOpen = (next: boolean) => {
    if (pending && !next) return
    setOpen(next)
    onOpenChange?.(next)
  }
  const confirm = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    if (pending || confirmDisabled) return
    setInternalPending(true)
    try {
      await onConfirm()
      setOpen(false)
      onOpenChange?.(false)
    } catch {
      // Ошибку показывает мутация; диалог остаётся открыт для повторной попытки.
    } finally {
      setInternalPending(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={changeOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {content}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            onClick={confirm}
            disabled={pending || confirmDisabled}
            aria-busy={pending}
            className={destructive ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : undefined}
          >
            {pending ? pendingLabel : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
