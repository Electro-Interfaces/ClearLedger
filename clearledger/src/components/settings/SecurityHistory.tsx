/**
 * Что происходило с учётной записью: входы и устройства с уведомлениями.
 *
 * До этого единственной реакцией на «кажется, кто-то заходил под моей учёткой»
 * было «выйти на всех устройствах» вслепую — человек не мог даже посмотреть,
 * было ли что-то на самом деле. Данные уже писались в журнал, их просто никто
 * не показывал владельцу.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, MonitorSmartphone } from 'lucide-react'
import { toast } from 'sonner'
import { myDevices, myLogins, revokeDevice } from '@/services/authService'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** «25.10.2026, 19:04» в поясе устройства — человек сверяет с тем, что помнит. */
function когда(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function SecurityHistory() {
  const qc = useQueryClient()
  const [всё, setВсё] = useState(false)
  const входы = useQuery({ queryKey: ['my-logins'], queryFn: myLogins, staleTime: 60_000 })
  const устройства = useQuery({ queryKey: ['my-devices'], queryFn: myDevices, staleTime: 60_000 })
  const отвязать = useMutation({
    mutationFn: (id: string) => revokeDevice(id),
    onSuccess: () => {
      toast.success('Устройство отвязано')
      void qc.invalidateQueries({ queryKey: ['my-devices'] })
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось отвязать'),
  })

  const список = входы.data?.logins ?? []
  const видимые = всё ? список : список.slice(0, 5)
  const приборы = устройства.data?.devices ?? []

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <h4 className="text-xs font-medium text-muted-foreground">Последние входы</h4>
        {входы.isLoading && <p className="text-xs text-muted-foreground">Загружаем…</p>}
        {!входы.isLoading && список.length === 0 && (
          <p className="text-xs text-muted-foreground">Записей пока нет.</p>
        )}
        <ul className="space-y-1.5">
          {видимые.map((в, i) => (
            <li key={`${в.at}-${i}`} className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="tabular-nums text-muted-foreground">{когда(в.at)}</span>
              <span className={cn(в.failed && 'text-destructive', в.newPlace && 'text-amber-600 dark:text-amber-500')}>
                {в.label}
              </span>
              {в.device && <span className="text-xs text-muted-foreground">· {в.device}</span>}
              {в.ip && <span className="text-xs tabular-nums text-muted-foreground">· {в.ip}</span>}
              {(в.newPlace || в.failed) && <AlertTriangle className="size-3.5 shrink-0 text-amber-600 dark:text-amber-500" />}
            </li>
          ))}
        </ul>
        {список.length > 5 && (
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs"
            onClick={() => setВсё((v) => !v)}>
            {всё ? 'Показать только последние' : `Показать все (${список.length})`}
          </Button>
        )}
        <p className="text-xs text-muted-foreground">
          Не узнаёте вход — смените пароль: он гасит все прежние входы, кроме этого окна.
        </p>
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-medium text-muted-foreground">Устройства с уведомлениями</h4>
        {устройства.isLoading && <p className="text-xs text-muted-foreground">Загружаем…</p>}
        {!устройства.isLoading && приборы.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Ни одно устройство не подписано на уведомления. Подписка появляется, когда вы
            разрешаете их в чате.
          </p>
        )}
        <ul className="space-y-1.5">
          {приборы.map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-sm">
              <MonitorSmartphone className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">
                {d.device}
                <span className="block text-xs text-muted-foreground">
                  подписано {когда(d.since)}
                  {!d.showPreview && ' · текст сообщений скрыт'}
                </span>
              </span>
              <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs"
                disabled={отвязать.isPending}
                onClick={() => {
                  if (window.confirm(`Отвязать «${d.device}»? Уведомления на это устройство перестанут приходить.`)) {
                    отвязать.mutate(d.id)
                  }
                }}>
                {отвязать.isPending && отвязать.variables === d.id
                  ? <Loader2 className="size-3.5 animate-spin" />
                  : 'Отвязать'}
              </Button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
