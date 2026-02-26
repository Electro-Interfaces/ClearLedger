import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Play, Settings, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { mockConnectors, mockSyncLogs } from '@/services/mockData'

const statusConfig = {
  active: { label: 'Активен', className: 'bg-green-600/20 text-green-400 border-green-600/30' },
  error: { label: 'Ошибка', className: 'bg-red-600/20 text-red-400 border-red-600/30' },
  disabled: { label: 'Отключён', className: 'bg-gray-600/20 text-gray-400 border-gray-600/30' },
}

export function ConnectorDetailPage() {
  const { id } = useParams<{ id: string }>()
  const connector = mockConnectors.find((c) => c.id === id)

  if (!connector) {
    return (
      <div className="space-y-4">
        <Link to="/connectors" className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Назад к коннекторам
        </Link>
        <div className="text-center py-12 text-muted-foreground">Коннектор не найден</div>
      </div>
    )
  }

  const logs = mockSyncLogs.filter((l) => l.connectorId === connector.id)
  const status = statusConfig[connector.status]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/connectors" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <h1 className="text-2xl font-bold">{connector.name}</h1>
          <Badge variant="outline" className={status.className}>{status.label}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Play className="mr-2 h-4 w-4" />
            Тест
          </Button>
          <Button variant="outline" size="sm">
            <Settings className="mr-2 h-4 w-4" />
            Настройки
          </Button>
          <Button variant="outline" size="sm" className="text-destructive">
            <Trash2 className="mr-2 h-4 w-4" />
            Удалить
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Настройки подключения</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>URL</Label>
              <Input defaultValue={connector.url} />
            </div>
            <div className="space-y-2">
              <Label>Тип</Label>
              <Select defaultValue={connector.type}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="rest">REST API</SelectItem>
                  <SelectItem value="1c">1C</SelectItem>
                  <SelectItem value="email">Email (IMAP)</SelectItem>
                  <SelectItem value="ftp">FTP/SFTP</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Интервал синхронизации (сек.)</Label>
              <Input type="number" defaultValue={connector.interval} />
            </div>
            <div className="space-y-2">
              <Label>Категория</Label>
              <Input defaultValue={connector.categoryId} readOnly className="text-muted-foreground" />
            </div>
            <Button className="w-full">Сохранить</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Лог синхронизаций</CardTitle>
          </CardHeader>
          <CardContent>
            {logs.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">Нет записей</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Время</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead>Записей</TableHead>
                    <TableHead>Сообщение</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell className="text-muted-foreground text-sm">
                        {new Date(log.timestamp).toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={log.status === 'success'
                            ? 'bg-green-600/20 text-green-400 border-green-600/30'
                            : 'bg-red-600/20 text-red-400 border-red-600/30'}
                        >
                          {log.status === 'success' ? 'OK' : 'Ошибка'}
                        </Badge>
                      </TableCell>
                      <TableCell>{log.recordsProcessed}</TableCell>
                      <TableCell className="text-muted-foreground text-sm">{log.message ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
