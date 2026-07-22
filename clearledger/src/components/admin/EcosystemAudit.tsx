/**
 * Центр управления → Экосистема → «Аудит». Журнал действий по ВСЕЙ экосистеме
 * (суперадмин). Бэкенд: GET /api/core/audit.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { getCoreAudit } from '@/services/coreService'

export function EcosystemAudit() {
  const q = useQuery({ queryKey: ['core-audit'], queryFn: () => getCoreAudit({ limit: 150 }), staleTime: 15_000 })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }
  const events = q.data ?? []
  const fmt = (t?: string | null) => (t ? new Date(t).toLocaleString('ru-RU') : '—')

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Журнал действий по всей экосистеме — последние {events.length}.</p>
      <div className="rounded-lg border divide-y text-sm">
        {events.map((e) => (
          <div key={e.id} className="grid grid-cols-1 sm:grid-cols-[160px_130px_1fr] gap-x-3 gap-y-0.5 px-3 py-2">
            <span className="text-xs text-muted-foreground tabular-nums">{fmt(e.timestamp)}</span>
            <Badge variant="outline" className="text-[10px] w-fit">{e.companyName}</Badge>
            <span className="min-w-0">
              <span className="font-medium">{e.action}</span>
              {e.details && <span className="text-muted-foreground"> — {e.details}</span>}
              <span className="text-muted-foreground text-xs"> · {e.userName}</span>
            </span>
          </div>
        ))}
        {events.length === 0 && <div className="px-3 py-8 text-center text-muted-foreground">Событий нет</div>}
      </div>
    </div>
  )
}
