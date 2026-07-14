/**
 * Страница «Документы» — первый слой данных (L1 RAW):
 * хранилище загруженных первичных документов (смены, ТТН, ручная загрузка).
 *
 * Раньше жила как левая раскрывающаяся панель рабочего стола («Хранилище»).
 * Вынесена в отдельный раздел левого меню; функционал ручной загрузки —
 * в соседнем пункте «Загрузка» (IntakePage).
 */
import { WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { ExplorerView } from '@/components/workspace/raw-panel/ExplorerView'

function FilesContent() {
  // Источник первого слоя определяет useRawPanelTree по профилю компании:
  // fuel (ГИГ) — смены/ТТН из БД, прочие — каналы и история их прогонов.
  return (
    <div className="h-full min-h-0 overflow-hidden flex flex-col">
      <div className="flex-1 min-h-0 overflow-hidden">
        <ExplorerView />
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
