import { FlaskConical } from 'lucide-react'
import { isDemoMode } from '@/services/apiClient'

export function DemoBanner() {
  if (!isDemoMode()) return null

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-16 z-[80] flex justify-center px-3 md:bottom-3">
      <div
        role="status"
        className="pointer-events-auto flex max-w-[680px] items-center gap-2 rounded-xl border border-amber-400/60 bg-background/95 px-3 py-2 text-xs shadow-lg backdrop-blur"
      >
        <FlaskConical className="size-4 shrink-0 text-amber-600" />
        <span>
          <strong>Демонстрационный контур.</strong>{' '}
          Данные вымышлены, внешние сервисы не вызываются, изменения не сохраняются.
        </span>
      </div>
    </div>
  )
}
