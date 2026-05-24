/**
 * Страница «1С → Маппинги» — соответствия ключей внешних источников
 * (STS station_id, fuel_type, pay_type, артикулы ТТН) и записей в
 * Catalog БП ГИГ. Используется при сверке для построчного матчинга
 * (см. docs/sverka-spec.md §4 и §2.5).
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@/components/ui/tabs'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  Plus, Pencil, Trash2, Loader2, Link2, Building2, Fuel, CreditCard, Package, Users,
} from 'lucide-react'
import { toast } from 'sonner'

import { useCompany } from '@/contexts/CompanyContext'
import {
  listMappings, createMapping, updateMapping, deleteMapping, mappingStats,
  type MappingKind, type MappingMethod, type ReconcileMapping,
} from '@/services/mappingService'

const KINDS: { value: MappingKind; label: string; icon: typeof Link2; hint: string }[] = [
  { value: 'station',      label: 'АЗС',          icon: Building2,  hint: 'STS station_id → Catalog.Склады' },
  { value: 'fuel',         label: 'Топливо',      icon: Fuel,       hint: 'STS fuel_type → Catalog.Номенклатура' },
  { value: 'paytype',      label: 'Виды оплат',   icon: CreditCard, hint: 'STS pay_type → Catalog.ВидыОплат' },
  { value: 'nomenclature', label: 'Номенклатура', icon: Package,    hint: 'Артикул ТТН-поставщика → Catalog.Номенклатура' },
  { value: 'counterparty', label: 'Контрагенты',  icon: Users,      hint: 'ИНН/наименование внешнего источника → Catalog.Контрагенты' },
]

const METHOD_STYLE: Record<string, string> = {
  manual:           'border-blue-400/50 text-blue-300/80',
  auto:             'border-emerald-400/50 text-emerald-300/80',
  ai:               'border-violet-400/50 text-violet-300/80',
  imported_from_bp: 'border-zinc-600 text-zinc-400',
}

export function MappingsPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [kind, setKind] = useState<MappingKind>('station')
  const [editing, setEditing] = useState<ReconcileMapping | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['mappings', companyId, kind],
    queryFn: () => listMappings(companyId, kind),
  })

  const { data: stats } = useQuery({
    queryKey: ['mappings-stats', companyId],
    queryFn: () => mappingStats(companyId),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteMapping(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['mappings', companyId] })
      qc.invalidateQueries({ queryKey: ['mappings-stats', companyId] })
      toast.success('Маппинг удалён')
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка удаления'),
  })

  const meta = KINDS.find((k) => k.value === kind)!

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Маппинги для сверки</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Связь ключей внешних источников (STS, файлы ТТН) с записями справочников БП ГИГ.
            Используется при построчной сверке документов.
          </p>
        </div>
        <Button size="sm" onClick={() => { setCreating(true); setEditing(null) }} className="gap-1.5 shrink-0">
          <Plus className="h-3.5 w-3.5" /> Добавить
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <Card className="py-2 gap-0">
            <CardContent className="p-3">
              <div className="text-[10px] text-muted-foreground uppercase">Всего</div>
              <div className="text-lg font-semibold mt-0.5">{stats.total.toLocaleString('ru-RU')}</div>
            </CardContent>
          </Card>
          {KINDS.map((k) => {
            const n = stats.byKind[k.value] ?? 0
            return (
              <Card key={k.value} className="py-2 gap-0">
                <CardContent className="p-3">
                  <div className="text-[10px] text-muted-foreground uppercase truncate">{k.label}</div>
                  <div className="text-lg font-semibold mt-0.5">{n.toLocaleString('ru-RU')}</div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <Tabs value={kind} onValueChange={(v) => setKind(v as MappingKind)}>
        <TabsList className="grid w-full grid-cols-5 h-9">
          {KINDS.map((k) => {
            const Icon = k.icon
            return (
              <TabsTrigger key={k.value} value={k.value} className="text-xs gap-1.5">
                <Icon className="h-3.5 w-3.5" /> {k.label}
              </TabsTrigger>
            )
          })}
        </TabsList>

        <TabsContent value={kind} className="mt-3">
          <Card className="py-3 gap-2">
            <CardHeader className="pb-0">
              <CardTitle className="text-sm flex items-center gap-2">
                <Link2 className="h-4 w-4 text-muted-foreground" /> {meta.label}
                <Badge variant="outline" className="text-[10px] font-mono ml-1">{rows.length}</Badge>
              </CardTitle>
              <CardDescription className="text-xs">{meta.hint}</CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              {isLoading && <Loader2 className="h-4 w-4 animate-spin mx-auto" />}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-7 text-[10px] w-32">Ключ источника</TableHead>
                    <TableHead className="h-7 text-[10px]">Цель в БП</TableHead>
                    <TableHead className="h-7 text-[10px] w-48 font-mono">Ref</TableHead>
                    <TableHead className="h-7 text-[10px] w-20">Способ</TableHead>
                    <TableHead className="h-7 text-[10px] w-16 text-right">Conf</TableHead>
                    <TableHead className="h-7 text-[10px] w-24"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((m) => (
                    <TableRow key={m.id} className="text-xs">
                      <TableCell className="py-1.5 font-mono text-[11px]">{m.source_key}</TableCell>
                      <TableCell className="py-1.5">{m.target_name || '—'}</TableCell>
                      <TableCell className="py-1.5 font-mono text-[10px] text-muted-foreground truncate" title={m.target_ref}>
                        {m.target_ref.slice(0, 8)}…
                      </TableCell>
                      <TableCell className="py-1.5">
                        <Badge variant="outline" className={`text-[9px] h-4 px-1 ${METHOD_STYLE[m.method] ?? ''}`}>
                          {m.method}
                        </Badge>
                      </TableCell>
                      <TableCell className="py-1.5 text-right font-mono">{m.confidence}</TableCell>
                      <TableCell className="py-1.5 text-right">
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => { setEditing(m); setCreating(false) }}>
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-destructive"
                          onClick={() => { if (confirm('Удалить маппинг?')) deleteMut.mutate(m.id) }}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {rows.length === 0 && !isLoading && (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-[11px] text-muted-foreground py-6">
                        Маппингов нет — добавьте первый кнопкой «Добавить».
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <MappingEditSheet
        open={creating || !!editing}
        companyId={companyId}
        editing={editing}
        defaultKind={kind}
        onClose={() => { setEditing(null); setCreating(false) }}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ['mappings', companyId] })
          qc.invalidateQueries({ queryKey: ['mappings-stats', companyId] })
        }}
      />
    </div>
  )
}


interface EditSheetProps {
  open: boolean
  companyId: string
  editing: ReconcileMapping | null
  defaultKind: MappingKind
  onClose: () => void
  onSaved: () => void
}

function MappingEditSheet({ open, companyId, editing, defaultKind, onClose, onSaved }: EditSheetProps) {
  const isNew = !editing
  const [form, setForm] = useState({
    kind:        editing?.kind        ?? defaultKind,
    sourceKey:   editing?.source_key  ?? '',
    targetRef:   editing?.target_ref  ?? '',
    targetName:  editing?.target_name ?? '',
    confidence:  editing?.confidence  ?? 100,
    method:      (editing?.method ?? 'manual') as MappingMethod,
    note:        editing?.note ?? '',
  })

  // Reset form when sheet opens with different record
  function resetForOpen() {
    setForm({
      kind:        editing?.kind        ?? defaultKind,
      sourceKey:   editing?.source_key  ?? '',
      targetRef:   editing?.target_ref  ?? '',
      targetName:  editing?.target_name ?? '',
      confidence:  editing?.confidence  ?? 100,
      method:      (editing?.method ?? 'manual') as MappingMethod,
      note:        editing?.note ?? '',
    })
  }

  // Чтобы не вешать useEffect (мелкое), сбрасываем при изменении ключа
  // editing?.id. Простая защита: при open=true и editing — берём свежие значения.

  const saveMut = useMutation({
    mutationFn: async () => {
      if (isNew) {
        return createMapping({
          companyId,
          kind: form.kind,
          sourceKey: form.sourceKey.trim(),
          targetRef: form.targetRef.trim(),
          targetName: form.targetName.trim() || undefined,
          confidence: form.confidence,
          method: form.method,
          note: form.note.trim() || undefined,
        })
      }
      return updateMapping(editing!.id, {
        sourceKey:  form.sourceKey.trim(),
        targetRef:  form.targetRef.trim(),
        targetName: form.targetName.trim(),
        confidence: form.confidence,
        method:     form.method,
        note:       form.note.trim(),
      })
    },
    onSuccess: () => {
      toast.success(isNew ? 'Маппинг создан' : 'Маппинг обновлён')
      onSaved()
      onClose()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось сохранить'),
  })

  // Sync form при смене записи
  if (open && editing && form.sourceKey !== editing.source_key && saveMut.isIdle) {
    // первичная инициализация для редактирования другой записи
    resetForOpen()
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="!max-w-lg p-0 overflow-y-auto">
        <SheetHeader className="p-4 pb-2">
          <SheetTitle className="text-base">{isNew ? 'Новый маппинг' : 'Редактирование'}</SheetTitle>
          <SheetDescription className="text-xs">
            {KINDS.find((k) => k.value === form.kind)?.hint}
          </SheetDescription>
        </SheetHeader>
        <div className="p-4 space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs">Тип</Label>
            <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v as MappingKind })} disabled={!isNew}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {KINDS.map((k) => (<SelectItem key={k.value} value={k.value} className="text-xs">{k.label}</SelectItem>))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Ключ источника</Label>
            <Input value={form.sourceKey} onChange={(e) => setForm({ ...form, sourceKey: e.target.value })}
              placeholder="208 / АИ-95-К5 / card / артикул поставщика" className="h-8 text-xs font-mono" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">UUID цели (external_ref в Catalog)</Label>
            <Input value={form.targetRef} onChange={(e) => setForm({ ...form, targetRef: e.target.value })}
              placeholder="b5167d72-0501-11e8-b37c-0025906bb4c7" className="h-8 text-xs font-mono" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Имя цели (для UI)</Label>
            <Input value={form.targetName} onChange={(e) => setForm({ ...form, targetName: e.target.value })}
              placeholder="АЗС Выборг (208)" className="h-8 text-xs" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs">Способ</Label>
              <Select value={form.method} onValueChange={(v) => setForm({ ...form, method: v as MappingMethod })}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual" className="text-xs">manual</SelectItem>
                  <SelectItem value="auto" className="text-xs">auto</SelectItem>
                  <SelectItem value="ai" className="text-xs">ai</SelectItem>
                  <SelectItem value="imported_from_bp" className="text-xs">imported</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Уверенность (0-100)</Label>
              <Input type="number" min={0} max={100} value={form.confidence}
                onChange={(e) => setForm({ ...form, confidence: parseInt(e.target.value || '0', 10) })}
                className="h-8 text-xs font-mono" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Комментарий</Label>
            <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
              placeholder="откуда взяли соответствие" className="h-8 text-xs" />
          </div>
          <div className="flex gap-2 pt-2 border-t border-border/40">
            <Button size="sm" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}
              className="gap-1.5">
              {saveMut.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isNew ? 'Создать' : 'Сохранить'}
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose}>Отмена</Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
