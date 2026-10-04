/**
 * Read-only рендер набора полей MetadataField[] (паспорт станции и т.п.).
 *
 * Вид один на все реквизиты объекта: подпись сверху, значение под ней, слева.
 * Раньше здесь была пара «подпись слева — значение справа», и в карточке
 * получался разнобой: половина блоков читалась сверху вниз, половина — с
 * рваным правым краем. Хуже того, длинные значения рвались посреди слова
 * («CCS Combo 2, CHA deMO»), потому что выравнивание вправо в узкой колонке
 * требует переноса по любому символу (замечание МАГа 20.09.2026).
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
    <dl className="grid grid-cols-1 gap-x-8 gap-y-2.5 sm:grid-cols-2">
      {rows.map((f) => (
        <div key={f.key} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{f.label}</dt>
          <dd className="break-words font-medium">
            {String(values[f.key])}{f.unit ? ` ${f.unit}` : ''}
          </dd>
        </div>
      ))}
    </dl>
  )
}
