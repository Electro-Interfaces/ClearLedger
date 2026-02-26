import { Badge } from '@/components/ui/badge'
import type { EntrySource } from '@/types'

const sourceConfig: Record<EntrySource, { label: string; className: string }> = {
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
  email: {
    label: 'Email',
    className: 'border-cyan-500 text-cyan-400',
  },
  paste: {
    label: 'Вставка',
    className: 'border-gray-500 text-gray-400',
  },
  oneC: {
    label: '1С',
    className: 'border-yellow-500 text-yellow-400',
  },
  whatsapp: {
    label: 'WhatsApp',
    className: 'border-emerald-500 text-emerald-400',
  },
  telegram: {
    label: 'Telegram',
    className: 'border-sky-500 text-sky-400',
  },
}

export function SourceBadge({ source }: { source: EntrySource }) {
  const config = sourceConfig[source] ?? sourceConfig.upload
  return (
    <Badge variant="outline" className={config.className}>
      {config.label}
    </Badge>
  )
}
