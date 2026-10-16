/**
 * Общие куски экранов «Телефонии»: заголовок раздела, показатель, метки звонка,
 * сообщение об ошибке узла и запрос причины доступа к ПДн.
 */
import { useState, type ReactNode } from 'react'
import { AlertTriangle, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { ФЛАГ } from './format'

/** Заголовок раздела: имя пункта меню, справа — действия раздела. */
export function Heading({ имя, подпись, children }: { имя: string; подпись?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="mr-auto min-w-0">
        <h1 className="font-headline text-lg font-semibold">{имя}</h1>
        {подпись && <p className="text-xs text-muted-foreground">{подпись}</p>}
      </div>
      {children}
    </div>
  )
}

/** Число с подписью; `пояснение` расшифровывает сокращение (SL, ASA) в подсказке. */
export function Stat({ имя, значение, пояснение, тон }: {
  имя: string
  значение: string
  пояснение?: string
  тон?: 'warning' | 'destructive' | 'success'
}) {
  return (
    <div title={пояснение} className="min-w-28">
      <p className="text-xs text-muted-foreground">{имя}</p>
      <p className={cn('font-headline text-xl font-semibold tabular-nums',
        тон === 'warning' && 'text-warning', тон === 'destructive' && 'text-destructive',
        тон === 'success' && 'text-success')}>
        {значение}
      </p>
    </div>
  )
}

/** Метки звонка: VIP, повтор, вне часов. Нейтральные — это признак, а не статус. */
export function Flags({ флаги }: { флаги?: string[] }) {
  if (!флаги?.length) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {флаги.map(ф => (
        <span key={ф} className={cn('rounded-md border px-1.5 text-xs leading-5',
          ф === 'vip' ? 'border-amber-400/50 text-amber-600 dark:text-amber-300/80' : 'border-border text-muted-foreground')}>
          {ФЛАГ[ф] ?? ф}
        </span>
      ))}
    </span>
  )
}

/** Ошибка запроса к узлу — словами и с тем, что делать. */
export function NodeError({ ошибка, что }: { ошибка: unknown; что: string }) {
  const текст = voice.узелНедоступен(ошибка) ? 'узел не отвечает'
    : ошибка instanceof Error ? ошибка.message : 'неизвестная ошибка'
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <p>Не удалось {что}: {текст}.</p>
    </div>
  )
}

const ПРИЧИНЫ = ['Жалоба звонящего', 'Разбор спорного звонка', 'Проверка качества обслуживания', 'Запрос заказчика']

/**
 * Запрос причины перед номером, записью или расшифровкой. Причина обязательна:
 * узел пишет её в журнал доступа, а без неё отвечает отказом. Частые причины —
 * кнопками, чтобы не набирать одно и то же каждый раз.
 */
export function ReasonDialog({ открыт, заголовок, действие, onClose, onSubmit }: {
  открыт: boolean
  заголовок: string
  действие: string
  onClose: () => void
  onSubmit: (причина: string) => Promise<void> | void
}) {
  const [причина, setПричина] = useState('')
  const [идёт, setИдёт] = useState(false)
  const годна = причина.trim().length >= 3

  async function отправить() {
    if (!годна) return
    setИдёт(true)
    try {
      await onSubmit(причина.trim())
      setПричина('')
      onClose()
    } finally {
      setИдёт(false)
    }
  }

  return (
    <Dialog open={открыт} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{заголовок}</DialogTitle>
          <DialogDescription className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            Причина попадёт в журнал доступа узла вместе с вашим именем и временем.
            Её увидит каждый, кто откроет этот звонок.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-1.5">
          {ПРИЧИНЫ.map(п => (
            <button key={п} type="button" onClick={() => setПричина(п)}
              aria-pressed={причина === п}
              className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
                причина === п ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent/50')}>
              {п}
            </button>
          ))}
        </div>
        <Textarea value={причина} onChange={e => setПричина(e.target.value)} maxLength={500}
          aria-label="Причина" placeholder="Например: звонящий жалуется, что его не соединили" rows={3} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={отправить} disabled={!годна || идёт}>
            {идёт ? 'Открываем…' : действие}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
