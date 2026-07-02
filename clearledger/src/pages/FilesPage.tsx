/**
 * Страница «Документы» — первый слой данных (L1 RAW):
 * хранилище загруженных первичных документов (смены, ТТН, ручная загрузка).
 *
 * Раньше жила как левая раскрывающаяся панель рабочего стола («Хранилище»).
 * Вынесена в отдельный раздел левого меню; функционал ручной загрузки —
 * в соседнем пункте «Загрузка» (IntakePage).
 */
import { WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { useCompany } from '@/contexts/CompanyContext'
import { ExplorerView } from '@/components/workspace/raw-panel/ExplorerView'
import { EnergyRawPanel } from '@/components/workspace/EnergySidePanels'

function FilesContent() {
  // Профиль определяет источник первого слоя: fuel (ГИГ) — смены/ТТН STS,
  // energy (РусГидро, ЭЗС) — первичка инфраструктуры.
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'

  return (
    <div className="h-full min-h-0 overflow-hidden flex flex-col">
      <div className="flex-1 min-h-0 overflow-hidden">
        {isEnergy ? <EnergyRawPanel /> : <ExplorerView />}
      </div>
    </div>
  )
}

export function FilesPage() {
  return (
    <WorkspaceProvider>
      <FilesContent />
    </WorkspaceProvider>
  )
}

export default FilesPage
