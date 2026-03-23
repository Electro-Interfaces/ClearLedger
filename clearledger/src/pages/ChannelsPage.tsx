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
import { getChannels, createChannel, updateChannel, deleteChannel } from '@/services/channelService'
import { CHANNEL_TYPE_META, type ChannelType, type Channel } from '@/types/channel'
import { stsTestConnection } from '@/services/fuel/stsApiClient'
import {
  Plus, Trash2, Globe, Database, Mail, HardDrive,
  Webhook, FolderOpen, FileCheck, Cloud, Radio,
  ChevronDown, Settings, Loader2, CheckCircle2, XCircle, Save,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Globe, Database, Mail, HardDrive, Webhook, FolderOpen, FileCheck, Cloud,
}

const STATUS_MAP: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  active: { label: 'Активен', variant: 'default' },
  paused: { label: 'Пауза', variant: 'secondary' },
  error: { label: 'Ошибка', variant: 'destructive' },
  draft: { label: 'Черновик', variant: 'outline' },
}

/** Форма настройки REST API канала (STS) */
function RestApiConfig({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const [url, setUrl] = useState(channel.config.url ?? channel.endpoint ?? '')
  const [login, setLogin] = useState(channel.config.login ?? '')
  const [password, setPassword] = useState(channel.config.password ?? '')
  const [systemCode, setSystemCode] = useState(channel.config.systemCode ?? '65')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; shiftsCount?: number } | null>(null)

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    const testUrl = import.meta.env.DEV ? '/tms' : url
    const result = await stsTestConnection(testUrl, login, password)
    setTestResult(result)
    setTesting(false)
    if (result.ok) toast.success(`Подключение OK — ${result.shiftsCount} смен`)
    else toast.error(`Ошибка: ${result.error}`)
  }

  function handleSave() {
    const updated = updateChannel(channel.id, {
      endpoint: url,
      config: { ...channel.config, url, login, password, systemCode },
      status: testResult?.ok ? 'active' : channel.status,
    })
    if (updated) {
      onUpdate(updated)
      toast.success('Канал сохранён')
    }
  }

  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-2">
        <Label className="text-xs">URL API</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://pos.autooplata.ru/tms" className="h-8 text-sm" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label className="text-xs">Логин</Label>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="UserApi" className="h-8 text-sm" />
        </div>
        <div className="space-y-2">
          <Label className="text-xs">Пароль</Label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-8 text-sm" />
        </div>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Код системы (сети)</Label>
        <Input value={systemCode} onChange={(e) => setSystemCode(e.target.value)} className="h-8 text-sm w-24" />
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleTest} disabled={testing || !login}>
          {testing && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
          Проверить
        </Button>
        <Button size="sm" className="h-8 text-xs gap-1" onClick={handleSave}>
          <Save className="h-3 w-3" />
          Сохранить
        </Button>
        {testResult && (
          <span className="flex items-center gap-1 text-xs">
            {testResult.ok
              ? <><CheckCircle2 className="h-4 w-4 text-emerald-500" /><span className="text-emerald-500">OK ({testResult.shiftsCount} смен)</span></>
              : <><XCircle className="h-4 w-4 text-destructive" /><span className="text-destructive">{testResult.error}</span></>
            }
          </span>
        )}
      </div>
    </div>
  )
}

/** Заглушка настройки для других типов каналов */
function GenericConfig({ channel }: { channel: Channel }) {
  return (
    <div className="py-3">
      <p className="text-xs text-muted-foreground">
        Настройка канала типа «{CHANNEL_TYPE_META[channel.type].label}» — в следующей версии.
      </p>
      {channel.endpoint && (
        <div className="mt-2 space-y-2">
          <Label className="text-xs">Endpoint</Label>
          <Input value={channel.endpoint} readOnly className="h-8 text-sm bg-muted/50" />
        </div>
      )}
    </div>
  )
}

/** Карточка канала (раскрываемая) */
function ChannelCard({ channel, onUpdate, onDelete }: {
  channel: Channel; onUpdate: (ch: Channel) => void; onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const meta = CHANNEL_TYPE_META[channel.type]
  const IconComp = ICON_MAP[meta.icon] ?? Globe
  const statusMeta = STATUS_MAP[channel.status] ?? STATUS_MAP.draft

  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <CardHeader className="pb-2 cursor-pointer hover:bg-accent/30 transition-colors rounded-t-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10">
                  <IconComp className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-sm flex items-center gap-2">
                    {channel.name}
                    <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`} />
                  </CardTitle>
                  <CardDescription className="text-xs">{meta.label}</CardDescription>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={statusMeta.variant} className="text-[10px]">{statusMeta.label}</Badge>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  onClick={(e) => { e.stopPropagation(); onDelete() }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        {!open && (
          <CardContent className="pt-0 pb-2">
            <div className="flex gap-4 text-xs text-muted-foreground">
              {channel.endpoint && <span className="truncate max-w-[300px]">{channel.endpoint}</span>}
              <span>Загружено: {channel.docsLoaded}</span>
              <span>Создан: {format(new Date(channel.createdAt), 'dd.MM.yyyy')}</span>
            </div>
          </CardContent>
        )}

        <CollapsibleContent>
          <CardContent className="pt-0 border-t border-border/30 mt-1">
            <div className="flex items-center gap-1.5 py-2">
              <Settings className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground">Параметры подключения</span>
            </div>
            {channel.type === 'rest' ? (
              <RestApiConfig channel={channel} onUpdate={onUpdate} />
            ) : (
              <GenericConfig channel={channel} />
            )}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

export function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>(getChannels)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<ChannelType>('rest')
  const [newEndpoint, setNewEndpoint] = useState('')

  function refresh() { setChannels(getChannels()) }

  function handleCreate() {
    if (!newName.trim()) return
    createChannel({ name: newName, type: newType, endpoint: newEndpoint })
    refresh()
    setDialogOpen(false)
    setNewName('')
    setNewEndpoint('')
    toast.success('Канал создан')
  }

  function handleDelete(id: string) {
    if (!confirm('Удалить канал?')) return
    deleteChannel(id)
    refresh()
    toast.success('Канал удалён')
  }

  function handleUpdate(updated: Channel) {
    setChannels((prev) => prev.map((c) => c.id === updated.id ? updated : c))
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Каналы данных</h1>
          <p className="text-sm text-muted-foreground">Подключения для загрузки документов. Настройте параметры каждого канала.</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-4 w-4" />
              Добавить канал
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Новый канал</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Название</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="STS API ГИГ" />
              </div>
              <div className="space-y-2">
                <Label>Тип канала</Label>
                <Select value={newType} onValueChange={(v) => setNewType(v as ChannelType)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(CHANNEL_TYPE_META).map(([key, meta]) => (
                      <SelectItem key={key} value={key}>
                        {meta.label} — {meta.description}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Endpoint (URL / путь)</Label>
                <Input value={newEndpoint} onChange={(e) => setNewEndpoint(e.target.value)}
                  placeholder="https://pos.autooplata.ru/tms" />
              </div>
            </div>
            <DialogFooter>
              <Button onClick={handleCreate} disabled={!newName.trim()}>Создать</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {channels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Radio className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Нет настроенных каналов</p>
            <Button variant="outline" size="sm" onClick={() => setDialogOpen(true)}>
              Добавить первый канал
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {channels.map((ch) => (
            <ChannelCard
              key={ch.id}
              channel={ch}
              onUpdate={handleUpdate}
              onDelete={() => handleDelete(ch.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default ChannelsPage
