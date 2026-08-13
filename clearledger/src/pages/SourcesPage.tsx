/**
 * Источники данных — подключения к внешним системам.
 * Настройка URL, credentials, типов документов.
 */

import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useCanManage } from '@/hooks/useCanManage'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import { getSources, loadSources, createSource, updateSource, deleteSource, testSource, frontendSourceType } from '@/services/sourceService'
import { getSourceTypes, type SetupFieldSchema } from '@/services/catalogService'
import { isApiEnabled } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { SOURCE_TYPE_META, BACKEND_SOURCE_META, type Source } from '@/types/channel'
import { stsTestConnection } from '@/services/fuel/stsApiClient'
import { checkOnlineOrders } from '@/services/fuel/onlineOrdersService'
import { tradecorpTestConnection } from '@/services/tradecorp/tradecorpApiClient'
import {
  Plus, Trash2, Globe, Database, Mail, HardDrive,
  Webhook, FolderOpen, FileCheck, Cloud, Server,
  Loader2, CheckCircle2, XCircle, AlertTriangle, Circle, Save, Plug,
  Fuel, CreditCard, Activity, Tag, Ticket, Cylinder,
  BookCheck, Smartphone, Banknote, Receipt, ScanBarcode, Landmark,
} from 'lucide-react'
import { toast } from 'sonner'

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Globe, Database, Mail, HardDrive, Webhook, FolderOpen, FileCheck, Cloud, Fuel, CreditCard, Activity, Tag, Ticket, Cylinder,
  BookCheck, Smartphone, Banknote, Receipt, ScanBarcode, Server, Landmark,
}

const STATUS_COLORS: Record<string, string> = {
  connected: 'text-emerald-500',
  disconnected: 'text-muted-foreground',
  error: 'text-destructive',
  draft: 'text-amber-500',
}

const STATUS_LABELS: Record<string, string> = {
  connected: 'Подключён',
  disconnected: 'Отключён',
  error: 'Ошибка',
  draft: 'Настраивается',
}

const STATUS_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  connected: CheckCircle2,
  disconnected: Circle,
  error: XCircle,
  draft: AlertTriangle,
}

/** Форма настройки подключения REST API */
function RestConnectionForm({ source, onUpdate }: { source: Source; onUpdate: (s: Source) => void }) {
  const [url, setUrl] = useState(source.connection.url || 'https://pos.autooplata.ru/tms')
  const [login, setLogin] = useState(source.connection.login || 'UserApi')
  const [password, setPassword] = useState(source.connection.password ?? '')
  const [systemCode, setSystemCode] = useState(source.connection.systemCode || '65')
  const [testing, setTesting] = useState(false)
  const [testOk, setTestOk] = useState<boolean | null>(null)
  const [testError, setTestError] = useState('')

  async function handleTest() {
    setTesting(true)
    setTestOk(null)
    const testUrl = import.meta.env.DEV ? '/tms' : url
    const result = await stsTestConnection(testUrl, login, password)
    setTestOk(result.ok)
    setTestError(result.error ?? '')
    setTesting(false)
    if (result.ok) toast.success(`Подключено — ${result.shiftsCount} смен найдено`)
    else toast.error(result.error ?? 'Ошибка подключения')
  }

  async function handleSave() {
    const updated = await updateSource(source.id, {
      connection: { url, login, password, systemCode },
      status: testOk ? 'connected' : source.status,
    })
    if (updated) { onUpdate(updated); toast.success('Источник сохранён') }
  }

  return (
    <div className="space-y-3 pt-2">
      <div className="space-y-1.5">
        <Label className="text-xs">URL API</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://pos.autooplata.ru/tms" className="h-8 text-sm" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs">Логин</Label>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="UserApi" className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Пароль</Label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-8 text-sm" />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">Код системы (сети)</Label>
        <Input value={systemCode} onChange={(e) => setSystemCode(e.target.value)} className="h-8 text-sm w-24" />
      </div>

      {/* Типы документов */}
      {source.docTypes.length > 0 && (
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Доступные типы документов</Label>
          <div className="space-y-1">
            {source.docTypes.map((dt) => (
              <div key={dt.id} className="flex items-center gap-2 text-xs py-1 px-2 rounded bg-muted/30">
                <Badge variant="outline" className="text-[9px] h-4 px-1.5 font-mono">{dt.id}</Badge>
                <span className="font-medium">{dt.name}</span>
                {dt.endpoint && <span className="text-muted-foreground/50 ml-auto font-mono text-[10px]">{dt.endpoint}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleTest} disabled={testing || !login}>
          {testing ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Plug className="h-3 w-3 mr-1" />}
          Проверить подключение
        </Button>
        <Button size="sm" className="h-8 text-xs gap-1" onClick={handleSave}>
          <Save className="h-3 w-3" />
          Сохранить
        </Button>
        {testOk != null && (
          <span className="flex items-center gap-1 text-xs">
            {testOk
              ? <><CheckCircle2 className="h-4 w-4 text-emerald-500" /><span className="text-emerald-500">Подключено</span></>
              : <><XCircle className="h-4 w-4 text-destructive" /><span className="text-destructive truncate max-w-[200px]">{testError}</span></>
            }
          </span>
        )}
      </div>
    </div>
  )
}

/** Форма настройки подключения MSTO */
function MstoConnectionForm({ source, onUpdate }: { source: Source; onUpdate: (s: Source) => void }) {
  const [url, setUrl] = useState(source.connection.url || 'http://46.229.214.21:3000')
  const [login, setLogin] = useState(source.connection.login || 'tf-integration')
  const [password, setPassword] = useState(source.connection.password ?? '')
  const [testing, setTesting] = useState(false)
  const [testOk, setTestOk] = useState<boolean | null>(null)
  const [testError, setTestError] = useState('')

  async function handleTest() {
    setTesting(true)
    setTestOk(null)
    try {
      // Проверка идёт СЕРВЕРНО (reconciliation_proxy, креды MSTO из .env как у
      // TradeFrame) — секрет не уходит в браузер, пароль в форме не требуется.
      const result = await checkOnlineOrders()
      setTestOk(result.available)
      setTestError(result.error ?? '')
      if (result.available) toast.success(`MSTO подключено — ${result.service_points ?? 0} станций`)
      else toast.error(result.error ?? 'Ошибка подключения MSTO')
    } catch {
      setTestOk(false)
      setTestError('Ошибка запроса (бэкенд недоступен?)')
      toast.error('Ошибка подключения MSTO')
    }
    setTesting(false)
  }

  async function handleSave() {
    const updated = await updateSource(source.id, {
      connection: { url, login, password },
      status: testOk ? 'connected' : source.status,
    })
    if (updated) { onUpdate(updated); toast.success('Источник MSTO сохранён') }
  }

  return (
    <div className="space-y-3 pt-2">
      <div className="space-y-1.5">
        <Label className="text-xs">URL MSTO API</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="http://46.229.214.21:3000" className="h-8 text-sm" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs">Логин</Label>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="tf-integration" className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Пароль</Label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-8 text-sm" placeholder="•••• (пусто — не менять)" />
          <p className="text-[10px] text-muted-foreground">Сохраните, затем «Проверить подключение». Пусто — не перезаписывать; если креды не заданы — берётся .env (fallback).</p>
        </div>
      </div>
      {source.docTypes.length > 0 && (
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Доступные типы документов</Label>
          <div className="space-y-1">
            {source.docTypes.map((dt) => (
              <div key={dt.id} className="flex items-center gap-2 text-xs py-1 px-2 rounded bg-muted/30">
                <Badge variant="outline" className="text-[9px] h-4 px-1.5 font-mono">{dt.id}</Badge>
                <span className="font-medium">{dt.name}</span>
                {dt.endpoint && <span className="text-muted-foreground/50 ml-auto font-mono text-[10px]">{dt.endpoint}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleTest} disabled={testing || !login}>
          {testing ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Plug className="h-3 w-3 mr-1" />}
          Проверить подключение
        </Button>
        <Button size="sm" className="h-8 text-xs gap-1" onClick={handleSave}>
          <Save className="h-3 w-3" />
          Сохранить
        </Button>
        {testOk != null && (
          <span className="flex items-center gap-1 text-xs">
            {testOk
              ? <><CheckCircle2 className="h-4 w-4 text-emerald-500" /><span className="text-emerald-500">Подключено</span></>
              : <><XCircle className="h-4 w-4 text-destructive" /><span className="text-destructive truncate max-w-[200px]">{testError}</span></>
            }
          </span>
        )}
      </div>
    </div>
  )
}

/** Форма настройки подключения TradeCorp */
function TradecorpConnectionForm({ source, onUpdate }: { source: Source; onUpdate: (s: Source) => void }) {
  const [url, setUrl] = useState(source.connection.url || 'https://api.autooplata.ru')
  const [login, setLogin] = useState(source.connection.login ?? '')
  const [password, setPassword] = useState(source.connection.password ?? '')
  const [emitentId, setEmitentId] = useState(source.connection.emitentId || '15')
  const [testing, setTesting] = useState(false)
  const [testOk, setTestOk] = useState<boolean | null>(null)
  const [testError, setTestError] = useState('')

  async function handleTest() {
    setTesting(true)
    setTestOk(null)
    const testUrl = import.meta.env.DEV ? '/tradecorp' : url
    const result = await tradecorpTestConnection(testUrl, login, password, emitentId)
    setTestOk(result.ok)
    setTestError(result.error ?? '')
    setTesting(false)
    if (result.ok) toast.success(`TradeCorp подключено — ${result.txCount} транзакций за неделю`)
    else toast.error(result.error ?? 'Ошибка подключения TradeCorp')
  }

  async function handleSave() {
    const updated = await updateSource(source.id, {
      connection: { url, login, password, emitentId },
      status: testOk ? 'connected' : source.status,
    })
    if (updated) { onUpdate(updated); toast.success('Источник TradeCorp сохранён') }
  }

  return (
    <div className="space-y-3 pt-2">
      <div className="space-y-1.5">
        <Label className="text-xs">URL TradeCorp API</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://api.autooplata.ru" className="h-8 text-sm" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs">Логин</Label>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Пароль</Label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-8 text-sm" />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">ID эмитента</Label>
        <Input value={emitentId} onChange={(e) => setEmitentId(e.target.value)} className="h-8 text-sm w-24" />
      </div>
      {source.docTypes.length > 0 && (
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Доступные типы документов</Label>
          <div className="space-y-1">
            {source.docTypes.map((dt) => (
              <div key={dt.id} className="flex items-center gap-2 text-xs py-1 px-2 rounded bg-muted/30">
                <Badge variant="outline" className="text-[9px] h-4 px-1.5 font-mono">{dt.id}</Badge>
                <span className="font-medium">{dt.name}</span>
                {dt.endpoint && <span className="text-muted-foreground/50 ml-auto font-mono text-[10px]">{dt.endpoint}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleTest} disabled={testing || !login}>
          {testing ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Plug className="h-3 w-3 mr-1" />}
          Проверить подключение
        </Button>
        <Button size="sm" className="h-8 text-xs gap-1" onClick={handleSave}>
          <Save className="h-3 w-3" />
          Сохранить
        </Button>
        {testOk != null && (
          <span className="flex items-center gap-1 text-xs">
            {testOk
              ? <><CheckCircle2 className="h-4 w-4 text-emerald-500" /><span className="text-emerald-500">Подключено</span></>
              : <><XCircle className="h-4 w-4 text-destructive" /><span className="text-destructive truncate max-w-[200px]">{testError}</span></>
            }
          </span>
        )}
      </div>
    </div>
  )
}

/** Реальная мета типа источника (по backend source_type, fallback — укрупнённый type) */
function sourceMeta(source: Source): { label: string; icon: string; category?: string } {
  if (source.backendType && BACKEND_SOURCE_META[source.backendType]) {
    return BACKEND_SOURCE_META[source.backendType]
  }
  return SOURCE_TYPE_META[source.type]
}

/** Какая форма подключения подходит реальному типу источника */
function sourceFormKind(source: Source): 'sts' | 'msto' | 'tradecorp' | 'generic' {
  const bt = source.backendType
  if (bt) {
    if (bt === 'sts' || bt === 'sts_transactions') return 'sts'
    if (bt === 'msto') return 'msto'
    if (bt === 'tradecorp') return 'tradecorp'
    return 'generic'
  }
  if (source.type === 'rest') return 'sts'
  if (source.type === 'msto') return 'msto'
  if (source.type === 'tradecorp') return 'tradecorp'
  return 'generic'
}

/** Заглушка для типов без специализированной формы */
function GenericConnectionForm({ source }: { source: Source }) {
  return (
    <div className="py-3 text-xs text-muted-foreground">
      Настройка подключения типа «{sourceMeta(source).label}» — в следующей версии.
    </div>
  )
}

const ADAPTER_STATUS_META: Record<string, { label: string; cls: string; dot: string }> = {
  available: { label: 'Рабочий', cls: 'border-emerald-400/50 text-emerald-300/80', dot: 'bg-emerald-400' },
  planned: { label: 'Запланирован', cls: 'border-amber-400/50 text-amber-300/80', dot: 'bg-amber-400' },
  partial: { label: 'Частично', cls: 'border-blue-400/50 text-blue-300/80', dot: 'bg-blue-400' },
}

/**
 * Панель источника по setup_schema адаптера (каталог). Логика: админ резервирует
 * источник (draft + описание), менеджер компании настраивает реквизиты по описанию.
 * Показывает: статус/версию интеграции · логику обработки и данные · форму доступов.
 */
export function SchemaConnectionForm({ source, onUpdate }: { source: Source; onUpdate: (s: Source) => void }) {
  const { companyId } = useCompany()
  const { data: types, isLoading } = useQuery({
    queryKey: ['catalog', 'source-types'],
    queryFn: getSourceTypes,
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const item = types?.find((t) => t.source_type === source.backendType)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    if (!item) return
    const init: Record<string, string> = {}
    for (const f of item.setup_schema) init[f.key] = source.connection[f.key] ?? f.default_value ?? ''
    setValues(init)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, source.id])

  if (!isApiEnabled()) {
    return <div className="py-3 text-xs text-muted-foreground">Настройка доступна при подключённом API.</div>
  }
  if (isLoading) {
    return <div className="py-3 flex justify-center"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
  }
  if (!item) return <GenericConnectionForm source={source} />

  const st = ADAPTER_STATUS_META[item.status] ?? ADAPTER_STATUS_META.planned
  const set = (k: string, v: string) => setValues((p) => ({ ...p, [k]: v }))

  async function handleSave() {
    if (!item) return
    setSaving(true)
    const cfg: Record<string, string> = {}
    for (const f of item.setup_schema) {
      const v = values[f.key] ?? ''
      if (f.secret && v === '') continue // не затирать сохранённый секрет пустым
      cfg[f.key] = v
    }
    const updated = await updateSource(source.id, { connection: cfg })
    setSaving(false)
    if (updated) { onUpdate(updated); toast.success('Реквизиты сохранены') }
  }

  async function handleTest() {
    setTesting(true)
    const r = await testSource(source.id)
    setTesting(false)
    if (r.ok) toast.success(r.message ?? 'Подключение успешно')
    else if (r.planned) toast.info(r.message ?? 'Источник запланирован — выгрузка ещё не реализована')
    else toast.error(r.message ?? 'Ошибка подключения')
    if (companyId) {
      await loadSources(companyId)
      const s = getSources().find((x) => x.id === source.id)
      if (s) onUpdate(s)
    }
  }

  // Группировка полей по смыслу — отдельные секции-карточки.
  const ungrouped = item.setup_schema.filter((f) => !f.group)
  const groupNames: string[] = []
  const groups: Record<string, SetupFieldSchema[]> = {}
  for (const f of item.setup_schema) {
    if (!f.group) continue
    if (!groups[f.group]) { groups[f.group] = []; groupNames.push(f.group) }
    groups[f.group].push(f)
  }

  const renderField = (f: SetupFieldSchema) => (
    <div key={f.key} className="space-y-1.5 min-w-0">
      <Label className="text-[11px] font-medium text-foreground/70">{f.label}{f.required ? ' *' : ''}</Label>
      {f.type === 'select' && f.options ? (
        <Select value={values[f.key] ?? ''} onValueChange={(v) => set(f.key, v)}>
          <SelectTrigger className="h-9 text-[13px]"><SelectValue placeholder="—" /></SelectTrigger>
          <SelectContent>
            {f.options.map((o) => <SelectItem key={o.value} value={o.value} className="text-[13px]">{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
      ) : (
        <Input
          type={f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}
          value={values[f.key] ?? ''}
          onChange={(e) => set(f.key, e.target.value)}
          placeholder={f.secret ? '•••• (пусто — не менять)' : (f.placeholder ?? '')}
          className="h-9 text-[13px]"
        />
      )}
      {f.help_text && <p className="text-[11px] text-muted-foreground leading-snug">{f.help_text}</p>}
    </div>
  )

  const grid = 'grid sm:grid-cols-2 gap-x-4 gap-y-2.5'
  const SrcIcon = ICON_MAP[item.icon] ?? Plug
  const modeField = item.setup_schema.find((f) => f.key === 'mode')
  const modeLabel = modeField?.options?.find((o) => o.value === (values.mode ?? ''))?.label ?? null
  const tile = 'rounded-xl border border-border/60 bg-card/40 px-3 py-2.5 flex flex-col gap-2 min-w-0'
  const cap = 'text-[10px] uppercase tracking-wide text-muted-foreground/70'

  return (
    <div className="py-2 space-y-3 text-[13px]">
      {/* Статус-плитки */}
      <div className="grid grid-cols-2 gap-2">
        <div className={tile}>
          <div className="flex items-center justify-between">
            <SrcIcon className="h-4 w-4 text-muted-foreground" />
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground/90">
              <span className={`h-2 w-2 rounded-full ${st.dot}`} />{st.label}
            </span>
          </div>
          <div className="min-w-0"><div className={cap}>Тип источника</div>
            <div className="text-sm font-medium text-foreground break-words">{item.label}</div></div>
        </div>
        <div className={tile}>
          <Activity className="h-4 w-4 text-muted-foreground" />
          <div><div className={cap}>Версия интеграции</div>
            <div className="text-sm font-mono font-medium text-foreground">{item.version ?? '1.0'}</div></div>
        </div>
        {modeLabel != null && (
          <div className={tile}>
            <Plug className="h-4 w-4 text-muted-foreground" />
            <div className="min-w-0"><div className={cap}>Способ получения</div>
              <div className="text-sm font-medium text-foreground break-words">{modeLabel}</div></div>
          </div>
        )}
        <div className={tile}>
          <Database className="h-4 w-4 text-muted-foreground" />
          <div className="min-w-0"><div className={cap}>Состояние</div>
            <div className="text-sm font-medium text-foreground break-words">{STATUS_LABELS[source.status] ?? source.status}</div></div>
        </div>
      </div>

      {/* Карточка: логика обработки + данные */}
      {(item.description || item.setup_guide || item.available_doc_types.length > 0) && (
        <div className="rounded-xl border border-border/60 bg-card/40 overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/40">
            <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-primary/10 shrink-0">
              <Activity className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="min-w-0">
              <div className="font-medium text-foreground">Логика обработки</div>
              <div className="text-[11px] text-muted-foreground">Что делает источник и что запросить</div>
            </div>
            <span className="ml-auto flex items-center gap-1.5 text-[11px] text-muted-foreground shrink-0">
              <span className={`h-2 w-2 rounded-full ${st.dot}`} />{st.label}
            </span>
          </div>
          <div className="p-3 space-y-3">
            {item.description && (
              <p className="text-[13px] text-foreground/80 leading-relaxed">{item.description}</p>
            )}
            {item.setup_guide && (
              <div className="rounded-lg border border-border/50 bg-di-surface-low p-3">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80 mb-1.5">Что запросить и как подключить</div>
                <p className="whitespace-pre-line text-[13px] text-foreground/75 leading-relaxed">{item.setup_guide}</p>
              </div>
            )}
            {item.available_doc_types.length > 0 && (
              <div className="rounded-lg border border-border/50 bg-di-surface-low p-3">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80 mb-2">Данные</div>
                <div className="space-y-1.5">
                  {item.available_doc_types.map((d) => (
                    <div key={d.id} className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary/60 shrink-0" />
                      <span className="text-[13px] text-foreground">{d.name}</span>
                      {d.category && <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground/70">{d.category}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Карточка: доступы (реквизиты — заполняет менеджер компании) */}
      <div className="rounded-xl border border-border/60 bg-card/40 overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/40">
          <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-primary/10 shrink-0">
            <Plug className="h-3.5 w-3.5 text-primary" />
          </div>
          <div className="min-w-0">
            <div className="font-medium text-foreground">Доступы и реквизиты</div>
            <div className="text-[11px] text-muted-foreground">Заполняет менеджер по описанию · секреты шифруются</div>
          </div>
        </div>
        <div className="p-3 space-y-2.5">
          {item.setup_schema.length === 0 && (
            <p className="text-muted-foreground">Реквизиты не требуются.</p>
          )}
          {ungrouped.length > 0 && <div className={grid}>{ungrouped.map(renderField)}</div>}
          {groupNames.map((g) => (
            <div key={g} className="rounded-lg border border-border/50 bg-di-surface-low p-3 space-y-3">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">{g}</div>
              <div className={grid}>{groups[g].map(renderField)}</div>
            </div>
          ))}
          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" className="h-7 gap-1.5" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Сохранить
            </Button>
            <Button size="sm" variant="outline" className="h-7 gap-1.5" onClick={handleTest} disabled={testing}>
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
              Проверить
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Карточка источника */
function SourceCard({ source, onUpdate, onDelete, autoOpen = false }: {
  source: Source; onUpdate: (s: Source) => void; onDelete: () => void; autoOpen?: boolean
}) {
  const [open, setOpen] = useState(autoOpen)
  const ref = useRef<HTMLDivElement>(null)
  const meta = sourceMeta(source)
  const IconComp = ICON_MAP[meta.icon] ?? Globe
  const StatusIcon = STATUS_ICON[source.status] ?? Circle
  const formKind = sourceFormKind(source)

  // Переход из каталога (?focus=id) — раскрыть и подскроллить к карточке
  useEffect(() => {
    if (autoOpen && ref.current) {
      ref.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [autoOpen])

  return (
    <>
      <div ref={ref} onClick={() => setOpen(true)}
        className={`group/head rounded-2xl border bg-card cursor-pointer p-4 transition-colors border-border/60 hover:border-border${autoOpen ? ' ring-1 ring-primary/50' : ''}`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-di-surface-low shrink-0">
            <IconComp className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex items-center gap-1">
            <span className={`flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide ${STATUS_COLORS[source.status]}`}>
              <StatusIcon className="h-3.5 w-3.5" />
              {STATUS_LABELS[source.status]}
            </span>
            <Button variant="ghost" size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-destructive opacity-0 group-hover/head:opacity-100 transition-opacity"
              onClick={(e) => { e.stopPropagation(); onDelete() }}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70 truncate">{meta.label}</div>
          <div className="mt-0.5 text-base font-bold tracking-tight truncate">{source.name}</div>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-di-surface-low shrink-0">
                <IconComp className="h-4 w-4 text-muted-foreground" />
              </span>
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">{meta.label}</span>
                <span className="block text-base font-bold tracking-tight truncate">{source.name}</span>
              </span>
            </DialogTitle>
          </DialogHeader>
          {formKind === 'sts' ? (
            <RestConnectionForm source={source} onUpdate={onUpdate} />
          ) : formKind === 'msto' ? (
            <MstoConnectionForm source={source} onUpdate={onUpdate} />
          ) : formKind === 'tradecorp' ? (
            <TradecorpConnectionForm source={source} onUpdate={onUpdate} />
          ) : (
            <SchemaConnectionForm source={source} onUpdate={onUpdate} />
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>(getSources)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<string>('')
  const [focusId, setFocusId] = useState<string | null>(null)
  const { companyId } = useCompany()
  // Реквизиты доступа правит администратор организации — так же гейтит сервер.
  const { canManage } = useCanManage()
  const [searchParams, setSearchParams] = useSearchParams()

  function refresh() { setSources(getSources()) }

  // API-режим: гидрация кэша источников из бэкенда при монтировании
  useEffect(() => {
    void loadSources(companyId).then(refresh).catch(() => { /* офлайн → localStorage */ })
  }, [companyId])

  // Переход из каталога: ?add=1&type=&name= → открыть диалог; ?focus=id → раскрыть карточку
  useEffect(() => {
    const add = searchParams.get('add')
    const type = searchParams.get('type')
    const name = searchParams.get('name')
    const focus = searchParams.get('focus')
    if (add) {
      setDialogOpen(true)
      if (type) setNewType(type)
      if (name) setNewName(name)
    }
    if (focus) setFocusId(focus)
    if (add || focus) {
      for (const k of ['add', 'type', 'name', 'focus']) searchParams.delete(k)
      setSearchParams(searchParams, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleCreate() {
    if (!newName.trim()) return
    await createSource({ name: newName, type: frontendSourceType(newType), sourceType: newType })
    refresh()
    setDialogOpen(false)
    setNewName('')
    toast.success('Источник создан')
  }

  async function handleDelete(id: string) {
    if (!confirm('Удалить источник?')) return
    await deleteSource(id)
    refresh()
    toast.success('Источник удалён')
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Источники</h1>
          <p className="text-sm text-muted-foreground">
            Реквизиты доступа к внешним системам: адрес, учётка, ключи. Данные носит
            коннектор, собранный поверх источника, — источник сам по себе ничего не грузит.
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          {canManage && (
            <DialogTrigger asChild>
              <Button size="sm" className="gap-1.5">
                <Plus className="h-4 w-4" />
                Добавить источник
              </Button>
            </DialogTrigger>
          )}
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Новый источник</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Название</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Бухгалтерия компании" />
              </div>
              <div className="space-y-2">
                <Label>Тип подключения</Label>
                <Select value={newType} onValueChange={setNewType}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(BACKEND_SOURCE_META).map(([key, meta]) => (
                      <SelectItem key={key} value={key}>
                        {meta.label} — {meta.category}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={handleCreate} disabled={!newName.trim()}>Создать</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {sources.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Server className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm font-medium">Источников пока нет</p>
            <p className="max-w-md text-center text-xs text-muted-foreground">
              Источник — это реквизиты доступа к внешней системе: адрес, учётка, ключи.
              Сам он ничего не грузит: данные носит коннектор, собранный поверх него.
              Тип выбирается в «Каталоге типов».
            </p>
            {canManage && (
              <Button variant="outline" size="sm" onClick={() => setDialogOpen(true)}>
                Добавить первый источник
              </Button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
          {sources.map((src) => (
            <SourceCard
              key={src.id}
              source={src}
              autoOpen={src.id === focusId}
              onUpdate={(updated) => setSources((prev) => prev.map((s) => s.id === updated.id ? updated : s))}
              onDelete={() => handleDelete(src.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default SourcesPage
