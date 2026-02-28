/**
 * Форма подключения к 1С:Бухгалтерия — настройки OData, логин/пароль, папка обмена.
 */

import { useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { CheckCircle2, XCircle, Loader2, Link2, Trash2, Save, TestTube } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import {
  useOneCConnections,
  useCreateOneCConnection,
  useUpdateOneCConnection,
  useDeleteOneCConnection,
  useTestOneCConnection,
} from '@/hooks/useOneCSync'
import type { OneCConnection, OneCTestResult } from '@/types'

export function OneCConnectionForm() {
  const { companyId } = useCompany()
  const { data: connections, isLoading } = useOneCConnections()
  const createMutation = useCreateOneCConnection()
  const updateMutation = useUpdateOneCConnection()
  const deleteMutation = useDeleteOneCConnection()
  const testMutation = useTestOneCConnection()

  const connection = connections?.[0] // пока один коннект на компанию

  const [form, setForm] = useState({
    name: connection?.name ?? '1С:Бухгалтерия',
    odataUrl: connection?.odataUrl ?? '',
    username: connection?.username ?? '',
    password: '',
    exchangePath: connection?.exchangePath ?? '',
    syncIntervalSec: connection?.syncIntervalSec ?? 300,
  })

  const [testResult, setTestResult] = useState<OneCTestResult | null>(null)

  // Обновляем форму при загрузке подключения
  useState(() => {
    if (connection) {
      setForm({
        name: connection.name,
        odataUrl: connection.odataUrl,
        username: connection.username,
        password: '',
        exchangePath: connection.exchangePath ?? '',
        syncIntervalSec: connection.syncIntervalSec,
      })
    }
  })

  const handleSave = async () => {
    if (!form.odataUrl || !form.username) {
      toast.error('Заполните URL и имя пользователя')
      return
    }

    try {
      if (connection) {
        await updateMutation.mutateAsync({
          id: connection.id,
          input: {
            name: form.name,
            odataUrl: form.odataUrl,
            username: form.username,
            password: form.password || undefined,
            exchangePath: form.exchangePath || undefined,
            syncIntervalSec: form.syncIntervalSec,
          },
        })
        toast.success('Подключение обновлено')
      } else {
        if (!form.password) {
          toast.error('Укажите пароль')
          return
        }
        await createMutation.mutateAsync({
          companyId,
          name: form.name,
          odataUrl: form.odataUrl,
          username: form.username,
          password: form.password,
          exchangePath: form.exchangePath || undefined,
          syncIntervalSec: form.syncIntervalSec,
        })
        toast.success('Подключение создано')
      }
    } catch {
      toast.error('Ошибка сохранения подключения')
    }
  }

  const handleTest = async () => {
    if (!connection) {
      toast.error('Сначала сохраните подключение')
      return
    }
    setTestResult(null)
    try {
      const result = await testMutation.mutateAsync(connection.id)
      setTestResult(result)
      if (result.available) {
        toast.success(`1С доступна. Найдено каталогов: ${result.catalogs.length}`)
      } else {
        toast.error(result.error || '1С недоступна')
      }
    } catch {
      toast.error('Ошибка тестирования подключения')
    }
  }

  const handleDelete = async () => {
    if (!connection) return
    try {
      await deleteMutation.mutateAsync(connection.id)
      setForm({
        name: '1С:Бухгалтерия',
        odataUrl: '',
        username: '',
        password: '',
        exchangePath: '',
        syncIntervalSec: 300,
      })
      setTestResult(null)
      toast.success('Подключение удалено')
    } catch {
      toast.error('Ошибка удаления')
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    )
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500/10">
              <Link2 className="size-5 text-orange-500" />
            </div>
            <div>
              <CardTitle>Подключение 1С</CardTitle>
              <CardDescription>OData-интерфейс для синхронизации с 1С:Бухгалтерия 3.0</CardDescription>
            </div>
          </div>
          {connection && (
            <StatusBadge status={connection.status} />
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Название</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="1С:Бухгалтерия"
            />
          </div>
          <div className="space-y-2">
            <Label>OData URL</Label>
            <Input
              value={form.odataUrl}
              onChange={(e) => setForm({ ...form, odataUrl: e.target.value })}
              placeholder="http://localhost/base/odata/standard.odata"
            />
          </div>
          <div className="space-y-2">
            <Label>Пользователь</Label>
            <Input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              placeholder="ClearLedger"
            />
          </div>
          <div className="space-y-2">
            <Label>Пароль</Label>
            <Input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder={connection ? '••••••••' : 'Пароль пользователя 1С'}
            />
          </div>
          <div className="space-y-2">
            <Label>Папка обмена</Label>
            <Input
              value={form.exchangePath}
              onChange={(e) => setForm({ ...form, exchangePath: e.target.value })}
              placeholder="/shared/1c_exchange"
            />
            <p className="text-xs text-muted-foreground">
              Папка для файлового обмена (EnterpriseData XML)
            </p>
          </div>
          <div className="space-y-2">
            <Label>Интервал синхронизации (сек)</Label>
            <Input
              type="number"
              min={60}
              max={86400}
              value={form.syncIntervalSec}
              onChange={(e) => setForm({ ...form, syncIntervalSec: parseInt(e.target.value) || 300 })}
            />
          </div>
        </div>

        <Separator />

        <div className="flex flex-wrap gap-3">
          <Button onClick={handleSave} disabled={isSaving}>
            {isSaving ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Save className="mr-2 size-4" />}
            {connection ? 'Обновить' : 'Создать'}
          </Button>
          {connection && (
            <>
              <Button variant="outline" onClick={handleTest} disabled={testMutation.isPending}>
                {testMutation.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <TestTube className="mr-2 size-4" />}
                Тест подключения
              </Button>
              <Button variant="destructive" size="icon" onClick={handleDelete} disabled={deleteMutation.isPending}>
                <Trash2 className="size-4" />
              </Button>
            </>
          )}
        </div>

        {testResult && (
          <div className={`rounded-lg border p-3 ${testResult.available ? 'border-green-500/30 bg-green-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
            <div className="flex items-center gap-2 mb-1">
              {testResult.available ? (
                <CheckCircle2 className="size-4 text-green-500" />
              ) : (
                <XCircle className="size-4 text-red-500" />
              )}
              <span className="text-sm font-medium">
                {testResult.available ? '1С доступна' : '1С недоступна'}
              </span>
            </div>
            {testResult.available && testResult.catalogs.length > 0 && (
              <p className="text-xs text-muted-foreground ml-6">
                Доступных каталогов: {testResult.catalogs.length}
              </p>
            )}
            {testResult.error && (
              <p className="text-xs text-red-500 ml-6">{testResult.error}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
    active: { label: 'Активно', variant: 'default' },
    inactive: { label: 'Неактивно', variant: 'secondary' },
    error: { label: 'Ошибка', variant: 'destructive' },
  }
  const { label, variant } = variants[status] ?? { label: status, variant: 'outline' as const }
  return <Badge variant={variant}>{label}</Badge>
}
