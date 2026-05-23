/**
 * Страница «1С → Подключение». Работающая форма с сохранением
 * в localStorage. Реальная проверка подключения требует бэкенда
 * (см. PROMPT_подключение_к_БП_ГИГ.md → параллельный агент).
 */

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@/components/ui/tabs'
import {
  Plug, Server, CheckCircle2, AlertCircle, Loader2, Save, Database, HardDrive, Webhook,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  getOneCConnection, saveOneCConnection, testOneCConnection, setOneCStatus,
  type OneCConnectionMode,
} from '@/services/oneCConnectionService'
import { format } from 'date-fns'

const STATUS_META: Record<string, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  not_configured: { label: 'Не настроено', color: 'text-muted-foreground', icon: AlertCircle },
  configured: { label: 'Настроено, не проверено', color: 'text-amber-500', icon: AlertCircle },
  testing: { label: 'Проверка…', color: 'text-blue-500', icon: Loader2 },
  connected: { label: 'Подключено', color: 'text-emerald-500', icon: CheckCircle2 },
  error: { label: 'Ошибка', color: 'text-destructive', icon: AlertCircle },
}

export function ConnectionPage() {
  const [conn, setConn] = useState(() => getOneCConnection())
  const [testing, setTesting] = useState(false)
  const status = STATUS_META[conn.status] ?? STATUS_META.not_configured
  const StatusIcon = status.icon

  function update<K extends keyof typeof conn>(key: K, value: (typeof conn)[K]) {
    setConn((prev) => ({ ...prev, [key]: value }))
  }

  function handleSave() {
    const saved = saveOneCConnection(conn)
    setConn(saved)
    toast.success('Настройки подключения сохранены')
  }

  async function handleTest() {
    setTesting(true)
    setOneCStatus('testing')
    setConn(getOneCConnection())
    try {
      // Сначала сохраняем то что в форме
      saveOneCConnection(conn)
      const result = await testOneCConnection()
      if (result.ok) {
        const updated = setOneCStatus('connected')
        setConn(updated)
        toast.success('Подключение к 1С установлено')
      } else {
        const updated = setOneCStatus('error', { error: result.message })
        setConn(updated)
        toast.error(result.message)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const updated = setOneCStatus('error', { error: msg })
      setConn(updated)
      toast.error(msg)
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Заголовок */}
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Подключение к 1С</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Связь с информационной базой 1С:Бухгалтерия для чтения справочников
          и закрытых периодов.
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
              <StatusIcon className={`h-3.5 w-3.5 ${conn.status === 'testing' ? 'animate-spin' : ''}`} />
              <span className="font-medium">{status.label}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0 space-y-1">
          {conn.lastTestedAt && (
            <p className="text-[11px] text-muted-foreground">
              Последний тест: {format(new Date(conn.lastTestedAt), 'dd.MM.yyyy HH:mm')}
            </p>
          )}
          {conn.lastSyncAt && (
            <p className="text-[11px] text-muted-foreground">
              Последняя синхронизация: {format(new Date(conn.lastSyncAt), 'dd.MM.yyyy HH:mm')}
            </p>
          )}
          {conn.configVersion && (
            <p className="text-[11px] text-muted-foreground">
              Конфигурация: <span className="font-mono text-foreground/70">{conn.configVersion}</span>
              {conn.platformVersion && (
                <> · Платформа: <span className="font-mono text-foreground/70">{conn.platformVersion}</span></>
              )}
            </p>
          )}
          {conn.lastError && conn.status === 'error' && (
            <p className="text-[11px] text-destructive whitespace-pre-wrap">{conn.lastError}</p>
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
          <Tabs value={conn.mode} onValueChange={(v) => update('mode', v as OneCConnectionMode)}>
            <TabsList className="grid w-full grid-cols-3 h-9">
              <TabsTrigger value="odata" className="text-xs gap-1.5">
                <Database className="h-3.5 w-3.5" />
                OData (HTTP)
              </TabsTrigger>
              <TabsTrigger value="com" className="text-xs gap-1.5">
                <HardDrive className="h-3.5 w-3.5" />
                COM (локально)
              </TabsTrigger>
              <TabsTrigger value="http_service" className="text-xs gap-1.5">
                <Webhook className="h-3.5 w-3.5" />
                HTTP-сервис
              </TabsTrigger>
            </TabsList>

            <TabsContent value="odata" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="odata-url" className="text-xs">URL публикации OData</Label>
                <Input
                  id="odata-url"
                  value={conn.odataUrl ?? ''}
                  onChange={(e) => update('odataUrl', e.target.value)}
                  placeholder="http://192.168.40.31/acc/odata/standard.odata/"
                  className="h-8 text-xs font-mono"
                />
                <p className="text-[10px] text-muted-foreground">
                  Полный URL до корня OData. Завершается на «/». Должен быть доступен через VPN ElsyPlus.
                </p>
              </div>
            </TabsContent>

            <TabsContent value="com" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="com-path" className="text-xs">Путь к файловой БД</Label>
                <Input
                  id="com-path"
                  value={conn.comPath ?? ''}
                  onChange={(e) => update('comPath', e.target.value)}
                  placeholder="D:\Users\magsp\GIG Base2"
                  className="h-8 text-xs font-mono"
                />
                <p className="text-[10px] text-muted-foreground">
                  Только для локальной разработки. Требует установленный 1С 8.3
                  и зарегистрированный V83.COMConnector.
                </p>
              </div>
            </TabsContent>

            <TabsContent value="http_service" className="space-y-3 mt-4">
              <div className="space-y-1.5">
                <Label htmlFor="http-url" className="text-xs">URL HTTP-сервиса расширения</Label>
                <Input
                  id="http-url"
                  value={conn.httpServiceUrl ?? ''}
                  onChange={(e) => update('httpServiceUrl', e.target.value)}
                  placeholder="http://192.168.40.31/acc/hs/clearledger/v1"
                  className="h-8 text-xs font-mono"
                />
                <p className="text-[10px] text-muted-foreground">
                  Если в БП ГИГ опубликован HTTP-сервис расширения TradeLedger.cfe
                  или GIG_Ledger.cfe — точка входа для pull-операций.
                </p>
              </div>
            </TabsContent>
          </Tabs>

          {/* Учётка */}
          <div className="grid sm:grid-cols-2 gap-3 pt-2 border-t border-border/40">
            <div className="space-y-1.5">
              <Label htmlFor="login" className="text-xs">Логин в 1С</Label>
              <Input
                id="login"
                value={conn.login}
                onChange={(e) => update('login', e.target.value)}
                placeholder="Администратор"
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-xs">Пароль</Label>
              <Input
                id="password"
                type="password"
                value={conn.password}
                onChange={(e) => update('password', e.target.value)}
                placeholder="••••••••"
                className="h-8 text-xs"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="org-inn" className="text-xs">ИНН организации</Label>
            <Input
              id="org-inn"
              value={conn.organizationInn}
              onChange={(e) => update('organizationInn', e.target.value)}
              placeholder="7839440090"
              className="h-8 text-xs font-mono w-48"
            />
            <p className="text-[10px] text-muted-foreground">
              Все запросы фильтруются по этой организации. Для ГИГ: 7839440090.
            </p>
          </div>

          <div className="flex items-center gap-2 pt-3 border-t border-border/40">
            <Button size="sm" onClick={handleSave} className="gap-1.5">
              <Save className="h-3.5 w-3.5" />
              Сохранить
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleTest}
              disabled={testing}
              className="gap-1.5"
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
              Проверить подключение
            </Button>
          </div>
        </CardContent>
      </Card>

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
              ['Реквизиты компании', 'Catalog_Организации (ИНН, КПП, юр.адрес, банковские счета)'],
              ['Учётная политика', 'Метод оценки запасов, режим НДС, ставки УСН'],
              ['Справочники', 'Контрагенты, Номенклатура, Договоры, Склады, ВидыНДС'],
              ['Закрытые периоды', 'ДатыЗапретаИзменения → эталон для сверки'],
              ['Документы и проводки', 'ОРП, ПТУ, СчётФактураПолученный + регистр «Хозрасчётный»'],
              ['Сверка с эталоном', 'Расхождения в незакрытом периоде vs закрытом'],
            ].map(([title, descr]) => (
              <li key={title as string} className="flex items-start gap-2">
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

      {/* Подсказка */}
      <Card className="py-3 gap-2 border-l-2 border-l-amber-500">
        <CardContent className="pt-0 pb-0">
          <p className="text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[9px] h-4 px-1 mr-1">i</Badge>
            Реальная проверка подключения требует бэкенда. Промпт для интеграции —{' '}
            <code className="text-[10px] bg-muted px-1 py-0.5 rounded">
              D:\Users\magsp\Ledger\PROMPT_подключение_к_БП_ГИГ.md
            </code>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
