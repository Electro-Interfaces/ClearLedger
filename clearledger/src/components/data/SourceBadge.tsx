import { Badge } from '@/components/ui/badge'
import type { DataEntry } from '@/types'

const sourceConfig: Record<DataEntry['source'], { label: string; className: string }> = {
  upload: {
    label: 'Загрузка',
    className: 'border-blue-500 text-blue-400',
  },
  photo: {
    label: 'Фото',
    className: 'border-purple-500 text-purple-400',
  },
  manual: {
    label: 'Ручной',
    className: 'border-green-500 text-green-400',
  },
  api: {
    label: 'API',
    className: 'border-orange-500 text-orange-400',
  },
}

export function SourceBadge({ source }: { source: DataEntry['source'] }) {
  const config = sourceConfig[source]
  return (
    <Badge variant="outline" className={config.className}>
      {config.label}
    </Badge>
  )
}
