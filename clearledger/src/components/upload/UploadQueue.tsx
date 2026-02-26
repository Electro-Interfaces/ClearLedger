import type { UploadItem } from '@/types'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-react'
import { getCategoryById } from '@/config/categories'
import { useCompany } from '@/contexts/CompanyContext'

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

const statusConfig: Record<
  UploadItem['status'],
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }
> = {
  pending: { label: 'Ожидание', variant: 'secondary' },
  uploading: { label: 'Загрузка', variant: 'default' },
  done: { label: 'Готово', variant: 'outline' },
  error: { label: 'Ошибка', variant: 'destructive' },
}

interface UploadQueueProps {
  items: UploadItem[]
  onRemove: (id: string) => void
}

export function UploadQueue({ items, onRemove }: UploadQueueProps) {
  const { company } = useCompany()

  if (items.length === 0) return null

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Файл</TableHead>
            <TableHead>Размер</TableHead>
            <TableHead>Категория</TableHead>
            <TableHead className="w-[140px]">Прогресс</TableHead>
            <TableHead>Статус</TableHead>
            <TableHead className="w-[60px]">Действия</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const cat = getCategoryById(company.profileId, item.categoryId)
            const cfg = statusConfig[item.status]

            return (
              <TableRow key={item.id}>
                <TableCell className="max-w-[200px] truncate font-medium">
                  {item.file.name}
                </TableCell>
                <TableCell>{formatFileSize(item.file.size)}</TableCell>
                <TableCell>{cat?.label ?? '—'}</TableCell>
                <TableCell>
                  <Progress value={item.progress} className="h-2" />
                </TableCell>
                <TableCell>
                  <Badge variant={cfg.variant}>{cfg.label}</Badge>
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    onClick={() => onRemove(item.id)}
                    disabled={item.status === 'uploading'}
                  >
                    <X className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
