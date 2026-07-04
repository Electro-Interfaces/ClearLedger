/**
 * Мастер «Создать коннектор» — на BACKEND-шаблонах каналов (`/api/channel-templates`).
 * Заменяет legacy `ChannelWizard` (тот на несуществующих frontend-id → 404).
 *
 * Шаг 1: выбрать тип коннектора (шаблон канала).
 * Шаг 2: на каждый вход (source_type шаблона) — привязать существующее подключение
 *        или создать новое (настройка связи/теста — в карточке коннектора, Фаза 3).
 * Создание = createChannel(template_id, sourceIds) → backend резолвит потоки/стадии/разрезы.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ChevronLeft, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { getChannelTemplates, type ChannelTemplateItem } from '@/services/catalogService'
import { getSources, createSource, frontendSourceType } from '@/services/sourceService'
import { createChannel } from '@/services/channelService'
import { BACKEND_SOURCE_META } from '@/types/channel'

const srcMeta = (t: string) => BACKEND_SOURCE_META[t] ?? { label: t, category: '', icon: 'Plug' }
const NEW = '__new__'

export function ConnectorWizard({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [templates, setTemplates] = useState<ChannelTemplateItem[]>([])
  const [tpl, setTpl] = useState<ChannelTemplateItem | null>(null)
  const [name, setName] = useState('')
  const [bind, setBind] = useState<Record<string, string>>({})  // source_type → sourceId | '__new__'
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) getChannelTemplates().then(setTemplates).catch(() => { /* офлайн */ })
  }, [open])

  function reset() { setStep(1); setTpl(null); setName(''); setBind({}) }

  // Уникальные входы шаблона (по source_type — одно подключение на тип).
  const inputs = useMemo(() => {
    if (!tpl) return [] as ChannelTemplateItem['streams']
    const seen = new Set<string>()
    return tpl.streams.filter((s) => (seen.has(s.source_type) ? false : (seen.add(s.source_type), true)))
  }, [tpl])

  function pick(t: ChannelTemplateItem) {
    setTpl(t)
    setName(t.label)
    const b: Record<string, string> = {}
    for (const s of t.streams) {
      const existing = getSources().filter((x) => x.backendType === s.source_type)
      b[s.source_type] = existing.length === 1 ? existing[0].id : NEW  // авто-привязка единственного
    }
    setBind(b)
    setStep(2)
  }

  async function create() {
    if (!tpl) return
    setBusy(true)
    try {
      const sourceIds: string[] = []
      for (const s of inputs) {
        const sel = bind[s.source_type]
        if (sel && sel !== NEW) { sourceIds.push(sel); continue }
        const src = await createSource({
          name: srcMeta(s.source_type).label,
          type: frontendSourceType(s.source_type),
          sourceType: s.source_type,
        })
        sourceIds.push(src.id)
      }
      const ch = await createChannel({ name: name.trim() || tpl.label, sourceIds, templateId: tpl.id })
      toast.success(`Коннектор «${ch.name}» создан`)
      onOpenChange(false)
      reset()
      navigate(`/connectors/${ch.id}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания коннектора')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v) }}>
      <DialogContent className="flex max-h-[85vh] max-w-[640px] flex-col">
        <DialogHeader><DialogTitle>Новый коннектор</DialogTitle></DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-2">
          {step === 1 && (
            <>
              <p className="text-sm text-muted-foreground">Выберите тип коннектора. Входы (подключения) настроите на следующем шаге.</p>
              <div className="grid gap-2">
                {templates.filter((t) => t.status !== 'planned').map((t) => (
                  <button key={t.id} type="button" onClick={() => pick(t)}
                    className="rounded-lg border p-3 text-left transition-colors hover:bg-accent/40">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{t.label}</span>
                      <span className="ml-auto text-[10px] text-muted-foreground/70">{t.category}</span>
                    </div>
                    <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{t.description}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground/80">
                      входы: {[...new Set(t.streams.map((s) => srcMeta(s.source_type).label))].join(' · ')}
                    </div>
                  </button>
                ))}
                {templates.length === 0 && <div className="py-6 text-center text-sm text-muted-foreground">Каталог шаблонов пуст.</div>}
              </div>
            </>
          )}

          {step === 2 && tpl && (
            <>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">Название коннектора</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-sm" />
              </label>
              <div className="pt-1 text-xs font-medium text-muted-foreground">Входы (подключения)</div>
              {inputs.map((s) => {
                const existing = getSources().filter((x) => x.backendType === s.source_type)
                return (
                  <div key={s.source_type} className="space-y-1.5 rounded-md border p-2.5">
                    <div className="text-sm font-medium">{srcMeta(s.source_type).label}</div>
                    <div className="text-[11px] text-muted-foreground">{s.label} · роль {s.role}</div>
                    <Select value={bind[s.source_type] ?? NEW} onValueChange={(v) => setBind((b) => ({ ...b, [s.source_type]: v }))}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {existing.map((x) => <SelectItem key={x.id} value={x.id} className="text-xs">{x.name}</SelectItem>)}
                        <SelectItem value={NEW} className="text-xs">➕ Создать новое подключение</SelectItem>
                      </SelectContent>
                    </Select>
                    {(bind[s.source_type] ?? NEW) === NEW && (
                      <p className="text-[11px] text-muted-foreground/80">Новое подключение создастся; настройка связи и проверка — в карточке коннектора.</p>
                    )}
                  </div>
                )
              })}
            </>
          )}
        </div>

        <DialogFooter className="flex justify-between">
          <div>{step > 1 && <Button variant="ghost" onClick={() => setStep(1)}><ChevronLeft className="mr-1 h-4 w-4" />Назад</Button>}</div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => { reset(); onOpenChange(false) }}>Отмена</Button>
            {step === 2 && (
              <Button onClick={create} disabled={busy || !name.trim()}>
                {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}Создать коннектор
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
