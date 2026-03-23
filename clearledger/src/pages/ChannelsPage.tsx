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
import { getChannels, createChannel, deleteChannel } from '@/services/channelService'
import { CHANNEL_TYPE_META, type ChannelType, type Channel } from '@/types/channel'
import {
  Plus, Trash2, Globe, Database, Mail, HardDrive,
  Webhook, FolderOpen, FileCheck, Cloud, Radio,
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

export function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>(getChannels)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<ChannelType>('rest')
  const [newEndpoint, setNewEndpoint] = useState('')

  function handleCreate() {
    if (!newName.trim()) return
    createChannel({ name: newName, type: newType, endpoint: newEndpoint })
    setChannels(getChannels())
    setDialogOpen(false)
    setNewName('')
    setNewEndpoint('')
    toast.success('Канал создан')
  }

  function handleDelete(id: string) {
    if (!confirm('Удалить канал?')) return
    deleteChannel(id)
    setChannels(getChannels())
    toast.success('Канал удалён')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Каналы данных</h1>
          <p className="text-sm text-muted-foreground">Автоматические подключения для загрузки документов</p>
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
          {channels.map((ch) => {
            const meta = CHANNEL_TYPE_META[ch.type]
            const IconComp = ICON_MAP[meta.icon] ?? Globe
            const statusMeta = STATUS_MAP[ch.status] ?? STATUS_MAP.draft

            return (
              <Card key={ch.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10">
                        <IconComp className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <CardTitle className="text-sm">{ch.name}</CardTitle>
                        <CardDescription className="text-xs">{meta.label}</CardDescription>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={statusMeta.variant} className="text-[10px]">
                        {statusMeta.label}
                      </Badge>
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => handleDelete(ch.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="flex gap-4 text-xs text-muted-foreground">
                    {ch.endpoint && <span className="truncate max-w-[300px]">{ch.endpoint}</span>}
                    <span>Загружено: {ch.docsLoaded}</span>
                    {ch.lastSync && <span>Последняя: {format(new Date(ch.lastSync), 'dd.MM.yyyy HH:mm')}</span>}
                    <span>Создан: {format(new Date(ch.createdAt), 'dd.MM.yyyy')}</span>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default ChannelsPage
