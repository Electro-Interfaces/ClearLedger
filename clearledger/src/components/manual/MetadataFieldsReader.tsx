/**
 * Read-only рендер набора полей MetadataField[] (паспорт станции и т.п.).
 * Показывает только заполненные поля: «подпись → значение [единица]».
 */
import type { MetadataField } from '@/config/profiles'

export function MetadataFieldsReader({
  fields,
  values,
}: {
  fields: MetadataField[]
  values: Record<string, unknown>
}) {
  const rows = fields.filter((f) => {
    const v = values?.[f.key]
    return v !== undefined && v !== null && String(v).trim() !== ''
  })
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Свойства не заполнены.</p>
  }
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1">
      {rows.map((f) => (
        <div key={f.key} className="flex justify-between gap-3 border-b border-border/30 py-1.5 text-sm">
          <dt className="text-muted-foreground shrink-0">{f.label}</dt>
          <dd className="font-medium text-right break-all">
            {String(values[f.key])}{f.unit ? ` ${f.unit}` : ''}
          </dd>
        </div>
      ))}
    </dl>
  )
}
