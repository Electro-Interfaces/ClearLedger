import type { OpsSnapshot } from '@/services/opsService'

export function OpsSnapshotNotice({ data }: { data: OpsSnapshot }) {
  return <div className="rounded-md border p-2 text-xs text-muted-foreground space-y-1">
    <p>{data.dataThrough
      ? `Данные по ${new Date(data.dataThrough).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })} МСК`
      : 'Сессии ещё не загружены'}
      {data.dataLagHours != null && data.dataLagHours >= 24
        ? ` · отставание ${Math.round(data.dataLagHours)} ч` : ''}</p>
    {data.snapshotNote && <p>{data.snapshotNote}</p>}
  </div>
}
