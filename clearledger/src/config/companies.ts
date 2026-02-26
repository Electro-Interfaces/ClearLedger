import type { ProfileId } from './profiles'

export interface Company {
  id: string
  name: string
  shortName: string
  inn?: string
  color: string
  profileId: ProfileId
}

/** Кастомизация профиля для конкретной компании */
export interface CompanyCustomization {
  /** Отключённые категории (id категорий) */
  disabledCategories: string[]
  /** Отключённые подкатегории (ключ = "categoryId/subcategoryId") */
  disabledSubcategories: string[]
  /** Отключённые типы документов (id типов) */
  disabledDocTypes: string[]
  /** Отключённые шаблоны коннекторов (id шаблонов) */
  disabledConnectors: string[]
}

export const defaultCompanies: Company[] = [
  { id: 'npk', name: 'НПК', shortName: 'НПК', color: '#3b82f6', profileId: 'fuel' },
  { id: 'rti', name: 'РТИ', shortName: 'РТИ', color: '#8b5cf6', profileId: 'fuel' },
  { id: 'ts94', name: 'ТС-94', shortName: 'ТС-94', color: '#10b981', profileId: 'trade' },
  { id: 'ofptk', name: 'ОФ ПТК', shortName: 'ОФПТК', color: '#f59e0b', profileId: 'retail' },
  { id: 'rushydro', name: 'РусГидро', shortName: 'РусГидро', color: '#ef4444', profileId: 'energy' },
]

export const defaultCompanyId = 'npk'

export function emptyCustomization(): CompanyCustomization {
  return {
    disabledCategories: [],
    disabledSubcategories: [],
    disabledDocTypes: [],
    disabledConnectors: [],
  }
}
