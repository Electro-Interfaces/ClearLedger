/**
 * Доступны ли «Задачи» этому человеку в этом пространстве — то же правило, что у
 * гарда маршрута `/tasks`: право роли на продукт плюс его подключённость компании.
 * Одно место на всех, кто показывает вход в задачи (шапка, правый док, счётчик),
 * иначе кнопка и вкладка начинают расходиться с самим маршрутом.
 */
import { useCompany } from '@/contexts/CompanyContext'
import { useAppEnabled } from '@/hooks/useCompanyRegistry'

export function useTasksApp(): boolean {
  const { companyId, canApp } = useCompany()
  // Хук зовётся безусловно — порядок хуков не должен зависеть от роли. `null`
  // (реестр ещё не ответил) не прячет вход, иначе он моргал бы на холодном заходе.
  const enabled = useAppEnabled(companyId, 'plan')
  return canApp('plan') && enabled !== false
}
