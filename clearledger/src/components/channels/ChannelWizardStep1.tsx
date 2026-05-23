import { ChannelTemplateCard } from './ChannelTemplateCard'
import { getTemplatesByCategory } from '@/services/channelTemplateService'
import type { ChannelTemplate } from '@/types/channel'

interface Props {
  selectedId: string | null
  onSelect: (template: ChannelTemplate) => void
}

export function ChannelWizardStep1({ selectedId, onSelect }: Props) {
  const byCategory = getTemplatesByCategory()

  return (
    <div className="space-y-6">
      {[...byCategory.entries()].map(([category, templates]) => (
        <div key={category}>
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">{category}</h3>
          <div className="grid grid-cols-2 gap-3">
            {templates.map((t) => (
              <ChannelTemplateCard
                key={t.id}
                template={t}
                selected={selectedId === t.id}
                onSelect={() => onSelect(t)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
