/**
 * Модальное окно экспорта: выбор формата, колонок, параметров.
 */

import { useState, useMemo } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Download, AlertCircle, CheckCircle2 } from 'lucide-react'
import { exportToExcel, exportToCsv, exportTo1C, exportToEnterpriseData } from '@/services/exportService'
import { validateForExport } from '@/services/exportValidationService'
import { logEvent } from '@/services/auditService'
import { toast } from 'sonner'
import type { DataEntry } from '@/types'

type ExportFormat = 'excel' | 'csv' | '1c-xml' | 'enterprise-data'

const ALL_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'title', label: 'Название' },
  { key: 'categoryId', label: 'Категория' },
  { key: 'subcategoryId', label: 'Подкатегория' },
  { key: 'docTypeId', label: 'Тип документа' },
  { key: 'status', label: 'Статус' },
  { key: 'source', label: 'Источник' },
  { key: 'sourceLabel', label: 'Метка источника' },
  { key: 'createdAt', label: 'Создан' },
  { key: 'updatedAt', label: 'Обновлён' },
  { key: 'counterparty', label: 'Контрагент' },
  { key: 'amount', label: 'Сумма' },
  { key: 'inn', label: 'ИНН' },
  { key: 'docNumber', label: 'Номер документа' },
  { key: 'docDate', label: 'Дата документа' },
]

const DEFAULT_SELECTED = ['id', 'title', 'categoryId', 'subcategoryId', 'status', 'source', 'createdAt']

interface ExportModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  entries: DataEntry[]
  companyId: string
}

export function ExportModal({ open, onOpenChange, entries, companyId }: ExportModalProps) {
  const [format, setFormat] = useState<ExportFormat>('excel')
  const [selectedColumns, setSelectedColumns] = useState<Set<string>>(new Set(DEFAULT_SELECTED))
  const [dateFormat, setDateFormat] = useState<'dd.mm.yyyy' | 'yyyy-mm-dd'>('dd.mm.yyyy')

  // Предэкспортная валидация для EnterpriseData
  const exportValidation = useMemo(() => {
    if (format !== 'enterprise-data') return null
    return validateForExport(entries)
  }, [format, entries])

  function toggleColumn(key: string) {
    setSelectedColumns((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function handleExport() {
    const columns = ALL_COLUMNS.filter((c) => selectedColumns.has(c.key)).map((c) => c.key)
    const options = { columns, dateFormat }

    if (format === 'excel') {
      exportToExcel(entries, options)
    } else if (format === 'csv') {
      exportToCsv(entries, options)
    } else if (format === 'enterprise-data') {
      const entriesToExport = exportValidation?.entriesReady ?? entries
      const result = await exportToEnterpriseData(entriesToExport, companyId, options)
      toast.success(`EnterpriseData: экспортировано ${result.documentsExported} документов`)
    } else {
      exportTo1C(entries, options)
    }

    logEvent({ companyId, action: 'exported', details: `${format}: ${entries.length} записей` })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Экспорт данных ({entries.length} записей)</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Format */}
          <div className="space-y-1.5">
            <Label>Формат</Label>
            <Select value={format} onValueChange={(v) => setFormat(v as ExportFormat)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="excel">Excel (.xlsx)</SelectItem>
                <SelectItem value="csv">CSV (.csv)</SelectItem>
                <SelectItem value="1c-xml">1С XML (CommerceML)</SelectItem>
                <SelectItem value="enterprise-data">EnterpriseData XML (для 1С:БП)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Date format */}
          <div className="space-y-1.5">
            <Label>Формат даты</Label>
            <Select value={dateFormat} onValueChange={(v) => setDateFormat(v as typeof dateFormat)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dd.mm.yyyy">ДД.ММ.ГГГГ</SelectItem>
                <SelectItem value="yyyy-mm-dd">ГГГГ-ММ-ДД</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* EnterpriseData: предэкспортная валидация */}
          {format === 'enterprise-data' && exportValidation && (
            <div className="space-y-2 p-3 rounded-lg border bg-muted/30">
              <div className="flex items-center justify-between text-sm">
                <span>Готово к экспорту:</span>
                <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                  <CheckCircle2 className="size-3 mr-1" />
                  {exportValidation.totalReady}
                </Badge>
              </div>
              {exportValidation.totalWithIssues > 0 && (
                <div className="flex items-center justify-between text-sm">
                  <span>С ошибками (пропущены):</span>
                  <Badge variant="destructive">
                    <AlertCircle className="size-3 mr-1" />
                    {exportValidation.totalWithIssues}
                  </Badge>
                </div>
              )}
              {exportValidation.issues.filter((i) => i.severity === 'error').length > 0 && (
                <div className="max-h-24 overflow-auto text-xs space-y-0.5 mt-1">
                  {exportValidation.issues
                    .filter((i) => i.severity === 'error')
                    .slice(0, 5)
                    .map((issue, i) => (
                      <p key={i} className="text-destructive">
                        {issue.entryTitle}: {issue.issue}
                      </p>
                    ))}
                  {exportValidation.issues.filter((i) => i.severity === 'error').length > 5 && (
                    <p className="text-muted-foreground">
                      ...ещё {exportValidation.issues.filter((i) => i.severity === 'error').length - 5}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Columns */}
          {format !== '1c-xml' && format !== 'enterprise-data' && (
            <div className="space-y-1.5">
              <Label>Колонки</Label>
              <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto p-2 border rounded-lg">
                {ALL_COLUMNS.map((col) => (
                  <label key={col.key} className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox
                      checked={selectedColumns.has(col.key)}
                      onCheckedChange={() => toggleColumn(col.key)}
                    />
                    {col.label}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button onClick={handleExport} disabled={
            (selectedColumns.size === 0 && format !== '1c-xml' && format !== 'enterprise-data') ||
            !!(format === 'enterprise-data' && exportValidation && !exportValidation.canExport)
          }>
            <Download className="size-4" />
            Экспорт
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
