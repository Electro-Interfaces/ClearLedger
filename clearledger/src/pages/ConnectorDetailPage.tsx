import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, Save, Trash2, Power, PowerOff, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { useConnector, useUpdateConnector, useDeleteConnector, useSyncConnector } from '@/hooks/useConnectors'
import { DetailPageSkeleton } from '@/components/common/Skeletons'
import { QueryError } from '@/components/common/QueryError'
import { formatDateTime } from '@/lib/formatDate'
import { toast } from 'sonner'

interface EmailConfig {
  emailHost: string
  emailPort: string
  emailUser: string
  emailPassword: string
  emailFolder: string
  emailTls: boolean
}

function parseEmailConfig(url: string): EmailConfig | null {
  try {
    if (!url.startsWith('imap://') && !url.startsWith('imaps://')) return null
    const parsed = new URL(url)
    return {
      emailHost: parsed.hostname,
      emailPort: parsed.port || '993',
      emailUser: decodeURIComponent(parsed.username),
      emailPassword: decodeURIComponent(parsed.password),
      emailFolder: parsed.pathname.replace(/^\//, '') || 'INBOX',
      emailTls: url.startsWith('imaps://') || parsed.searchParams.get('tls') === '1',
    }
  } catch {
    return null
  }
}

function buildEmailConfig(form: EmailConfig): string {
  const proto = form.emailTls ? 'imaps' : 'imap'
  const user = encodeURIComponent(form.emailUser)
  const pass = encodeURIComponent(form.emailPassword)
  const port = form.emailPort || '993'
  const folder = form.emailFolder || 'INBOX'
  return `${proto}://${user}:${pass}@${form.emailHost}:${port}/${folder}`
}

const statusConfig = {
  active: { label: 'Активен', className: 'bg-green-600/20 text-green-400 border-green-600/30' },
  error: { label: 'Ошибка', className: 'bg-red-600/20 text-red-400 border-red-600/30' },
  disabled: { label: 'Отключён', className: 'bg-gray-600/20 text-gray-400 border-gray-600/30' },
}

export function ConnectorDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: connector, isLoading, isError, refetch } = useConnector(id ?? '')
  const updateConnector = useUpdateConnector()
  const deleteConnector = useDeleteConnector()
  const syncConnector = useSyncConnector()

  const [form, setForm] = useState({
    name: '', url: '', type: '', interval: '', categoryId: '',
    emailHost: '', emailPort: '993', emailUser: '', emailPassword: '', emailFolder: 'INBOX', emailTls: true,
  })

  useEffect(() => {
    if (connector) {
      const emailConfig = parseEmailConfig(connector.url)
      setForm({
        name: connector.name,
        url: connector.url,
        type: connector.type,
        interval: String(connector.interval),
        categoryId: connector.categoryId,
        ...(emailConfig ?? { emailHost: '', emailPort: '993', emailUser: '', emailPassword: '', emailFolder: 'INBOX', emailTls: true }),
      })
    }
  }, [connector])

  if (isLoading) return <DetailPageSkeleton />
  if (isError) return <QueryError onRetry={() => refetch()} />

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
    const url = form.type === 'email'
      ? buildEmailConfig(form)
      : form.url
    updateConnector.mutate({
      id: connector!.id,
      updates: {
        name: form.name,
        url,
        type: form.type,
        interval: Number(form.interval) || 60,
        categoryId: form.categoryId,
      },
    }, {
      onSuccess: () => toast.success('Коннектор сохранён'),
      onError: () => toast.error('Ошибка сохранения'),
    })
  }

  function handleToggle() {
    const newStatus = connector!.status === 'disabled' ? 'active' : 'disabled'
    updateConnector.mutate({
      id: connector!.id,
      updates: { status: newStatus },
    }, {
      onSuccess: () => toast.success(newStatus === 'active' ? 'Коннектор включён' : 'Коннектор отключён'),
    })
  }

  function handleDelete() {
    deleteConnector.mutate(connector!.id, {
      onSuccess: () => {
        toast.success('Коннектор удалён')
        navigate('/connectors')
      },
      onError: () => toast.error('Ошибка удаления'),
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
          <Button
            variant="outline"
            size="sm"
            disabled={connector.status === 'disabled' || syncConnector.isPending}
            onClick={() => {
              syncConnector.mutate(connector.id, {
                onSuccess: (result) => {
                  if (result.error) {
                    toast.error(result.error)
                  } else {
                    toast.success(`Синхронизировано: ${result.entries.length} записей`)
                  }
                },
                onError: () => toast.error('Ошибка синхронизации'),
              })
            }}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${syncConnector.isPending ? 'animate-spin' : ''}`} />
            {syncConnector.isPending ? 'Синхронизация...' : 'Синхронизировать'}
          </Button>
          <Button variant="outline" size="sm" onClick={handleToggle}>
            {connector.status === 'disabled' ? (
              <><Power className="mr-2 h-4 w-4" />Включить</>
            ) : (
              <><PowerOff className="mr-2 h-4 w-4" />Отключить</>
            )}
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="text-destructive">
                <Trash2 className="mr-2 h-4 w-4" />
                Удалить
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Удалить коннектор?</AlertDialogTitle>
                <AlertDialogDescription>
                  Коннектор &laquo;{connector.name}&raquo; будет удалён. Это действие нельзя отменить.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Отмена</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                  Удалить
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
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

          {/* Поля зависят от типа коннектора */}
          {form.type === 'email' ? (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>IMAP сервер</Label>
                  <Input placeholder="imap.example.com" value={form.emailHost} onChange={(e) => setForm({ ...form, emailHost: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>Порт</Label>
                  <Input type="number" value={form.emailPort} onChange={(e) => setForm({ ...form, emailPort: e.target.value })} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Пользователь</Label>
                  <Input placeholder="user@example.com" value={form.emailUser} onChange={(e) => setForm({ ...form, emailUser: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>Пароль</Label>
                  <Input type="password" placeholder="••••••••" value={form.emailPassword} onChange={(e) => setForm({ ...form, emailPassword: e.target.value })} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Папка</Label>
                  <Input placeholder="INBOX" value={form.emailFolder} onChange={(e) => setForm({ ...form, emailFolder: e.target.value })} />
                </div>
                <div className="flex items-center gap-2 pt-6">
                  <input
                    type="checkbox"
                    id="emailTls"
                    checked={form.emailTls}
                    onChange={(e) => setForm({ ...form, emailTls: e.target.checked })}
                    className="size-4 rounded border-input"
                  />
                  <Label htmlFor="emailTls" className="cursor-pointer">SSL/TLS</Label>
                </div>
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <Label>{form.type === 'ftp' ? 'Хост' : 'URL'}</Label>
              <Input
                placeholder={form.type === 'ftp' ? 'ftp.example.com:/path' : 'https://api.example.com/v1'}
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label>Интервал синхронизации (сек.)</Label>
            <Input type="number" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>Категория</Label>
            <Input value={form.categoryId} onChange={(e) => setForm({ ...form, categoryId: e.target.value })} />
          </div>
          <Button onClick={handleSave}>
            <Save className="mr-2 h-4 w-4" />
            Сохранить
          </Button>
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
                {connector.lastSyncAt
                  ? formatDateTime(connector.lastSyncAt)
                  : connector.lastSync
                    ? formatDateTime(connector.lastSync)
                    : 'Не выполнялась'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Статус синхронизации:</span>
              <span className="ml-2 font-medium">
                {connector.syncStatus === 'synced' && 'Синхронизирован'}
                {connector.syncStatus === 'syncing' && 'Синхронизация...'}
                {connector.syncStatus === 'error' && 'Ошибка'}
                {(!connector.syncStatus || connector.syncStatus === 'idle') && 'Ожидание'}
              </span>
            </div>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Demo-режим: кнопка «Синхронизировать» генерирует тестовые записи. Реальная синхронизация — в Слое 2.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
