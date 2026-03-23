import type { ProfileId } from './profiles'

export interface Company {
  id: string
  name: string
  shortName: string
  inn?: string
  color: string
  profileId: ProfileId
}

export interface CompanyCustomization {
  disabledCategories: string[]
  disabledSubcategories: string[]
  disabledDocTypes: string[]
  disabledConnectors: string[]
}

export const defaultCompanies: Company[] = [
  { id: 'gig', name: 'ООО ГИГ (ГазИнвестГрупп)', shortName: 'ГИГ', inn: '7839124578', color: '#3b82f6', profileId: 'fuel' },
]

export const defaultCompanyId = 'gig'

export function emptyCustomization(): CompanyCustomization {
  return {
    disabledCategories: [],
    disabledSubcategories: [],
    disabledDocTypes: [],
    disabledConnectors: [],
  }
}
