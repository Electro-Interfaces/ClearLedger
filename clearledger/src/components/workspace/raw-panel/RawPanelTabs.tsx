import { FileText, Fuel, X } from 'lucide-react'
import type { FsNode } from './raw-panel-types'

interface Props {
  tabs: FsNode[]
  activeId: string | null
  onSwitch: (node: FsNode) => void
  onClose: (path: string) => void
}

export function RawPanelTabs({ tabs, activeId, onSwitch, onClose }: Props) {
  if (tabs.length === 0) return null

  return (
    <div className="flex items-center gap-0.5 px-2 py-0.5 overflow-x-auto border-t border-border/40 scrollbar-hide">
      {tabs.map((tab) => {
        const isActive = activeId === tab.path
        const isDelivery = tab.docType === 'delivery' || tab.name.includes('ТТН')
        const Icon = isDelivery ? Fuel : FileText

        return (
          <div
            key={tab.path}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs cursor-pointer transition-colors shrink-0 ${
              isActive
                ? 'bg-primary/15 text-primary font-semibold'
                : 'text-muted-foreground hover:bg-accent/40'
            }`}
          >
            <button onClick={() => onSwitch(tab)} className="flex items-center gap-1">
              <Icon className="h-3 w-3 shrink-0" />
              <span className="max-w-[90px] truncate">{tab.name}</span>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onClose(tab.path) }}
              className="h-3.5 w-3.5 flex items-center justify-center rounded hover:bg-destructive/20 hover:text-destructive transition-colors ml-0.5"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
