/**
 * Тип точки обслуживания (каталог типов).
 *
 * Тип = код + единица + набор полей (схема). Встроенные типы (companyId=null,
 * isBuiltin) доступны всем; кастомные — у компании. Значения полей конкретной
 * точки лежат в ServiceLocation.metadata. Нижестоящий код опирается на
 * стабильный `code` (например 'fuel_station'), а не на лейбл.
 */
import type { MetadataField } from '@/config/profiles'

export type { MetadataField }

export type NomenclatureKind = 'fuel' | 'energy' | 'goods' | 'food' | 'none'

export interface LocationTypeDef {
  id: string
  /** null = встроенный (системный) тип */
  companyId: string | null
  code: string
  name: string
  /** имя lucide-иконки */
  icon: string
  /** единица по умолчанию: л / кВт·ч / шт / "" */
  unit: string
  nomenclatureKind: NomenclatureKind
  /** схема полей типа */
  fields: MetadataField[]
  isBuiltin: boolean
  sortOrder: number
  status: string
}
