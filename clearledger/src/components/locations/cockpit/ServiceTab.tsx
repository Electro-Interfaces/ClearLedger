/**
 * Сервис объекта: заявки Координатора (общий объект пространства) + полевые заявки
 * HubEx FSM (внешняя система, при наличии metadata.hubexAssetId).
 *
 * Координатор — соседний разрез той же экосистемы, поэтому его заявки показываем всегда,
 * а HubEx-часть — отдельной секцией, как было.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Wrench } from 'lucide-react'
import { getHubexTasks } from '@/services/locationService'
import type { ServiceLocation } from '@/types/location'
import { Field, Placeholder, ScrollTab } from './shared'
import { CoordinatorTickets } from './CoordinatorTickets'

export function ServiceTab({ location }: { location: ServiceLocation }) {
  const meta = (location.metadata ?? {}) as Record<string, unknown>
  const hubexQ = useQuery({
    queryKey: ['hubex-tasks', location.id],
    queryFn: () => getHubexTasks(location.id),
    staleTime: 60_000,
  })

  if (meta.hubexAssetId == null) {
    return (
      <ScrollTab>
        <CoordinatorTickets objectId={location.id} />
        <Placeholder
          icon={Wrench}
          title="Станция не связана с HubEx"
          text="Нет HubEx asset_id — заявки внешней сервисной системы недоступны. Связка проставляется при импорте реестра."
        />
      </ScrollTab>
    )
  }

  return (
    <ScrollTab>
      <CoordinatorTickets objectId={location.id} />
      <Card>
        <CardContent className="grid grid-cols-2 gap-x-8 gap-y-2 pt-5 text-sm">
          <Field label="HubEx asset_id" value={String(meta.hubexAssetId)} mono />
          <Field label="Статус связки" value={String(meta.linkStatus ?? '—')} />
          <div className="col-span-2"><Field label="HubEx название" value={String(meta.hubexName ?? '—')} /></div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Сервисные заявки HubEx FSM</div>
        {hubexQ.data?.configured && (
          <span className="text-xs text-muted-foreground">всего: {hubexQ.data.total}</span>
        )}
      </div>

      {hubexQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка заявок…</p>}
      {hubexQ.data && !hubexQ.data.configured && (
        <p className="text-sm text-muted-foreground">HubEx-интеграция не настроена (нет сервисного токена).</p>
      )}
      {hubexQ.data?.error && (
        <p className="text-sm text-destructive">HubEx недоступен: {hubexQ.data.error}</p>
      )}
      {hubexQ.data?.configured && !hubexQ.data.error && hubexQ.data.tasks.length === 0 && (
        <p className="text-sm text-muted-foreground">Заявок по станции нет.</p>
      )}

      <div className="space-y-2">
        {hubexQ.data?.tasks.map((t) => (
          <div key={t.id} className="space-y-1.5 rounded-md border border-border/50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-medium">#{t.number}</span>
              {t.status && (
                <Badge variant="secondary" className="text-[10px]"
                  style={t.statusColor ? { backgroundColor: `#${t.statusColor}26`, color: `#${t.statusColor}` } : undefined}>
                  {t.status}
                </Badge>
              )}
              {t.criticality && (
                <Badge variant="outline" className="text-[10px]"
                  style={t.criticalityColor ? { borderColor: `#${t.criticalityColor}`, color: `#${t.criticalityColor}` } : undefined}>
                  {t.criticality}
                </Badge>
              )}
              {t.type && <span className="text-xs text-muted-foreground">{t.type}</span>}
            </div>
            {t.notes && <div className="whitespace-pre-line text-sm">{t.notes.trim()}</div>}
            <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
              {t.assignee && <span>Исполнитель: {t.assignee}</span>}
              {t.deadline && <span>Срок: {new Date(t.deadline).toLocaleString('ru-RU')}</span>}
            </div>
          </div>
        ))}
      </div>
    </ScrollTab>
  )
}
