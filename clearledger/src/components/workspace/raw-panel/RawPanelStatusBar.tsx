import { format } from 'date-fns'

interface Props {
  count: number
  dataUpdatedAt: number
}

export function RawPanelStatusBar({ count, dataUpdatedAt }: Props) {
  const time = dataUpdatedAt ? format(new Date(dataUpdatedAt), 'HH:mm') : '—'

  return (
    <div className="flex items-center justify-between px-3 py-0.5 border-t border-border/40 text-xs text-muted-foreground tabular-nums select-none">
      <span>{count} {count === 1 ? 'элемент' : count < 5 ? 'элемента' : 'элементов'}</span>
      <span>обновлено {time}</span>
    </div>
  )
}
