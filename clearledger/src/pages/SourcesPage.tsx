/**
 * Источники данных — подключения к внешним системам.
 * Настройка URL, credentials, типов документов.
 */

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { getSources, createSource, updateSource, deleteSource } from '@/services/sourceService'
import { SOURCE_TYPE_META, type SourceType, type Source } from '@/types/channel'
import { stsTestConnection } from '@/services/fuel/stsApiClient'
import {
  Plus, Trash2, Globe, Database, Mail, HardDrive,
  Webhook, FolderOpen, FileCheck, Cloud, Server,
  ChevronDown, Loader2, CheckCircle2, XCircle, Save, Plug,
} from 'lucide-react'
import { toast } from 'sonner'

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Globe, Database, Mail, HardDrive, Webhook, FolderOpen, FileCheck, Cloud,
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

/** Форма настройки подключения REST API */
function RestConnectionForm({ source, onUpdate }: { source: Source; onUpdate: (s: Source) => void }) {
  const [url, setUrl] = useState(source.connection.url ?? '')
  const [login, setLogin] = useState(source.connection.login ?? '')
  const [password, setPassword] = useState(source.connection.password ?? '')
  const [systemCode, setSystemCode] = useState(source.connection.systemCode ?? '65')
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

  function handleSave() {
    const updated = updateSource(source.id, {
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

/** Заглушка для других типов */
function GenericConnectionForm({ source }: { source: Source }) {
  return (
    <div className="py-3 text-xs text-muted-foreground">
      Настройка подключения типа «{SOURCE_TYPE_META[source.type].label}» — в следующей версии.
    </div>
  )
}

/** Карточка источника */
function SourceCard({ source, onUpdate, onDelete }: {
  source: Source; onUpdate: (s: Source) => void; onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const meta = SOURCE_TYPE_META[source.type]
  const IconComp = ICON_MAP[meta.icon] ?? Globe

  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <CardHeader className="pb-2 cursor-pointer hover:bg-accent/30 transition-colors rounded-t-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`flex items-center justify-center w-9 h-9 rounded-lg ${
                  source.status === 'connected' ? 'bg-emerald-500/10' : 'bg-primary/10'
                }`}>
                  <IconComp className={`h-4 w-4 ${source.status === 'connected' ? 'text-emerald-500' : 'text-primary'}`} />
                </div>
                <div>
                  <CardTitle className="text-sm flex items-center gap-2">
                    {source.name}
                    <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`} />
                  </CardTitle>
                  <CardDescription className="text-xs">{meta.label}</CardDescription>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] font-medium ${STATUS_COLORS[source.status]}`}>
                  ● {STATUS_LABELS[source.status]}
                </span>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  onClick={(e) => { e.stopPropagation(); onDelete() }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        {!open && source.connection.url && (
          <CardContent className="pt-0 pb-2">
            <p className="text-xs text-muted-foreground truncate">{source.connection.url}</p>
          </CardContent>
        )}

        <CollapsibleContent>
          <CardContent className="pt-0 border-t border-border/30 mt-1">
            {source.type === 'rest' ? (
              <RestConnectionForm source={source} onUpdate={onUpdate} />
            ) : (
              <GenericConnectionForm source={source} />
            )}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>(getSources)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<SourceType>('rest')

  function refresh() { setSources(getSources()) }

  function handleCreate() {
    if (!newName.trim()) return
    createSource({ name: newName, type: newType })
    refresh()
    setDialogOpen(false)
    setNewName('')
    toast.success('Источник создан')
  }

  function handleDelete(id: string) {
    if (!confirm('Удалить источник?')) return
    deleteSource(id)
    refresh()
    toast.success('Источник удалён')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Источники данных</h1>
          <p className="text-sm text-muted-foreground">
            Подключения к внешним системам. Настройте источник, затем создайте канал для загрузки.
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-4 w-4" />
              Добавить источник
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Новый источник</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Название</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="STS API ГИГ" />
              </div>
              <div className="space-y-2">
                <Label>Тип подключения</Label>
                <Select value={newType} onValueChange={(v) => setNewType(v as SourceType)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(SOURCE_TYPE_META).map(([key, meta]) => (
                      <SelectItem key={key} value={key}>
                        {meta.label} — {meta.description}
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
            <p className="text-sm text-muted-foreground">Нет настроенных источников</p>
            <p className="text-xs text-muted-foreground">Добавьте источник чтобы начать загрузку данных</p>
            <Button variant="outline" size="sm" onClick={() => setDialogOpen(true)}>
              Добавить первый источник
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {sources.map((src) => (
            <SourceCard
              key={src.id}
              source={src}
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
