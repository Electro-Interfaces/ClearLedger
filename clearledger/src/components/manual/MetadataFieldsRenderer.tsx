/**
 * Рендер набора полей MetadataField[] в значения (key→string).
 * Переиспользуется формой точки обслуживания (поля типа точки) и др.
 * Извлечён из ManualEntryForm (динамический блок метаполей).
 */
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { MetadataField } from '@/config/profiles'

export function MetadataFieldsRenderer({
  fields,
  values,
  onChange,
}: {
  fields: MetadataField[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
}) {
  if (!fields || fields.length === 0) return null
  return (
    <>
      {fields.map((mf) => (
        <div key={mf.key} className="grid gap-1.5">
          <Label htmlFor={`meta-${mf.key}`}>
            {mf.label}
            {mf.required && <span className="text-destructive ml-1">*</span>}
          </Label>
          {mf.type === 'text' && (
            <Input id={`meta-${mf.key}`} placeholder={mf.placeholder}
              value={values[mf.key] ?? ''} onChange={(e) => onChange(mf.key, e.target.value)} />
          )}
          {mf.type === 'number' && (
            <div className="flex items-center gap-2">
              <Input id={`meta-${mf.key}`} type="number" placeholder={mf.placeholder ?? '0'}
                value={values[mf.key] ?? ''} onChange={(e) => onChange(mf.key, e.target.value)}
                className="flex-1" />
              {mf.unit && <span className="text-sm text-muted-foreground shrink-0">{mf.unit}</span>}
            </div>
          )}
          {mf.type === 'date' && (
            <Input id={`meta-${mf.key}`} type="date"
              value={values[mf.key] ?? ''} onChange={(e) => onChange(mf.key, e.target.value)} />
          )}
          {mf.type === 'select' && (
            <Select value={values[mf.key] ?? ''} onValueChange={(v) => onChange(mf.key, v)}>
              <SelectTrigger id={`meta-${mf.key}`} className="w-full">
                <SelectValue placeholder={mf.placeholder ?? 'Выберите...'} />
              </SelectTrigger>
              <SelectContent>
                {mf.options?.map((opt) => (
                  <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {mf.type === 'textarea' && (
            <Textarea id={`meta-${mf.key}`} placeholder={mf.placeholder} rows={3}
              value={values[mf.key] ?? ''} onChange={(e) => onChange(mf.key, e.target.value)} />
          )}
        </div>
      ))}
    </>
  )
}
