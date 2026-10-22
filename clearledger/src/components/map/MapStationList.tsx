import { StationLink } from '@/components/common/StationLink'
import { useStationCard } from '@/contexts/StationCardContext'
import { OP_LABELS } from '@/lib/stationFacets'
import { locationField } from '@/types/location'

const STATUS_LABELS: Record<string, string> = {
  ...OP_LABELS, on_repair: 'На ремонте', maintenance: 'Обслуживание',
}

interface MapStation {
  id: string
  name: string
  number?: string
  status?: string | null
}

/** Все станции точки доступны, включая выведенные и записи после восьмой. */
export function MapStationList({ items, onOpen }: {
  items: MapStation[]
  onOpen?: (id: string) => void
}) {
  const cards = useStationCard()
  return (
    <ul aria-label="Объекты в точке" className="m-0 mt-2 max-h-56 list-none space-y-2 overflow-y-auto p-0 pr-1">
      {items.map((item) => {
        const location = cards.find(item.id)
        const number = item.number || (location ? locationField(location, 'number') : '')
        const label = number ? `№${number} · ${item.name}` : item.name
        const status = item.status ? STATUS_LABELS[item.status] ?? 'Состояние не известно' : null
        return (
          <li key={item.id} className="break-words text-sm leading-snug">
            {onOpen ? (
              <button type="button" onClick={() => onOpen(item.id)}
                className="rounded-sm text-left underline decoration-dotted underline-offset-2 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {label}
              </button>
            ) : <StationLink station={item.id}>{label}</StationLink>}
            {status && <div className="text-muted-foreground">{status}</div>}
          </li>
        )
      })}
    </ul>
  )
}
