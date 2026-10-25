import { useCompany } from '@/contexts/CompanyContext'
import { useAppEnabled } from '@/hooks/useCompanyRegistry'

/**
 * Стоит ли внизу панель пульта. Признак нужен и тому, кто её рисует, и тому, кто
 * из-за неё убирает свою копию кнопки, — держать его копиями значило бы чинить
 * повтор повтором (решение МАГа 06.09.2026).
 */
export function usePulseMobileNav(): boolean {
  const { companyId, canApp } = useCompany()
  const pulseOn = useAppEnabled(companyId, 'pulse')
  return canApp('pulse') && pulseOn !== false
}
