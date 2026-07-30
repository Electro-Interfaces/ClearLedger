/**
 * Страница приложения «Инфо» — знание пространства целиком.
 *
 * Сюда попадают со стола (плитка): полноэкранное рабочее место, где знание не только
 * читают, но и ведут — документы компании заводятся отсюда. Кнопка «Инфо» в шапке
 * открывает то же приложение окном (чтение), правая рельса — подсказку под открытый
 * экран (`InfoContextPanel`). Источник данных у всех трёх один (docs/INFO.md).
 */
import { useCompany } from '@/contexts/CompanyContext'
import { InfoCenter } from '@/components/info/InfoCenter'

export function InfoPage() {
  const { companyId } = useCompany()
  if (!companyId) return null
  return <InfoCenter companyId={companyId} />
}

export default InfoPage
