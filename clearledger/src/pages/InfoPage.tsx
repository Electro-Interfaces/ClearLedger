/**
 * Страница приложения «Инфо» — знание пространства целиком.
 *
 * Сюда попадают со стола (плитка) и кнопкой в шапке любого продукта. Контекстная
 * подсказка под конкретную рабочую область — правая панель `InfoContextPanel`,
 * данные у них общие (docs/INFO.md).
 */
import { useCompany } from '@/contexts/CompanyContext'
import { InfoCenter } from '@/components/info/InfoCenter'

export function InfoPage() {
  const { companyId } = useCompany()
  if (!companyId) return null
  return <InfoCenter companyId={companyId} />
}

export default InfoPage
