/**
 * Страница «1С → Подключение». Работает с бэкендом ClearLedger
 * (POST /api/onec/connections, тесты и синхронизации) через хуки
 * useOneCSync. Два режима: OData (HTTP) и COM (V83.COMConnector
 * на локальной файловой БД).
 */

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@/components/ui/tabs'
import {
  Plug, Server, CheckCircle2, AlertCircle, Loader2, Save, Database, HardDrive,
  RefreshCw, Trash2, FileText, History,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

import {
  useOneCConnections,
  useCreateOneCConnection,
  useUpdateOneCConnection,
  useDeleteOneCConnection,
  useTestOneCConnection,
  useSyncCatalogs,
  useSyncDocuments,
  useSyncHistory,
} from '@/hooks/useOneCSync'
import { useCompany } from '@/contexts/CompanyContext'
import type { OneCConnectionMode, OneCTestResult } from '@/types'

const MODE_META: Record<OneCConnectionMode, {
  label: string
  icon: typeof Database
  urlLabel: string
  urlPlaceholder: string
  hint: string
}> = {
  odata: {
    label: 'OData (HTTP)',
    icon: Database,
    urlLabel: 'URL публикации OData',
    urlPlaceholder: 'http://192.168.40.31/acc/odata/standard.odata',
    hint: 'Полный URL до корня OData. Apache/IIS публикация. Доступ через VPN ElsyPlus.',
  },
  com: {
    label: 'COM (локально)',
    icon: HardDrive,
    urlLabel: 'Путь к файловой БД или строка соединения',
    urlPlaceholder: 'D:\\Users\\magsp\\GIG Base2',
    hint: 'V83.COMConnector. Только Windows + 32-bit Python. Для стендов разработки.',
  },
}

const STATUS_META: Record<string, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  inactive: { label: 'Не проверено', color: 'text-muted-foreground', icon: AlertCircle },
  active:   { label: 'Подключено', color: 'text-emerald-500', icon: CheckCircle2 },
  error:    { label: 'Ошибка', color: 'text-destructive', icon: AlertCircle },
}

export function ConnectionPage() {
  const { companyId } = useCompany()
  const { data: connections, isLoading } = useOneCConnections()
  const createMutation = useCreateOneCConnection()
  const updateMutation = useUpdateOneCConnection()
  const deleteMutation = useDeleteOneCConnection()
  const testMutation = useTestOneCConnection()
  const syncCatalogsMutation = useSyncCatalogs()
  const syncDocumentsMutation = useSyncDocuments()

  const connection = connections?.[0]
  const { data: history } = useSyncHistory(connection?.id ?? '')

  const [form, setForm] = useState({
    name: '1С:Бухгалтерия',
    mode: 'com' as OneCConnectionMode,
    odataUrl: '',
    username: '',
    password: '',
  })
  const [testResult, setTestResult] = useState<OneCTestResult | null>(null)

  // Подтягиваем поля из существующего коннекта в форму при первой загрузке.
  useEffect(() => {
    if (connection) {
      setForm((prev) => ({
        ...prev,
        name: connection.name,
        mode: connection.mode,
        odataUrl: connection.odataUrl,
        username: connection.username,
        // password не возвращается с бэка — поле остаётся пустым в форме.
      }))
    }
  }, [connection?.id])

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    if (!form.odataUrl.trim() || !form.username.trim()) {
      toast.error('Заполните URL/путь и имя пользователя')
      return
    }
    try {
      if (connection) {
        await updateMutation.mutateAsync({
          id: connection.id,
          input: {
            name: form.name,
            mode: form.mode,
            odataUrl: form.odataUrl,
            username: form.username,
            password: form.password || undefined,
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
          mode: form.mode,
          odataUrl: form.odataUrl,
          username: form.username,
          password: form.password,
        })
        toast.success('Подключение создано')
      }
      setTestResult(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка сохранения подключения')
    }
  }

  async function handleTest() {
    if (!connection) {
      toast.error('Сначала сохраните подключение')
      return
    }
    setTestResult(null)
    try {
      const result = await testMutation.mutateAsync(connection.id)
      setTestResult(result)
      if (result.available) {
        toast.success(`Подключение OK. Доступно каталогов: ${result.catalogs.length}`)
      } else {
        toast.error(result.error || '1С недоступна')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка теста подключения')
    }
  }

  async function handleSyncCatalogs() {
    if (!connection) return
    try {
      const r = await syncCatalogsMutation.mutateAsync(connection.id)
      toast.success(
        `Справочники синхронизированы. Создано ${r.stats.created}, обновлено ${r.stats.updated}, ошибок ${r.stats.errors}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка синхронизации')
    }
  }

  async function handleSyncDocuments() {
    if (!connection) return
    try {
      const r = await syncDocumentsMutation.mutateAsync(connection.id)
      toast.success(
        `Документы синхронизированы. Создано ${r.stats.created}, обновлено ${r.stats.updated}, ошибок ${r.stats.errors}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка синхронизации')
    }
  }

  async function handleDelete() {
    if (!connection) return
    if (!confirm('Удалить подключение к 1С?')) return
    try {
      await deleteMutation.mutateAsync(connection.id)
      setForm({ name: '1С:Бухгалтерия', mode: 'com', odataUrl: '', username: '', password: '' })
      setTestResult(null)
      toast.success('Подключение удалено')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка удаления')
    }
  }

  const status = STATUS_META[connection?.status ?? 'inactive']
  const StatusIcon = status.icon
  const isSaving = createMutation.isPending || updateMutation.isPending
  const isTesting = testMutation.isPending
  const isSyncingCat = syncCatalogsMutation.isPending
  const isSyncingDoc = syncDocumentsMutation.isPending

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Заголовок */}
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Подключение к 1С</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Связь с информационной базой 1С:Бухгалтерия 3.0 для pull-чтения справочников
          и документов. Запись в 1С выполняется её собственным расширением.
        </p>
      </div>

      {/* Статус */}
      <Card className="py-4 gap-3">
        <CardHeader className="pb-0">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <Server className="h-4 w-4 text-muted-foreground" />
              Статус
            </CardTitle>
            <div className={`flex items-center gap-1.5 text-xs ${status.color}`}>
              <StatusIcon className="h-3.5 w-3.5" />
              <span className="font-medium">{status.label}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0 space-y-1">
          {!connection && !isLoading && (
            <p className="text-[11px] text-muted-foreground">
              Подключение для компании не создано.
            </p>
          )}
          {connection?.lastSyncAt && (
            <p className="text-[11px] text-muted-foreground">
              Последняя синхронизация: {format(new Date(connection.lastSyncAt), 'dd.MM.yyyy HH:mm')}
            </p>
          )}
          {testResult?.available && testResult.catalogs.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              Доступных Catalog_*: <span className="font-mono">{testResult.catalogs.length}</span>
            </p>
          )}
          {testResult?.error && (
            <p className="text-[11px] text-destructive whitespace-pre-wrap">{testResult.error}</p>
          )}
        </CardContent>
      </Card>

      {/* Параметры подключения */}
      <Card className="py-4 gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm">Параметры подключения</CardTitle>
          <CardDescription className="text-xs">
            Выберите режим и заполните поля. Сохранение не запускает проверку
            автоматически — нажмите «Проверить».
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0 space-y-4">
          <Tabs value={form.mode} onValueChange={(v) => update('mode', v as OneCConnectionMode)}>
            <TabsList className="grid w-full grid-cols-2 h-9">
              {(['odata', 'com'] as const).map((m) => {
                const Icon = MODE_META[m].icon
                return (
                  <TabsTrigger key={m} value={m} className="text-xs gap-1.5">
                    <Icon className="h-3.5 w-3.5" />
                    {MODE_META[m].label}
                  </TabsTrigger>
                )
              })}
            </TabsList>

            {(['odata', 'com'] as const).map((m) => (
              <TabsContent key={m} value={m} className="space-y-3 mt-4">
                <div className="space-y-1.5">
                  <Label htmlFor={`${m}-url`} className="text-xs">{MODE_META[m].urlLabel}</Label>
                  <Input
                    id={`${m}-url`}
                    value={form.mode === m ? form.odataUrl : ''}
                    onChange={(e) => update('odataUrl', e.target.value)}
                    placeholder={MODE_META[m].urlPlaceholder}
                    className="h-8 text-xs font-mono"
                  />
                  <p className="text-[10px] text-muted-foreground">{MODE_META[m].hint}</p>
                </div>
              </TabsContent>
            ))}
          </Tabs>

          {/* Учётка */}
          <div className="grid sm:grid-cols-2 gap-3 pt-2 border-t border-border/40">
            <div className="space-y-1.5">
              <Label htmlFor="login" className="text-xs">Логин в 1С</Label>
              <Input
                id="login"
                value={form.username}
                onChange={(e) => update('username', e.target.value)}
                placeholder="Администратор"
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-xs">Пароль</Label>
              <Input
                id="password"
                type="password"
                value={form.password}
                onChange={(e) => update('password', e.target.value)}
                placeholder={connection ? '••••• (заполните для смены)' : 'Пароль пользователя 1С'}
                className="h-8 text-xs"
              />
            </div>
          </div>

          <div className="flex items-center flex-wrap gap-2 pt-3 border-t border-border/40">
            <Button size="sm" onClick={handleSave} disabled={isSaving} className="gap-1.5">
              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {connection ? 'Обновить' : 'Создать'}
            </Button>
            {connection && (
              <>
                <Button size="sm" variant="outline" onClick={handleTest} disabled={isTesting} className="gap-1.5">
                  {isTesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
                  Проверить
                </Button>
                <Button size="sm" variant="outline" onClick={handleSyncCatalogs} disabled={isSyncingCat} className="gap-1.5">
                  {isSyncingCat ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  Справочники
                </Button>
                <Button size="sm" variant="outline" onClick={handleSyncDocuments} disabled={isSyncingDoc} className="gap-1.5">
                  {isSyncingDoc ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
                  Документы
                </Button>
                <Button size="sm" variant="ghost" onClick={handleDelete} disabled={deleteMutation.isPending}
                        className="gap-1.5 ml-auto text-destructive hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                  Удалить
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* История синхронизаций */}
      {connection && history && history.length > 0 && (
        <Card className="py-4 gap-3">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm flex items-center gap-2">
              <History className="h-4 w-4 text-muted-foreground" />
              Последние синхронизации
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-1.5">
              {history.slice(0, 10).map((log) => (
                <div key={log.id}
                     className="flex items-center justify-between text-xs py-1.5 px-2 rounded hover:bg-muted/50">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[9px] h-4 px-1">{log.syncType}</Badge>
                    <span className="text-muted-foreground">
                      {format(new Date(log.startedAt), 'dd.MM HH:mm:ss')}
                    </span>
                    <span className={
                      log.status === 'success' || log.status === 'completed' ? 'text-emerald-500'
                        : log.status === 'error' ? 'text-destructive'
                        : 'text-amber-500'
                    }>
                      {log.status}
                    </span>
                  </div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    p={log.itemsProcessed} +{log.itemsCreated} ~{log.itemsUpdated} !{log.itemsErrors}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Что даёт подключение */}
      <Card className="py-4 gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-2">
            <Plug className="h-4 w-4 text-muted-foreground" />
            Что даёт подключение к 1С
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <ul className="space-y-1.5 text-xs">
            {[
              ['Справочники', 'Контрагенты, Номенклатура, Договоры, Склады, Организации'],
              ['Документы', 'ПТУ, ОРП, ОПЗС, КорректировкаПоступления'],
              ['Сверка', 'Локальные документы ClearLedger ↔ эталон БП ГИГ'],
              ['Pull-only', 'ClearLedger только читает. Запись в 1С — её расширение тянет данные из ClearLedger API'],
            ].map(([title, descr]) => (
              <li key={title} className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium">{title}</span>
                  <span className="text-muted-foreground"> — {descr}</span>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
