/**
 * «Подключения» → «Состояние»: чем пространство связано с внешним миром и что из
 * этого сейчас живо.
 *
 * Раньше экран показывал ДВА разных состава сразу: сверху карточку платформенных
 * сервисов (чат, конференции, почта — из `/core/status`, закрытого суперадмином),
 * снизу витрину подключений, где конференций не было, зато были каналы и источники.
 * Чат и почта попадали в обе таблицы, конференции — только в верхнюю, а администратор
 * компании вместо верхней видел пустоту. Раздел читался как «показывает выборочно».
 *
 * Теперь список один — витрина (`SpaceConnectors`), куда платформенные сервисы входят
 * наравне с остальными. Здесь — сводка по нему: сколько живо, у кого ошибка, кто молчит.
 *
 * Настройка остаётся у владельца подключения: здесь только состояние и переход.
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleOff, Clock } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { SpaceConnectors } from '@/components/channels/SpaceConnectors'
import { useCompany } from '@/contexts/CompanyContext'
import { listSpaceConnectors, type SpaceConnector } from '@/services/spaceConnectorsService'

/** Молчит ли подключение: обмен был, но давно. Порог — сутки. */
const SILENT_MS = 24 * 60 * 60 * 1000

function isSilent(c: SpaceConnector): boolean {
  if (!c.enabled || c.last_error || !c.last_sync_at) return false
  const t = new Date(c.last_sync_at).getTime()
  return !Number.isNaN(t) && Date.now() - t > SILENT_MS
}

function Tile({ n, label, hint, cls, Icon }: {
  n: number; label: string; hint: string
  cls: string; Icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <div className="rounded-lg border px-3 py-2.5">
      <div className={`flex items-center gap-1.5 text-sm ${cls}`}>
        <Icon className="h-4 w-4" />
        <span className="text-lg font-semibold tabular-nums">{n}</span>
        {label}
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
    </div>
  )
}

export function Connections() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['space-connectors', companyId],
    queryFn: () => listSpaceConnectors(companyId),
    enabled: !!companyId,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  })

  // Плитки должны делить список, а не пересекаться: сломанный источник считался и
  // «с ошибкой», и «выключен», и сумма плиток превышала число подключений.
  const items = q.data?.connectors ?? []
  const failing = items.filter((c) => c.last_error || c.status === 'error')
  const off = items.filter(
    (c) => !failing.includes(c) && (!c.enabled || c.status === 'off'))
  const rest = items.filter((c) => !failing.includes(c) && !off.includes(c))
  const silent = rest.filter(isSilent)
  const live = rest

  return (
    <div className="space-y-6">
      {items.length > 0 && (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <div>
              <h2 className="text-base font-semibold">Что сейчас происходит</h2>
              <p className="text-sm text-muted-foreground">
                Сводка по всем подключениям пространства — платформенным сервисам, обменам
                с внешними системами и файловым каналам приложений.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <Tile n={live.length} label="работают" cls="text-emerald-500" Icon={CheckCircle2}
                hint="подключение включено и не сообщало об ошибке" />
              <Tile n={failing.length} label="с ошибкой"
                cls={failing.length ? 'text-destructive' : 'text-muted-foreground'}
                Icon={AlertTriangle} hint="последний обмен не удался — причина в списке ниже" />
              <Tile n={silent.length} label="молчат"
                cls={silent.length ? 'text-amber-500' : 'text-muted-foreground'} Icon={Clock}
                hint="данные не приходили больше суток, хотя подключение живо" />
              <Tile n={off.length} label="выключены" cls="text-muted-foreground" Icon={CircleOff}
                hint="сервис не заказан в стеке или подключение остановлено" />
            </div>
            {silent.length > 0 && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs">
                <span className="font-medium">Давно не приносили данные:</span>{' '}
                {silent.map((c) => c.label).join(' · ')}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <SpaceConnectors />
    </div>
  )
}
