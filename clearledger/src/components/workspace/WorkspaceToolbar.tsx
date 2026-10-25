/**
 * Общий тулбар рабочего стола — над рабочей областью: период · область · данные ·
 * источник (`WorkspaceFilterBar`). Переключатель разрезов учёта — в вертикальном
 * меню слева (`WorkspaceModeSidebar`).
 *
 * Слева стояла метка-якорь «Фильтр рабочей области» — иконка воронки и подпись в две
 * строки. Она ничего не открывала, занимала двести точек ширины и заставляла читать
 * слово «фильтр» трижды подряд: метка, кнопка «Расширенный фильтр», чипы активных
 * ограничений. Убрана (МАГ, 15.09.2026, поручения №65 и №66): зона обозначена своей
 * строкой и рамкой, а кнопка названа тем, что открывает.
 */

import { useLocation } from 'react-router-dom'
import { useFilters } from '@/contexts/FilterContext'
import { WorkspaceFilterBar } from './WorkspaceFilterBar'

export function WorkspaceToolbar() {
  const { pathname } = useLocation()
  const { period, regionIds } = useFilters()
  if (pathname.startsWith('/marketing')) return <div className="shrink-0 border-b bg-card px-3 py-2">
    <details className="sm:hidden">
      <summary className="min-h-11 cursor-pointer py-2 text-sm">Период и территория · {regionIds.length ? regionIds.join(', ') : 'Вся сеть'}</summary>
      <WorkspaceFilterBar />
    </details>
    <p className="text-xs text-muted-foreground sm:hidden">{period.from} — {period.to}</p>
    <div className="hidden sm:block"><WorkspaceFilterBar /></div>
  </div>
  return (
    <div data-zone="Фильтр: что входит в данные" className="flex shrink-0 items-center gap-3 border-b border-border bg-card px-3 py-3">
      <WorkspaceFilterBar />
    </div>
  )
}
