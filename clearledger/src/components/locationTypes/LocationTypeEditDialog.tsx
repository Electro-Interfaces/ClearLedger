/**
 * Создание/правка типа точки — конструктор: реквизиты типа + построитель полей.
 * Кастомные типы правит админ компании; встроенные — суперадмин (код read-only).
 */
import { useState, type ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { createLocationType, updateLocationType } from '@/services/locationTypeService'
import { LOCATION_ICON_NAMES } from './locationIcons'
import type { LocationTypeDef, MetadataField, NomenclatureKind } from '@/types/locationType'

const FIELD_TYPES: MetadataField['type'][] = ['text', 'number', 'date', 'select', 'textarea']
const FIELD_TYPE_LABEL: Record<MetadataField['type'], string> = {
  text: 'Текст', number: 'Число', date: 'Дата', select: 'Список', textarea: 'Многострочный',
}
const KINDS: { id: NomenclatureKind; label: string }[] = [
  { id: 'fuel', label: 'Топливо' }, { id: 'energy', label: 'Энергия' },
  { id: 'goods', label: 'Товары' }, { id: 'food', label: 'Общепит' },
  { id: 'none', label: 'Нет' },
]

interface EditableField extends MetadataField {
  optionsText?: string  // options в виде строки через запятую (для редактирования)
}

export function LocationTypeEditDialog({
  type,
  children,
  onSaved,
}: {
  type?: LocationTypeDef
  children: ReactNode
  onSaved?: () => void
}) {
  const isEdit = !!type
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const [code, setCode] = useState(type?.code ?? '')
  const [name, setName] = useState(type?.name ?? '')
  const [icon, setIcon] = useState(type?.icon ?? 'MapPin')
  const [unit, setUnit] = useState(type?.unit ?? '')
  const [kind, setKind] = useState<NomenclatureKind>(type?.nomenclatureKind ?? 'none')
  const [fields, setFields] = useState<EditableField[]>(
    () => (type?.fields ?? []).map((f) => ({ ...f, optionsText: (f.options ?? []).join(', ') })),
  )

  function addField() {
    setFields((fs) => [...fs, { key: '', label: '', type: 'text', optionsText: '' }])
  }
  function patchField(i: number, patch: Partial<EditableField>) {
    setFields((fs) => fs.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  }
  function removeField(i: number) {
    setFields((fs) => fs.filter((_, j) => j !== i))
  }

  async function handleSave() {
    if (!code.trim() || !name.trim()) {
      toast.error('Код и название обязательны')
      return
    }
    const built: MetadataField[] = fields
      .filter((f) => f.key.trim() && f.label.trim())
      .map((f) => {
        const mf: MetadataField = { key: f.key.trim(), label: f.label.trim(), type: f.type }
        if (f.type === 'select') {
          mf.options = (f.optionsText ?? '').split(',').map((s) => s.trim()).filter(Boolean)
        }
        if (f.unit?.trim()) mf.unit = f.unit.trim()
        if (f.required) mf.required = true
        return mf
      })
    setSaving(true)
    try {
      const input = {
        code: code.trim(), name: name.trim(), icon: icon || 'MapPin',
        unit: unit.trim(), nomenclatureKind: kind, fields: built,
      }
      if (isEdit && type) await updateLocationType(type.id, input)
      else await createLocationType(companyId, input)
      await qc.invalidateQueries({ queryKey: ['location-types'] })
      toast.success(isEdit ? 'Тип обновлён' : 'Тип создан')
      setOpen(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить тип')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Тип «${type!.name}»` : 'Новый тип точки'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="lt-name">Название</Label>
              <Input id="lt-name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Электрозарядная станция" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lt-code">Код</Label>
              <Input id="lt-code" value={code} onChange={(e) => setCode(e.target.value)}
                placeholder="ev_charging" disabled={isEdit} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="lt-icon">Иконка</Label>
              <Select value={icon} onValueChange={setIcon}>
                <SelectTrigger id="lt-icon"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {LOCATION_ICON_NAMES.map((n) => (
                    <SelectItem key={n} value={n}>{n}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lt-unit">Единица</Label>
              <Input id="lt-unit" value={unit} onChange={(e) => setUnit(e.target.value)}
                placeholder="кВт·ч" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lt-kind">Номенклатура</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as NomenclatureKind)}>
                <SelectTrigger id="lt-kind"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {KINDS.map((k) => (
                    <SelectItem key={k.id} value={k.id}>{k.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Построитель полей */}
          <div className="space-y-2 border-t border-border/50 pt-3">
            <div className="flex items-center justify-between">
              <Label>Поля типа</Label>
              <Button type="button" variant="outline" size="sm" onClick={addField}>
                <Plus className="h-3.5 w-3.5 mr-1" /> Поле
              </Button>
            </div>
            {fields.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Полей нет. Они показываются в форме точки этого типа и пишутся в её свойства.
              </p>
            )}
            {fields.map((f, i) => (
              <div key={i} className="rounded-md border border-border/50 p-2 space-y-2">
                <div className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-3 space-y-1">
                    <Label className="text-[11px]">Ключ</Label>
                    <Input value={f.key} onChange={(e) => patchField(i, { key: e.target.value })}
                      placeholder="maxPowerKw" className="h-8" />
                  </div>
                  <div className="col-span-4 space-y-1">
                    <Label className="text-[11px]">Подпись</Label>
                    <Input value={f.label} onChange={(e) => patchField(i, { label: e.target.value })}
                      placeholder="Макс. мощность" className="h-8" />
                  </div>
                  <div className="col-span-3 space-y-1">
                    <Label className="text-[11px]">Тип</Label>
                    <Select value={f.type} onValueChange={(v) => patchField(i, { type: v as MetadataField['type'] })}>
                      <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {FIELD_TYPES.map((t) => (
                          <SelectItem key={t} value={t}>{FIELD_TYPE_LABEL[t]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="col-span-2 flex justify-end">
                    <Button type="button" variant="ghost" size="icon" className="h-8 w-8"
                      onClick={() => removeField(i)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-3 space-y-1">
                    <Label className="text-[11px]">Единица</Label>
                    <Input value={f.unit ?? ''} onChange={(e) => patchField(i, { unit: e.target.value })}
                      placeholder="кВт" className="h-8" />
                  </div>
                  {f.type === 'select' && (
                    <div className="col-span-7 space-y-1">
                      <Label className="text-[11px]">Варианты (через запятую)</Label>
                      <Input value={f.optionsText ?? ''} onChange={(e) => patchField(i, { optionsText: e.target.value })}
                        placeholder="Type 2, CCS, CHAdeMO" className="h-8" />
                    </div>
                  )}
                  <label className="col-span-2 flex items-center gap-1.5 text-xs pb-1.5 cursor-pointer">
                    <input type="checkbox" checked={!!f.required}
                      onChange={(e) => patchField(i, { required: e.target.checked })} />
                    Обязательное
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>Отмена</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {isEdit ? 'Сохранить' : 'Создать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
