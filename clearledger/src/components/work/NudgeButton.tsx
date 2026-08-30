/**
 * «Подтолкнуть» — напомнить о работе тому, у кого она стоит.
 *
 * Самое частое, что нужно надзирающему: виза висит четвёртый день, и до сих пор
 * у него было два пути — написать в чат руками (и потерять это из истории
 * предмета) или отобрать работу (слишком). Здесь середина: напомнить адресно,
 * оставив след.
 *
 * Кого толкать, решает сервер, а не нажимающий: у поручения это исполнитель, у
 * документа в круге — те, кто держит визу сейчас. Выбор адресата руками означал
 * бы, что можно толкнуть не того.
 */
import { useMutation } from '@tanstack/react-query'
import { BellRing, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import * as workService from '@/services/workService'
import { cn } from '@/lib/utils'

export function NudgeButton({ companyId, targetRef, className, compact }: {
  companyId: string
  /** `task:<uuid>` или `doc:<uuid>`. */
  targetRef: string
  className?: string
  /** В плотной строке — только значок; подпись остаётся доступной. */
  compact?: boolean
}) {
  const толкнуть = useMutation({
    mutationFn: () => workService.nudge(companyId, targetRef),
    onSuccess: (r) => {
      // Сколько человек получили: у документа в круге их бывает несколько, и
      // «напомнили» без числа не отвечает на вопрос «кому».
      toast.success(r.sent === 0
        ? 'Напоминать было некому'
        : `Напомнили: ${r.sent} чел.`)
    },
    // Отказ объясняет правило («напоминать некому: исполнитель не назначен»), а
    // «не получилось» не объясняет ничего.
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  return (
    <Button type="button" size="sm" variant="ghost"
      className={cn('h-8 px-2', className)}
      disabled={толкнуть.isPending}
      title="Напомнить тому, у кого работа стоит"
      aria-label="Напомнить тому, у кого работа стоит"
      onClick={(e) => {
        // Строка целиком открывает предмет — толчок не должен её открывать.
        e.preventDefault()
        e.stopPropagation()
        толкнуть.mutate()
      }}>
      {толкнуть.isPending
        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
        : <BellRing className="h-3.5 w-3.5" />}
      {!compact && <span className="ml-1.5">Напомнить</span>}
    </Button>
  )
}
