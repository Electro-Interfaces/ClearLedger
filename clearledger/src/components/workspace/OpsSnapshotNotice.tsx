import type { OpsSnapshot } from '@/services/opsService'

export function OpsSnapshotStatus({ dataThrough, dataLagHours, snapshotNote }: Pick<OpsSnapshot, 'dataThrough' | 'dataLagHours' | 'snapshotNote'>) {
  const date = dataThrough ? new Date(dataThrough) : null
  const lag = dataLagHours != null && dataLagHours >= 24 ? 'отставание ' + Math.round(dataLagHours) + ' ч' : ''
  const full = date ? 'Данные по ' + date.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) + ' МСК' : 'Сессии ещё не загружены'
  const title = [full, lag, snapshotNote].filter(Boolean).join(' · ')
  return <span title={title} aria-label={title} className="inline-flex flex-wrap justify-end gap-x-1 text-xs leading-4 text-muted-foreground">
    <span className="whitespace-nowrap">{date ? 'Данные по ' + date.toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' }) : 'Сессии ещё не загружены'}</span>
    {lag && <span className="whitespace-nowrap">· {lag}</span>}
  </span>
}

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
