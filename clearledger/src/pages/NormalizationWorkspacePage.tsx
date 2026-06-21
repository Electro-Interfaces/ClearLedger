/**
 * Рабочая область «Нормализация» (/normalization) — отдельный пункт левого меню.
 *
 * Нормализация (приведение первичных документов Слоя 1 к нормализованной базе Слоя 2)
 * вынесена из вкладок-режимов рабочего стола в самостоятельную область — по образцу
 * «Сверки» (ReconciliationPage). Сама панель — NormalizationPanel (своё вертикальное
 * меню Конвейер/Правила/Маппинг/Агенты/Журнал), обёрнута в WorkspaceProvider.
 */
import { WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { NormalizationPanel } from '@/components/workspace/NormalizationPanel'
import { Sparkles } from 'lucide-react'

export function NormalizationWorkspacePage() {
  return (
    <WorkspaceProvider>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5">
          <Sparkles className="h-4 w-4 text-primary" />
          <h1 className="text-sm font-semibold">Нормализация</h1>
          <span className="text-xs text-muted-foreground">— приведение первичных документов к нормализованной базе (Слой 2)</span>
        </div>
        <div className="min-h-0 flex-1">
          <NormalizationPanel />
        </div>
      </div>
    </WorkspaceProvider>
  )
}

export default NormalizationWorkspacePage
