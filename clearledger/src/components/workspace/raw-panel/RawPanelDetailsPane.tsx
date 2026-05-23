import { FileText, Fuel, X } from 'lucide-react'
import type { FsNode } from './raw-panel-types'

interface Props {
  node: FsNode | null
  onClose: () => void
}

export function RawPanelDetailsPane({ node, onClose }: Props) {
  if (!node || node.type === 'folder') return null

  const isDelivery = node.docType === 'delivery' || node.name.includes('ТТН')
  const Icon = isDelivery ? Fuel : FileText
  const typeShort = isDelivery ? 'ТТН' : 'Смена'

  const parts = [typeShort, node.date, node.size && node.size !== '—' ? node.size : null].filter(Boolean)

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 border-t border-border/40 bg-muted/20 text-xs text-muted-foreground select-none min-h-0">
      <Icon className="h-3 w-3 shrink-0" />
      <span className="font-medium text-foreground truncate">{node.name}</span>
      <span className="truncate">{parts.join(' \u00b7 ')}</span>
      <button
        onClick={onClose}
        className="ml-auto h-4 w-4 flex items-center justify-center rounded hover:bg-accent shrink-0"
        title="Скрыть"
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </div>
  )
}
