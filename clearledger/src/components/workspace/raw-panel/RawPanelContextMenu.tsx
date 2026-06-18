import {
  ContextMenu, ContextMenuContent, ContextMenuItem,
  ContextMenuSeparator, ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { FileText, ExternalLink, Copy, RefreshCw, Info } from 'lucide-react'
import { toast } from 'sonner'
import type { FsNode } from './raw-panel-types'

interface Props {
  children: React.ReactNode
  node: FsNode
  onOpen: (node: FsNode) => void
  onRefresh: () => void
}

export function RawPanelContextMenu({ children, node, onOpen, onRefresh }: Props) {
  const isFile = node.type === 'file'

  function handleCopyJson() {
    const data = node.shift ?? node.deliveryRecord ?? node
    navigator.clipboard.writeText(JSON.stringify(data, null, 2)).then(() => {
      toast.success('Скопировано в буфер обмена')
    })
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-52">
        <ContextMenuItem onClick={() => onOpen(node)}>
          <FileText className="mr-2 h-4 w-4" />
          Открыть
          {isFile && <span className="ml-auto text-xs text-muted-foreground">Enter</span>}
        </ContextMenuItem>

        {isFile && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onClick={handleCopyJson}>
              <Copy className="mr-2 h-4 w-4" />
              Копировать данные (JSON)
              <span className="ml-auto text-xs text-muted-foreground">Ctrl+C</span>
            </ContextMenuItem>
          </>
        )}

        <ContextMenuSeparator />

        <ContextMenuItem onClick={onRefresh}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Обновить
          <span className="ml-auto text-xs text-muted-foreground">F5</span>
        </ContextMenuItem>

        {isFile && (
          <ContextMenuItem disabled>
            <Info className="mr-2 h-4 w-4" />
            Свойства
            <span className="ml-auto text-xs text-muted-foreground">Alt+Enter</span>
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
