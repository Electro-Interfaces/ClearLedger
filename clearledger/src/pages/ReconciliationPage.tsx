/**
 * Рабочая область «Сверка данных» (/reconciliation).
 *
 * Разрезы сверки идут ДО основной рабочей области (рабочего стола): на вход —
 * потоки каналов (anchor STS-смена + внешние MSTO/TradeCorp/ОФД/эквайринг),
 * на выход — сверенные данные для рабочего стола и выгрузки в 1С.
 *
 * Лево — меню разрезов (Обзор / Онлайн-заказы / Корп.карты / Эквайринг / Чеки /
 * Нефтебазы / Сливы / Перевозки); центр — параметры (период/станции) + результаты.
 * Первый рабочий разрез — Онлайн-заказы (MSTO ↔ смена).
 *
 * Сама панель разрезов — ReconciliationPanel (переиспользуется и в рабочем столе).
 * Здесь она вынесена в самостоятельную область, обёрнута в WorkspaceProvider
 * (панель хранит последний результат сверки в контексте рабочего стола).
 */
import { WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { ReconciliationPanel } from '@/components/workspace/ReconciliationPanel'
import { GitCompare } from 'lucide-react'

export function ReconciliationPage() {
  return (
    <WorkspaceProvider>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5">
          <GitCompare className="h-4 w-4 text-primary" />
          <h1 className="text-sm font-semibold">Сверка данных</h1>
          <span className="text-xs text-muted-foreground">— разрезы до рабочей области</span>
        </div>
        <div className="min-h-0 flex-1">
          <ReconciliationPanel />
        </div>
      </div>
    </WorkspaceProvider>
  )
}

export default ReconciliationPage
