/**
 * Может ли человек НАСТРАИВАТЬ подключения этой организации.
 *
 * Тот же расчёт, что на сервере (`require_company_admin`): суперадмин контейнера
 * или админ этой организации. Хук вынесен из ConnectPages, потому что кнопки
 * «Создать коннектор», «Добавить источник» и корзины на соседних экранах
 * рисовались всем подряд — сервер такие запросы отклоняет, и человек получал
 * отказ на кнопку, которой у него не должно было быть.
 */
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

export function useCanManage() {
  const { user } = useAuth()
  const { companyId } = useCompany()
  return {
    companyId,
    isSuperadmin: !!user?.is_superadmin,
    canManage: !!user?.is_superadmin
      || (user?.companies ?? []).some((c) => c.id === companyId && c.role === 'admin'),
  }
}
