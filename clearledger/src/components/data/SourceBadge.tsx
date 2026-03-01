import { Badge } from '@/components/ui/badge'
import type { EntrySource } from '@/types'

const BADGE_CLASS = 'border-zinc-600 text-zinc-400'

const sourceConfig: Record<EntrySource, { label: string; className: string }> = {
  upload:   { label: 'Загрузка',    className: BADGE_CLASS },
  photo:    { label: 'Фото',        className: BADGE_CLASS },
  manual:   { label: 'Ручной',      className: BADGE_CLASS },
  api:      { label: 'API',         className: BADGE_CLASS },
  email:    { label: 'Email',       className: BADGE_CLASS },
  paste:    { label: 'Вставка',     className: BADGE_CLASS },
  oneC:     { label: '1С',          className: BADGE_CLASS },
  whatsapp: { label: 'WhatsApp',    className: BADGE_CLASS },
  telegram: { label: 'Telegram',    className: BADGE_CLASS },
}

export function SourceBadge({ source }: { source: EntrySource }) {
  const config = sourceConfig[source] ?? sourceConfig.upload
  return (
    <Badge variant="outline" className={config.className}>
      {config.label}
    </Badge>
  )
}
