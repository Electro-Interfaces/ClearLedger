/**
 * Центр управления → Экосистема → «Оповещения». Системные оповещения о состоянии
 * Ядра, выведенные из /api/core/status (сервисы недоступны, SSO не настроен).
 * Подписки на события (новый пользователь, ошибки, входы) — следующий инкремент.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { getCoreStatus } from '@/services/coreService'

export function CoreAlerts() {
  const q = useQuery({ queryKey: ['core-status'], queryFn: getCoreStatus, staleTime: 30_000, refetchInterval: 60_000 })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }
  const d = q.data
  const alerts: string[] = []
  if (d) {
    d.services.filter((s) => s.status === 'down').forEach((s) => alerts.push(`Сервис «${s.name}» недоступен`))
    if (!d.sso.enabled) alerts.push('Единый вход (SSO) не настроен — лаунчер приложений скрыт')
  }

  return (
    <div className="space-y-3">
      {alerts.length === 0 ? (
        <Card><CardContent className="py-6 flex items-center gap-2 text-emerald-400">
          <CheckCircle2 className="h-5 w-5" /> Всё в порядке — активных оповещений нет
        </CardContent></Card>
      ) : (
        alerts.map((a, i) => (
          <Card key={i}><CardContent className="py-3 flex items-center gap-2 text-amber-300">
            <AlertTriangle className="h-4 w-4 shrink-0" /> {a}
          </CardContent></Card>
        ))
      )}
      <p className="text-xs text-muted-foreground flex items-start gap-1.5">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        Пока это системные оповещения о состоянии Ядра. Подписки на события (новый пользователь,
        сбои, входы) — следующий инкремент консоли.
      </p>
    </div>
  )
}
