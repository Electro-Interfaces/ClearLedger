import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, Save, Trash2, Power, PowerOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useConnector, useUpdateConnector, useDeleteConnector } from '@/hooks/useConnectors'

const statusConfig = {
  active: { label: 'Активен', className: 'bg-green-600/20 text-green-400 border-green-600/30' },
  error: { label: 'Ошибка', className: 'bg-red-600/20 text-red-400 border-red-600/30' },
  disabled: { label: 'Отключён', className: 'bg-gray-600/20 text-gray-400 border-gray-600/30' },
}

export function ConnectorDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: connector, isLoading } = useConnector(id ?? '')
  const updateConnector = useUpdateConnector()
  const deleteConnector = useDeleteConnector()

  const [form, setForm] = useState({ name: '', url: '', type: '', interval: '', categoryId: '' })
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (connector) {
      setForm({
        name: connector.name,
        url: connector.url,
        type: connector.type,
        interval: String(connector.interval),
        categoryId: connector.categoryId,
      })
    }
  }, [connector])

  if (isLoading) {
    return <div className="text-center py-12 text-muted-foreground">Загрузка...</div>
  }

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

  const status = statusConfig[connector.status]

  function handleSave() {
    updateConnector.mutate({
      id: connector!.id,
      updates: {
        name: form.name,
        url: form.url,
        type: form.type,
        interval: Number(form.interval) || 60,
        categoryId: form.categoryId,
      },
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function handleToggle() {
    const newStatus = connector!.status === 'disabled' ? 'active' : 'disabled'
    updateConnector.mutate({
      id: connector!.id,
      updates: { status: newStatus },
    })
  }

  function handleDelete() {
    deleteConnector.mutate(connector!.id, {
      onSuccess: () => navigate('/connectors'),
    })
  }

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
          <Button variant="outline" size="sm" onClick={handleToggle}>
            {connector.status === 'disabled' ? (
              <><Power className="mr-2 h-4 w-4" />Включить</>
            ) : (
              <><PowerOff className="mr-2 h-4 w-4" />Отключить</>
            )}
          </Button>
          <Button variant="outline" size="sm" className="text-destructive" onClick={handleDelete}>
            <Trash2 className="mr-2 h-4 w-4" />
            Удалить
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Настройки подключения</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Название</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>URL</Label>
            <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>Тип</Label>
            <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="rest">REST API</SelectItem>
                <SelectItem value="1c">1C</SelectItem>
                <SelectItem value="email">Email (IMAP)</SelectItem>
                <SelectItem value="ftp">FTP/SFTP</SelectItem>
                <SelectItem value="webhook">Webhook</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Интервал синхронизации (сек.)</Label>
            <Input type="number" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>Категория</Label>
            <Input value={form.categoryId} onChange={(e) => setForm({ ...form, categoryId: e.target.value })} />
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={handleSave}>
              <Save className="mr-2 h-4 w-4" />
              Сохранить
            </Button>
            {saved && <span className="text-sm text-green-500">Сохранено</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Статистика</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Записей получено:</span>
              <span className="ml-2 font-medium">{connector.recordsCount}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Ошибок:</span>
              <span className="ml-2 font-medium">{connector.errorsCount}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Последняя синхронизация:</span>
              <span className="ml-2 font-medium">
                {connector.lastSync
                  ? new Date(connector.lastSync).toLocaleString('ru-RU')
                  : 'Не выполнялась'}
              </span>
            </div>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Реальная синхронизация доступна в Слое 2 (Python + cron). Слой 1 хранит конфигурацию.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
