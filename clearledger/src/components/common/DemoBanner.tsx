import { useState } from 'react'
import { FlaskConical, X } from 'lucide-react'
import { isDemoMode } from '@/services/apiClient'

export function DemoBanner() {
  const [visible, setVisible] = useState(true)
  if (!isDemoMode() || !visible) return null

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
        <button type="button" onClick={() => setVisible(false)} className="pointer-events-auto ml-1 grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Скрыть уведомление о демонстрационном контуре">
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
