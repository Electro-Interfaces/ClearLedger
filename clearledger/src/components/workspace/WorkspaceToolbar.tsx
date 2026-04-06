/**
 * Общий тулбар рабочего стола — над всеми 3 панелями.
 * Станция, обновление, кнопка «Нормализация» с модальным окном параметров.
 */

import { useState } from 'react'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { useShifts } from '@/hooks/useFuel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { RefreshCw, Sparkles, Play, GitCompare, BarChart3, Landmark, BookOpen, Receipt, FileOutput } from 'lucide-react'
import type { CoreMode } from '@/contexts/WorkspaceContext'
import { useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'

export function WorkspaceToolbar() {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { globalStation, setGlobalStation, coreMode, setCoreMode } = useWorkspace()
  const { isFetching } = useShifts(
    globalStation === 'all' ? undefined : Number(globalStation),
  )

  const [normOpen, setNormOpen] = useState(false)
  const [normParams, setNormParams] = useState({
    dateFrom: format(new Date(), 'yyyy-MM-dd'),
    dateTo: format(new Date(), 'yyyy-MM-dd'),
    docType: 'all' as string,
    method: 'auto' as string,
  })

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  function handleRunNormalization() {
    // TODO: запуск процедуры нормализации с normParams
    setNormOpen(false)
  }

  return (
    <div className="flex items-center px-3 py-1.5 border-b border-border/50 bg-background flex-shrink-0">
      {/* Станция */}
      <Select value={globalStation} onValueChange={setGlobalStation}>
        <SelectTrigger className="h-7 w-[160px] text-xs">
          <SelectValue placeholder="Все станции" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все станции</SelectItem>
          {settings.stations.map((s) => (
            <SelectItem key={s.code} value={String(s.code)}>
              {s.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Обновить */}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 ml-1"
        onClick={handleRefresh}
        disabled={isFetching}
        title="Обновить данные"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
      </Button>

      <div className="h-4 w-px bg-border/50 mx-2" />

      {/* Конвейер — переключатель режимов */}
      <div className="flex items-center gap-0.5 bg-muted/40 rounded-md p-0.5">
        {([
          { mode: 'normalize' as CoreMode, icon: Sparkles, label: 'Нормализация' },
          { mode: 'reconcile' as CoreMode, icon: GitCompare, label: 'Сверка' },
          { mode: 'management' as CoreMode, icon: BarChart3, label: 'Управленческий' },
          { mode: 'financial' as CoreMode, icon: Landmark, label: 'Финансовый' },
          { mode: 'accounting' as CoreMode, icon: BookOpen, label: 'Бухгалтерский' },
          { mode: 'tax' as CoreMode, icon: Receipt, label: 'Налоговый' },
          { mode: 'export' as CoreMode, icon: FileOutput, label: 'Выгрузка' },
        ]).map(({ mode, icon: Icon, label }) => (
          <button
            key={mode}
            onClick={() => setCoreMode(mode)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors ${
              coreMode === mode ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-3 w-3" />
            {label}
          </button>
        ))}
      </div>

      {/* Нормализация — модалка параметров */}
      <Dialog open={normOpen} onOpenChange={setNormOpen}>
        <DialogTrigger asChild>
          <Button variant="ghost" size="icon" className="h-7 w-7 ml-1" title="Параметры нормализации" disabled={coreMode !== 'normalize'}>
            <Play className="h-3.5 w-3.5" />
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>Нормализация документов</DialogTitle>
            <DialogDescription>
              Анализ входящих документов и преобразование в операционную базу проекта.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Период */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Период с</Label>
                <Input
                  type="date"
                  className="h-8 text-xs"
                  value={normParams.dateFrom}
                  onChange={(e) => setNormParams((p) => ({ ...p, dateFrom: e.target.value }))}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">по</Label>
                <Input
                  type="date"
                  className="h-8 text-xs"
                  value={normParams.dateTo}
                  onChange={(e) => setNormParams((p) => ({ ...p, dateTo: e.target.value }))}
                />
              </div>
            </div>

            {/* Тип документа */}
            <div className="space-y-1.5">
              <Label className="text-xs">Тип документа</Label>
              <Select value={normParams.docType} onValueChange={(v) => setNormParams((p) => ({ ...p, docType: v }))}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все типы</SelectItem>
                  <SelectItem value="shifts">Сменные отчёты</SelectItem>
                  <SelectItem value="receipts">ТТН (поступления)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Способ нормализации */}
            <div className="space-y-1.5">
              <Label className="text-xs">Способ</Label>
              <Select value={normParams.method} onValueChange={(v) => setNormParams((p) => ({ ...p, method: v }))}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Автоматический</SelectItem>
                  <SelectItem value="manual">С ручным подтверждением</SelectItem>
                  <SelectItem value="preview">Только предпросмотр</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setNormOpen(false)}>Отмена</Button>
            <Button size="sm" className="gap-1.5" onClick={handleRunNormalization}>
              <Play className="h-3.5 w-3.5" />
              Запустить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}
