/**
 * Мелкие куски форм настроек: текстовое поле с «пусто — по умолчанию», кнопка
 * «убрать» и раскрывашка «Подробнее» для технических полей.
 */
import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export function More({ children, подпись = 'Подробнее: ссылки на звуки и служебные поля' }: { children: ReactNode; подпись?: string }) {
  return (
    <details className="border-b border-border/60 py-3 last:border-0">
      <summary className="cursor-pointer text-sm text-muted-foreground">{подпись}</summary>
      <div className="pt-1">{children}</div>
    </details>
  )
}

export function TextInput({ значение, onChange, подпись, моно, className, placeholder }: {
  значение: string | undefined
  onChange: (v: string | undefined) => void
  подпись: string
  моно?: boolean
  className?: string
  placeholder?: string
}) {
  return (
    <Input value={значение ?? ''} aria-label={подпись} placeholder={placeholder}
      onChange={e => onChange(e.target.value === '' ? undefined : e.target.value)}
      className={cn('h-9', моно && 'font-mono text-xs', className ?? 'w-72 max-w-full')} />
  )
}

export function RemoveButton({ onClick, что }: { onClick: () => void; что: string }) {
  return (
    <Button variant="ghost" size="icon-xs" onClick={onClick} aria-label={`Убрать ${что}`} title={`Убрать ${что}`}>
      <X />
    </Button>
  )
}
