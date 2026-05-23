import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatusBadge } from '@/components/data/StatusBadge'
import { useEntries } from '@/hooks/useEntries'
import { useIsMobile } from '@/hooks/use-mobile'
import { formatTime } from '@/lib/formatDate'
import { useMemo } from 'react'

const actionLabels: Record<string, string> = {
  new: 'Загружен',
  recognized: 'Распознан',
  verified: 'Проверен',
  transferred: 'Передан',
  error: 'Ошибка',
}

export function RecentActivity() {
  const { data: entries = [] } = useEntries()
  const isMobile = useIsMobile()

  const recentEntries = useMemo(
    () => [...entries].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 7),
    [entries],
  )

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Последние действия</CardTitle>
      </CardHeader>
      <CardContent>
        {recentEntries.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">Нет данных</p>
        ) : isMobile ? (
          <div className="space-y-2">
            {recentEntries.map((entry) => (
              <div key={entry.id} className="flex items-center gap-3 p-2 rounded-md border">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{entry.title}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-muted-foreground">{formatTime(entry.updatedAt)}</span>
                    <span className="text-xs text-muted-foreground">{actionLabels[entry.status] ?? entry.status}</span>
                  </div>
                </div>
                <StatusBadge status={entry.status} />
              </div>
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Время</TableHead>
                <TableHead>Файл</TableHead>
                <TableHead>Действие</TableHead>
                <TableHead>Статус</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentEntries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="text-muted-foreground">{formatTime(entry.updatedAt)}</TableCell>
                  <TableCell className="font-medium">{entry.title}</TableCell>
                  <TableCell>{actionLabels[entry.status] ?? entry.status}</TableCell>
                  <TableCell>
                    <StatusBadge status={entry.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
