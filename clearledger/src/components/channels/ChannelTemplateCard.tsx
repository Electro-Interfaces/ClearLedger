import * as Icons from 'lucide-react'
import type { ChannelTemplate } from '@/types/channel'

interface Props {
  template: ChannelTemplate
  selected: boolean
  onSelect: () => void
}

export function ChannelTemplateCard({ template, selected, onSelect }: Props) {
  // Dynamic icon from lucide-react
  const IconComponent = (Icons as Record<string, React.ComponentType<{ className?: string }>>)[template.icon] ?? Icons.FileText

  return (
    <button
      onClick={onSelect}
      className={[
        'flex flex-col items-start gap-2 p-4 rounded-xl border-2 text-left transition-all',
        'hover:border-primary/40 hover:bg-accent/30',
        selected
          ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
          : 'border-border/40 bg-card',
      ].join(' ')}
    >
      <div className={`flex items-center justify-center w-10 h-10 rounded-lg ${
        selected ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
      }`}>
        <IconComponent className="h-5 w-5" />
      </div>
      <div>
        <div className="font-medium text-sm">{template.name}</div>
        <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{template.description}</div>
      </div>
    </button>
  )
}
