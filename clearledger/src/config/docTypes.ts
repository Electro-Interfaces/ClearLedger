/**
 * Типы данных (документов) фильтра рабочей области — по профилю компании.
 * Единый источник: используется и в фильтр-модалке (WorkspaceFilterModal),
 * и в чипах активного фильтра (ActiveFilterChips). Раньше дублировался
 * в нескольких местах — консолидировано в рамках стандарта (§6.2).
 */
export interface DocTypeOption {
  id: string
  label: string
}

// Фуел-профиль (ГИГ, сеть АЗС): топливо/STS/MSTO/TradeCorp.
export const FUEL_DOC_TYPES: DocTypeOption[] = [
  { id: 'shift_report', label: 'Сменные отчёты' },
  { id: 'receipt', label: 'Поступления (ТТН)' },
  { id: 'price', label: 'Цены' },
  { id: 'sts_transactions', label: 'Операции отпуска' },
  { id: 'sts_coupons', label: 'Купоны и талоны' },
  { id: 'sts_tanks', label: 'Остатки резервуаров' },
  { id: 'msto_transactions', label: 'MSTO транзакции' },
  { id: 'corp_transactions', label: 'TradeCorp транзакции' },
]

// Energy-профиль (РусГидро, сеть ЭЗС): зарядные сессии, ОФД, поставка э/э, ТО, аренда.
export const ENERGY_DOC_TYPES: DocTypeOption[] = [
  { id: 'charge_sessions', label: 'Зарядные сессии' },
  { id: 'ofd_z_reports', label: 'Z-отчёты ОФД' },
  { id: 'energy_supply_invoices', label: 'Счета поставщика э/э' },
  { id: 'maintenance_acts', label: 'Акты ТО' },
  { id: 'rent_contracts', label: 'Договоры аренды' },
]

export function getDocTypes(profileId: string): DocTypeOption[] {
  return profileId === 'energy' ? ENERGY_DOC_TYPES : FUEL_DOC_TYPES
}

export function docTypeLabel(id: string, profileId: string): string {
  return getDocTypes(profileId).find((t) => t.id === id)?.label ?? id
}
