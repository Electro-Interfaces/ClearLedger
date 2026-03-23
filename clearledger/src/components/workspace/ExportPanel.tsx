/**
 * Панель 4: Документы для 1С.
 * Только документы, отмеченные «готов к загрузке» в CorePanel.
 */

import { useState } from 'react'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { FileOutput, Trash2, Upload, PackageCheck } from 'lucide-react'
import { format } from 'date-fns'

const TYPE_LABELS: Record<string, string> = {
  receipt: 'Поступление',
  transfer: 'Перемещение',
  assembly: 'Комплектация',
  retail_sales: 'Розн. продажи',
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Черновик',
  confirmed: 'Подтверждён',
  exported: 'Выгружен',
}

export function ExportPanel({ hideHeader = false }: { hideHeader?: boolean }) {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const { exportDocs, removeExportDoc, markExported } = useWorkspace()

  const filteredDocs = statusFilter === 'all'
    ? exportDocs
    : exportDocs.filter((d) => d.status === statusFilter)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      {!hideHeader && (
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-border/50">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Для 1С
          </h2>
          {exportDocs.length > 0 && (
            <Badge variant="default" className="text-[10px] h-5">
              {exportDocs.length}
            </Badge>
          )}
        </div>
      )}

      {/* Локальный тулбар — фильтр по статусу */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border/30">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-7 w-[120px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все</SelectItem>
            <SelectItem value="draft">Черновики</SelectItem>
            <SelectItem value="confirmed">Подтв.</SelectItem>
            <SelectItem value="exported">Выгруж.</SelectItem>
          </SelectContent>
        </Select>
        <Badge variant="secondary" className="text-[9px] h-4 px-1.5 ml-auto">
          {filteredDocs.length} / {exportDocs.length}
        </Badge>
      </div>

      <ScrollArea className="flex-1">
        {filteredDocs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-muted-foreground gap-3 px-4">
            <FileOutput className="h-10 w-10 opacity-30" />
            <p className="text-xs text-center">
              {exportDocs.length === 0
                ? <>Нет документов для загрузки.<br />Выберите смену и нажмите «В 1С».</>
                : 'Нет документов с выбранным статусом.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border/20">
            {filteredDocs.map((doc) => (
              <div key={doc.id} className="px-3 py-3 hover:bg-accent/30 transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Badge variant="outline" className="text-[9px] h-4 px-1.5 shrink-0">
                        {TYPE_LABELS[doc.type] ?? doc.type}
                      </Badge>
                      <Badge
                        variant={doc.status === 'exported' ? 'default' : 'secondary'}
                        className="text-[9px] h-4 px-1.5"
                      >
                        {STATUS_LABELS[doc.status]}
                      </Badge>
                    </div>
                    <p className="text-xs font-medium truncate">{doc.label}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {format(new Date(doc.createdAt), 'dd.MM.yyyy HH:mm')}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {doc.status !== 'exported' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        title="Выгрузить в TradeLedger"
                        onClick={() => markExported(doc.id)}
                      >
                        <Upload className="h-3 w-3" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 text-muted-foreground hover:text-destructive"
                      title="Убрать"
                      onClick={() => removeExportDoc(doc.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Footer */}
      {exportDocs.length > 0 && (
        <div className="px-3 py-2 border-t border-border/50">
          <Button size="sm" className="w-full h-8 text-xs gap-1.5" variant="default">
            <PackageCheck className="h-3.5 w-3.5" />
            Выгрузить все ({exportDocs.filter((d) => d.status !== 'exported').length})
          </Button>
        </div>
      )}
    </div>
  )
}
