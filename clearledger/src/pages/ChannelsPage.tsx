/**
 * Каналы данных — работа с данными из источников.
 * Расписание, периоды, потоки, каталоги хранения, синхронизация.
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
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Progress } from '@/components/ui/progress'
import { getChannels, createChannel, updateChannel, deleteChannel } from '@/services/channelService'
import { getSources } from '@/services/sourceService'
import { syncRestChannel } from '@/services/channelSyncService'
import type { Channel, ChannelStream, SyncResult } from '@/types/channel'
import { DUPLICATE_POLICY_META, type DuplicatePolicy } from '@/types/channel'
import {
  Plus, Trash2, Radio, ChevronDown, Loader2, Play, History, Save,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

const STATUS_MAP: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  active: { label: 'Активен', variant: 'default' },
  paused: { label: 'Пауза', variant: 'secondary' },
  error: { label: 'Ошибка', variant: 'destructive' },
  draft: { label: 'Черновик', variant: 'outline' },
}

/** Настройка одного потока (подкаталог) */
function StreamConfig({ stream, rootCatalog, onChange }: {
  stream: ChannelStream; rootCatalog: string; onChange: (s: ChannelStream) => void
}) {
  const [open, setOpen] = useState(false)
  const [subdir, setSubdir] = useState(stream.catalogTemplate)
  const [streamName, setStreamName] = useState(stream.name)

  const fullPath = `${rootCatalog}${subdir}`.replace(/\/\//g, '/')
  const previewPath = fullPath
    .replace(/\{станция\}/g, 'АЗС-208')
    .replace(/\{год\}/g, '2026')
    .replace(/\{месяц\}/g, '03')

  return (
    <div className="rounded-md border border-border/40 bg-muted/20">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-accent/30 transition-colors rounded-md">
            <Checkbox checked={stream.enabled} className="h-3.5 w-3.5"
              onClick={(e) => { e.stopPropagation(); onChange({ ...stream, enabled: !stream.enabled }) }} />
            <span className={`font-medium ${stream.enabled ? '' : 'text-muted-foreground line-through'}`}>{stream.name}</span>
            <span className="text-muted-foreground/50 ml-auto mr-2 truncate max-w-[250px] font-mono text-[10px]">{previewPath}</span>
            <ChevronDown className={`h-3 w-3 text-muted-foreground shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-border/30">
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">Название потока</Label>
                <Input value={streamName} onChange={(e) => setStreamName(e.target.value)} className="h-7 text-xs" />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">Тип документа</Label>
                <div className="h-7 flex items-center px-2 rounded border border-border/30 bg-muted/30 text-xs font-mono text-muted-foreground">
                  {stream.docTypeId}
                </div>
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] text-muted-foreground">
                Подкаталог <span className="text-muted-foreground/40">(переменные: {'{станция}'}, {'{год}'}, {'{месяц}'})</span>
              </Label>
              <Input value={subdir} onChange={(e) => setSubdir(e.target.value)} className="h-7 text-xs font-mono" />
            </div>
            <div className="text-[10px] text-muted-foreground/60 font-mono bg-muted/30 px-2 py-1 rounded">
              Полный путь: {previewPath}
            </div>
            <Button size="sm" variant="outline" className="h-7 text-[10px]"
              onClick={() => {
                onChange({ ...stream, catalogTemplate: subdir, name: streamName })
                toast.success(`Поток «${streamName}» обновлён`)
              }}>
              Применить
            </Button>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

/** Карточка канала */
function ChannelCard({ channel, onUpdate, onDelete }: {
  channel: Channel; onUpdate: (ch: Channel) => void; onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState('')
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [periodDays, setPeriodDays] = useState(String(channel.periodDays ?? 7))
  const [dupPolicy, setDupPolicy] = useState<DuplicatePolicy>(channel.duplicatePolicy ?? 'skip')
  const [rootCatalog, setRootCatalog] = useState((channel as any).rootCatalog ?? '/Нефтепродукты АЗС')

  const sources = getSources()
  const source = sources.find((s) => s.id === channel.sourceId)
  const statusMeta = STATUS_MAP[channel.status] ?? STATUS_MAP.draft
  const log = channel.syncLog || []

  async function handleSync() {
    setSyncing(true)
    setSyncResult(null)
    setSyncProgress('Запуск...')

    // Сохранить настройки
    updateChannel(channel.id, { periodDays: Number(periodDays), duplicatePolicy: dupPolicy })

    try {
      // Собрать connection из источника
      const mergedChannel = {
        ...channel,
        duplicatePolicy: dupPolicy,
        // Передаём connection источника как config для совместимости с syncService
      }
      // syncRestChannel использует source.connection через канал
      const result = await syncRestChannel(
        { ...mergedChannel, config: source?.connection ?? {} } as Channel & { config: Record<string, string> },
        { onProgress: (_l, _t, msg) => setSyncProgress(msg) },
      )
      setSyncResult(result)
      onUpdate(getChannels().find((c) => c.id === channel.id) ?? channel)

      if (result.errors > 0) toast.error(`${result.loaded} загружено, ${result.errors} ошибок`)
      else toast.success(`${result.loaded} загружено, ${result.duplicates} пропущено`)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setSyncing(false)
      setSyncProgress('')
    }
  }

  function handleSave() {
    updateChannel(channel.id, {
      periodDays: Number(periodDays),
      duplicatePolicy: dupPolicy,
      ...({ rootCatalog } as any),
    })
    toast.success('Канал сохранён')
  }

  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <CardHeader className="pb-2 cursor-pointer hover:bg-accent/30 transition-colors rounded-t-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10">
                  <Radio className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-sm flex items-center gap-2">
                    {channel.name}
                    <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`} />
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Источник: {source?.name ?? 'не найден'}
                  </CardDescription>
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
              <span>Загружено: {channel.docsLoaded}</span>
              {channel.lastSync && <span>Последняя: {format(new Date(channel.lastSync), 'dd.MM.yyyy HH:mm')}</span>}
              <span>Период: {channel.periodDays} дн.</span>
            </div>
          </CardContent>
        )}

        <CollapsibleContent>
          <CardContent className="pt-0 border-t border-border/30 mt-1 space-y-4">
            {/* Параметры работы */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Период загрузки (дней)</Label>
                <Input value={periodDays} onChange={(e) => setPeriodDays(e.target.value)}
                  type="number" className="h-8 text-sm w-24" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Дубликаты</Label>
                <Select value={dupPolicy} onValueChange={(v) => setDupPolicy(v as DuplicatePolicy)}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(DUPLICATE_POLICY_META).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v.label} — {v.description}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Каталог хранения */}
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Корневой каталог</Label>
                <Input value={rootCatalog} onChange={(e) => setRootCatalog(e.target.value)}
                  className="h-8 text-sm font-mono" placeholder="/Нефтепродукты АЗС" />
                <p className="text-[10px] text-muted-foreground">Все документы канала будут размещены внутри этого каталога</p>
              </div>

              {/* Потоки — подкаталоги */}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Подкаталоги по типам документов</Label>
                {(channel.streams ?? []).map((s, idx) => (
                  <StreamConfig key={s.id} stream={s} rootCatalog={rootCatalog} onChange={(updated) => {
                    const streams = [...(channel.streams ?? [])]
                    streams[idx] = updated
                    updateChannel(channel.id, { streams })
                    onUpdate({ ...channel, streams })
                  }} />
                ))}
              </div>

              {/* Preview дерева каталогов */}
              <div className="rounded-md border border-border/30 bg-muted/20 p-3">
                <p className="text-[10px] font-semibold text-muted-foreground mb-1.5">Структура хранения:</p>
                <pre className="text-[10px] font-mono text-muted-foreground leading-relaxed">
{rootCatalog}/
{(channel.streams ?? []).filter(s => s.enabled).map(s => {
  const sub = s.catalogTemplate.replace(/^\//, '')
  return `├── ${sub.replace(/\{станция\}/g, 'АЗС-208').replace(/\{год\}/g, '2026').replace(/\{месяц\}/g, '03')}`
}).join('\n')}
                </pre>
              </div>
            </div>

            {/* Кнопки */}
            <div className="flex items-center gap-2 flex-wrap">
              <Button size="sm" className="h-8 text-xs gap-1" onClick={handleSync}
                disabled={syncing || !source}>
                {syncing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                Обновить данные
              </Button>
              <Button size="sm" variant="outline" className="h-8 text-xs gap-1" onClick={handleSave}>
                <Save className="h-3 w-3" />
                Сохранить
              </Button>
              {log.length > 0 && (
                <Button size="sm" variant="ghost" className="h-8 text-xs gap-1 ml-auto" onClick={() => setShowLog(!showLog)}>
                  <History className="h-3 w-3" />
                  Лог ({log.length})
                </Button>
              )}
            </div>

            {/* Прогресс */}
            {syncing && (
              <div className="space-y-1">
                <Progress className="h-1.5" />
                <p className="text-[10px] text-muted-foreground">{syncProgress}</p>
              </div>
            )}

            {/* Результат */}
            {syncResult && !syncing && (
              <div className="rounded-md bg-muted/50 p-3 text-xs flex gap-4">
                <span className="text-emerald-500 font-medium">Загружено: {syncResult.loaded}</span>
                <span className="text-muted-foreground">Дубликатов: {syncResult.duplicates}</span>
                {syncResult.errors > 0 && <span className="text-destructive">Ошибок: {syncResult.errors}</span>}
              </div>
            )}

            {/* Лог */}
            {showLog && log.length > 0 && (
              <div className="rounded-md border border-border/50 bg-muted/30">
                <ScrollArea className="max-h-[200px]">
                  <div className="p-2 space-y-0.5 font-mono text-[10px]">
                    {log.map((entry, i) => (
                      <div key={i} className={`flex gap-2 ${
                        entry.level === 'error' ? 'text-destructive' :
                        entry.level === 'success' ? 'text-emerald-500' :
                        'text-muted-foreground'
                      }`}>
                        <span className="shrink-0 w-14">{format(new Date(entry.timestamp), 'HH:mm:ss')}</span>
                        <span className="shrink-0 w-10 font-semibold">{entry.event}</span>
                        <span>{entry.message}</span>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
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
  const [newSourceId, setNewSourceId] = useState('')

  const sources = getSources()

  function refresh() { setChannels(getChannels()) }

  function handleCreate() {
    if (!newName.trim() || !newSourceId) return
    createChannel({ name: newName, sourceId: newSourceId })
    refresh()
    setDialogOpen(false)
    setNewName('')
    setNewSourceId('')
    toast.success('Канал создан')
  }

  function handleDelete(id: string) {
    if (!confirm('Удалить канал?')) return
    deleteChannel(id)
    refresh()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Каналы данных</h1>
          <p className="text-sm text-muted-foreground">
            Загрузка данных из источников. Расписание, периоды, каталоги хранения.
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5" disabled={sources.length === 0}>
              <Plus className="h-4 w-4" />
              Создать канал
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Новый канал</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Название</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Смены ГИГ" />
              </div>
              <div className="space-y-2">
                <Label>Источник</Label>
                <Select value={newSourceId} onValueChange={setNewSourceId}>
                  <SelectTrigger><SelectValue placeholder="Выберите источник" /></SelectTrigger>
                  <SelectContent>
                    {sources.map((s) => (
                      <SelectItem key={s.id} value={s.id}>{s.name} ({s.type})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {sources.length === 0 && (
                  <p className="text-xs text-muted-foreground">Сначала добавьте источник</p>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button onClick={handleCreate} disabled={!newName.trim() || !newSourceId}>Создать</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {channels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Radio className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Нет каналов</p>
            <p className="text-xs text-muted-foreground">
              {sources.length === 0
                ? 'Сначала добавьте источник в разделе «Источники»'
                : 'Создайте канал для загрузки данных из источника'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {channels.map((ch) => (
            <ChannelCard key={ch.id} channel={ch}
              onUpdate={(u) => setChannels((prev) => prev.map((c) => c.id === u.id ? u : c))}
              onDelete={() => handleDelete(ch.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

export default ChannelsPage
