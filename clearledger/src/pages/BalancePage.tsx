/**
 * Тонкая обёртка-страница для deep-link /balance.
 * Основной вход в баланс — пункт суб-навигации режима «Управленческий» (ManagementPanel),
 * который рендерит ту же витрину `BalanceVitrine`. Модуль подключается к компании по профилю.
 */
import { BalanceVitrine } from '@/components/balance/BalanceVitrine'

export function BalancePage() {
  return (
    <div className="flex-1 min-w-0">
      <BalanceVitrine />
    </div>
  )
}

export default BalancePage
