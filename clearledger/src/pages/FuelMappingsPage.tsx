/**
 * Страница маппингов топливных каналов STS → 1С:Бухгалтерия (ГИГ).
 * Каналы оплаты · Маппинг видов оплат · Виды топлива.
 */
import { FuelMappingsPanel } from '@/components/fuel/FuelMappingsPanel'

export function FuelMappingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Маппинги топливных каналов</h1>
        <p className="text-sm text-muted-foreground">
          Соответствия STS → 1С:Бухгалтерия: виды оплат → каналы → документы, виды топлива → номенклатура.
          На их основе сменный отчёт раскладывается по каналам и формируются документы БП.
        </p>
      </div>
      <FuelMappingsPanel />
    </div>
  )
}
