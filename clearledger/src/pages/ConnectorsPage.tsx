import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConnectorGrid } from '@/components/connectors/ConnectorGrid'
import { useConnectors, useCreateConnector } from '@/hooks/useConnectors'
import { useCompany } from '@/contexts/CompanyContext'
import { getProfile } from '@/config/profiles'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export function ConnectorsPage() {
  const { company } = useCompany()
  const { data: connectors = [] } = useConnectors()
  const createConnector = useCreateConnector()
  const [showNew, setShowNew] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'rest', url: '', categoryId: '', interval: '60' })

  const profile = getProfile(company.profileId)
  const templates = profile.connectorTemplates

  function handleCreate() {
    if (!form.name || !form.url) return
    createConnector.mutate({
      name: form.name,
      type: form.type,
      url: form.url,
      categoryId: form.categoryId || 'primary',
      interval: Number(form.interval) || 60,
    })
    setShowNew(false)
    setForm({ name: '', type: 'rest', url: '', categoryId: '', interval: '60' })
  }

  function handleTemplate(templateId: string) {
    const t = templates.find((tpl) => tpl.id === templateId)
    if (t) {
      setForm({
        name: t.name,
        type: t.type,
        url: '',
        categoryId: t.targetCategory,
        interval: String(t.defaultInterval),
      })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">API-коннекторы</h1>
        <Button onClick={() => setShowNew(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Новый коннектор
        </Button>
      </div>

      <ConnectorGrid connectors={connectors} />

      <Dialog open={showNew} onOpenChange={setShowNew}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый коннектор</DialogTitle>
          </DialogHeader>

          {templates.length > 0 && (
            <div className="space-y-2">
              <Label>Шаблон (необязательно)</Label>
              <Select onValueChange={handleTemplate}>
                <SelectTrigger>
                  <SelectValue placeholder="Выберите шаблон" />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((t) => (
                    <SelectItem key={t.id} value={t.id}>{t.name} — {t.description}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Название</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Название коннектора" />
            </div>
            <div className="space-y-2">
              <Label>Тип</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="rest">REST API</SelectItem>
                  <SelectItem value="1c">1C</SelectItem>
                  <SelectItem value="email">Email (IMAP)</SelectItem>
                  <SelectItem value="ftp">FTP/SFTP</SelectItem>
                  <SelectItem value="webhook">Webhook</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>URL</Label>
              <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://..." />
            </div>
            <div className="space-y-2">
              <Label>Интервал (сек.)</Label>
              <Input type="number" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNew(false)}>Отмена</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.url}>Создать</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
