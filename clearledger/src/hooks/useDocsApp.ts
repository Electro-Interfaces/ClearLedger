/**
 * Доступно ли «Дело» этому человеку в этом пространстве — то же правило, что у
 * гарда маршрута `/docs`: право роли на продукт плюс его подключённость компании.
 * Одно место на всех, кто показывает вход в документы, иначе кнопка и вкладка
 * начинают расходиться с самим маршрутом.
 */
import { useCompany } from '@/contexts/CompanyContext'
import { useAppEnabled } from '@/hooks/useCompanyRegistry'

export function useDocsApp(): boolean {
  const { companyId, canApp } = useCompany()
  // Хук зовётся безусловно — порядок хуков не должен зависеть от роли. `null`
  // (реестр ещё не ответил) не прячет вход, иначе он моргал бы на холодном заходе.
  const enabled = useAppEnabled(companyId, 'docs')
  return canApp('docs') && enabled !== false
}
