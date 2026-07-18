/**
 * Страница «1С → Подключение». Работает с бэкендом TradeLedger
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
  RefreshCw, Trash2, FileText, History, Plus,
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
    urlPlaceholder: 'C:\\1C\\Bases\\Бухгалтерия',
    hint: 'V83.COMConnector. Только Windows + 32-bit Python. Для стендов разработки.',
  },
}

const STATUS_META: Record<string, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  inactive: { label: 'Не проверено', color: 'text-muted-foreground', icon: AlertCircle },
  active:   { label: 'Подключено', color: 'text-emerald-400/80', icon: CheckCircle2 },
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

  // Выбранное подключение: id существующего, 'new' — режим создания, null — initial.
  const [selectedId, setSelectedId] = useState<string | 'new' | null>(null)
  const connection = selectedId && selectedId !== 'new'
    ? connections?.find((c) => c.id === selectedId) ?? null
    : null
  const isNew = selectedId === 'new'
  const { data: history } = useSyncHistory(connection?.id ?? '')

  const emptyForm = {
    name: '', mode: 'com' as OneCConnectionMode, odataUrl: '', username: '', password: '',
  }
  const [form, setForm] = useState({ ...emptyForm })
  const [testResult, setTestResult] = useState<OneCTestResult | null>(null)

  // Автовыбор первого подключения при загрузке (если ещё ничего не выбрано).
  useEffect(() => {
    if (selectedId === null && connections && connections.length > 0) {
      setSelectedId(connections[0].id)
    }
  }, [connections, selectedId])

  // Подстановка полей выбранного подключения в форму (или сброс для нового).
  useEffect(() => {
    setTestResult(null)
    if (connection) {
      setForm({
        name: connection.name,
        mode: connection.mode,
        odataUrl: connection.odataUrl,
        username: connection.username,
        password: '', // не возвращается с бэка
      })
    } else if (isNew) {
      setForm({ ...emptyForm, name: '1С:Бухгалтерия' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection?.id, isNew])

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error('Укажите название подключения (напр. «БП», «УТ», «Розница»)')
      return
    }
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
        const created = await createMutation.mutateAsync({
          companyId,
          name: form.name,
          mode: form.mode,
          odataUrl: form.odataUrl,
          username: form.username,
          password: form.password,
        })
        toast.success('Подключение создано')
        if (created?.id) setSelectedId(created.id)
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
    if (!confirm(`Удалить подключение «${connection.name}»?`)) return
    try {
      await deleteMutation.mutateAsync(connection.id)
      setSelectedId(null) // автовыбор первого из оставшихся
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
        <h1 className="text-xl font-semibold tracking-tight">Подключения к 1С</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Информационные базы 1С компании. Можно подключить несколько баз и конфигураций
          (Бухгалтерия, УТ, Розница, КА…) — каждое подключение принадлежит только этой
          компании. Pull-чтение справочников и документов; запись в 1С выполняет её расширение.
        </p>
      </div>

      {/* Список подключений компании */}
      <Card className="py-4 gap-3">
        <CardHeader className="pb-0">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="h-4 w-4 text-muted-foreground" />
              Подключения компании
              {connections && connections.length > 0 && (
                <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{connections.length}</Badge>
              )}
            </CardTitle>
            <Button size="sm" variant="outline" className="gap-1.5 h-8" onClick={() => setSelectedId('new')}>
              <Plus className="h-3.5 w-3.5" /> Добавить
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {isLoading && <p className="text-xs text-muted-foreground">Загрузка…</p>}
          {!isLoading && (!connections || connections.length === 0) && (
            <p className="text-xs text-muted-foreground">
              Подключений нет. Нажмите «Добавить», чтобы настроить первую базу 1С.
            </p>
          )}
          {connections && connections.length > 0 && (
            <div className="space-y-1.5">
              {connections.map((c) => {
                const ModeIcon = MODE_META[c.mode]?.icon ?? Database
                const st = STATUS_META[c.status] ?? STATUS_META.inactive
                const StIcon = st.icon
                const active = c.id === selectedId
                return (
                  <button key={c.id} onClick={() => setSelectedId(c.id)}
                    className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors ${active ? 'border-primary bg-primary/5' : 'border-border/50 hover:bg-muted/50'}`}>
                    <ModeIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium">{c.name}</div>
                      <div className="truncate font-mono text-[10px] text-muted-foreground">{c.odataUrl || MODE_META[c.mode]?.label}</div>
                    </div>
                    <span className={`flex shrink-0 items-center gap-1 text-[11px] ${st.color}`}>
                      <StIcon className="h-3 w-3" />
                      {st.label}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Статус выбранного подключения */}
      {connection && (
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
      )}

      {/* Параметры подключения (редактирование выбранного / новое) */}
      {(connection || isNew) && (
      <Card className="py-4 gap-3">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm">{isNew ? 'Новое подключение' : `Параметры — ${connection?.name ?? ''}`}</CardTitle>
          <CardDescription className="text-xs">
            Выберите режим и заполните поля. Сохранение не запускает проверку
            автоматически — нажмите «Проверить».
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-name" className="text-xs">Название / конфигурация</Label>
            <Input id="conn-name" value={form.name} onChange={(e) => update('name', e.target.value)}
              placeholder="напр. БП ГИГ, УТ Склад, Розница" className="h-8 text-xs" />
          </div>
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
      )}

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
                      log.status === 'success' || log.status === 'completed' ? 'text-emerald-400/80'
                        : log.status === 'error' ? 'text-destructive'
                        : 'text-amber-400/80'
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
              ['Сверка', 'Локальные документы ↔ эталон 1С:Бухгалтерии компании'],
              ['Pull-only', 'TradeLedger только читает. Запись в 1С — её расширение тянет данные из TradeLedger API'],
            ].map(([title, descr]) => (
              <li key={title} className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400/80 mt-0.5 shrink-0" />
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
