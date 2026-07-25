/**
 * Заявки Координатора по этому объекту — вторая сторона одного объекта пространства.
 *
 * Учёт и Координатор смотрят на одну и ту же АЗС; ось — общий объект (docs/SPACE.md).
 * Данные не копируем в Ledger: спрашиваем разрез в момент показа, иначе в пространстве
 * появилась бы вторая правда о заявках. Переход «в Координатор» — через рельс экосистемы.
 */
import { useQuery } from '@tanstack/react-query'
import { LifeBuoy, ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useCompany } from '@/contexts/CompanyContext'
import { getObjectTickets } from '@/services/spaceObjectsService'

const OPEN_LABEL: Record<string, string> = {
  new: 'Новая', open: 'Открыта', in_progress: 'В работе', waiting: 'Ожидание',
  done: 'Выполнена', closed: 'Закрыта', cancelled: 'Отменена',
}

export function CoordinatorTickets({ objectId }: { objectId: string }) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['object-tickets', companyId, objectId],
    queryFn: () => getObjectTickets(companyId, objectId),
    enabled: !!companyId && !!objectId,
    staleTime: 60_000,
    retry: false,
  })

  // Приложение не подключено к этой компании — молчим: это не ошибка, а состояние.
  if (q.isError || (q.data && !q.data.linked)) return null

  const data = q.data
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium">
          <LifeBuoy className="size-4 text-primary" /> Заявки Координатора
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-xs text-muted-foreground">
              открытых: {data.open} из {data.total}
            </span>
          )}
          <a href="/support/" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            Открыть <ExternalLink className="size-3" />
          </a>
        </div>
      </div>

      {q.isLoading && <p className="text-sm text-muted-foreground">Загрузка заявок…</p>}
      {data && data.tickets.length === 0 && (
        <p className="text-sm text-muted-foreground">По объекту заявок нет.</p>
      )}

      <div className="space-y-2">
        {data?.tickets.map((t) => (
          <div key={t.id} className="flex flex-wrap items-center gap-2 rounded-md border border-border/50 p-3">
            <span className="font-mono text-xs font-medium">#{t.number}</span>
            <span className="flex-1 truncate text-sm">{t.title}</span>
            <Badge variant="secondary" className="text-[10px]">
              {OPEN_LABEL[t.status] ?? t.status}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {new Date(t.created_at).toLocaleDateString('ru-RU')}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}
