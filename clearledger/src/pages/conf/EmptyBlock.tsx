/** Пустое состояние раздела: значок, фраза о том, что здесь бывает, и как это завести. */
import type { LucideIcon } from 'lucide-react'

export function EmptyBlock({ иконка: Иконка, текст, подсказка }: {
  иконка: LucideIcon
  текст: string
  подсказка?: string
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10">
        <Иконка className="h-7 w-7 text-primary" />
      </div>
      <p className="text-sm font-medium">{текст}</p>
      {подсказка && <p className="max-w-sm text-xs text-muted-foreground">{подсказка}</p>}
    </div>
  )
}
