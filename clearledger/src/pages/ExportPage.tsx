/**
 * ExportPage — страница /export.
 *
 * Таблица verified-записей + валидация + формат + история экспортов.
 */

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getEntries } from '@/services/dataEntryService'
import { validateForExport } from '@/services/exportValidationService'
import { exportToExcel, exportToCsv, exportTo1C, exportToEnterpriseData } from '@/services/exportService'
import { useAuditEvents } from '@/hooks/useAudit'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { StatusBadge } from '@/components/data/StatusBadge'
import { formatDateTime } from '@/lib/formatDate'
import { Download, AlertTriangle, CheckCircle2, History } from 'lucide-react'
import { toast } from 'sonner'

type ExportFormat = 'enterprise' | 'excel' | 'csv' | '1c'

const FORMAT_LABELS: Record<ExportFormat, string> = {
  enterprise: 'EnterpriseData (XML)',
  excel: 'Excel',
  csv: 'CSV',
  '1c': '1С (XML)',
}

export function ExportPage() {
  const { companyId } = useCompany()
  const [format, setFormat] = useState<ExportFormat>('enterprise')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [isExporting, setIsExporting] = useState(false)

  const { data: allEntries = [] } = useQuery({
    queryKey: ['entries', companyId],
    queryFn: () => getEntries(companyId),
  })

  // Фильтруем: verified/transferred, не архивные, не исключённые
  const exportableEntries = useMemo(
    () => allEntries.filter((e) =>
      (e.status === 'verified' || e.status === 'transferred') &&
      e.metadata._excluded !== 'true',
    ),
    [allEntries],
  )

  const validation = useMemo(
    () => validateForExport(exportableEntries),
    [exportableEntries],
  )

  // История экспортов (из аудит-лога)
  const { data: auditEvents = [] } = useAuditEvents({ action: 'exported' })
  const exportHistory = useMemo(
    () => auditEvents
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
      .slice(0, 10),
    [auditEvents],
  )

  function toggleAll() {
    if (selected.size === validation.entriesReady.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(validation.entriesReady.map((e) => e.id)))
    }
  }

  function toggleEntry(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleExport() {
    const entries = exportableEntries.filter((e) => selected.has(e.id))
    if (entries.length === 0) {
      toast.error('Нет выбранных записей')
      return
    }

    setIsExporting(true)
    try {
      switch (format) {
        case 'enterprise':
          await exportToEnterpriseData(entries, companyId)
          break
        case 'excel':
          exportToExcel(entries)
          break
        case 'csv':
          exportToCsv(entries)
          break
        case '1c':
          exportTo1C(entries)
          break
      }
      toast.success(`Экспорт ${entries.length} записей завершён`)
    } catch (err) {
      toast.error('Ошибка экспорта')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Экспорт данных</h1>

      {/* Формат + статистика */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Формат:</span>
              <Select value={format} onValueChange={(v) => setFormat(v as ExportFormat)}>
                <SelectTrigger className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.entries(FORMAT_LABELS) as [ExportFormat, string][]).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-3 text-sm">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="size-4 text-green-500" />
                <span>Готово: <strong>{validation.totalReady}</strong></span>
              </div>
              <div className="flex items-center gap-1.5">
                <AlertTriangle className="size-4 text-yellow-500" />
                <span>С ошибками: <strong>{validation.totalWithIssues}</strong></span>
              </div>
            </div>

            <Button
              className="ml-auto"
              onClick={handleExport}
              disabled={isExporting || selected.size === 0}
            >
              <Download className="size-4" />
              Экспортировать ({selected.size})
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Таблица записей */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Записи для экспорта</CardTitle>
        </CardHeader>
        <CardContent>
          {exportableEntries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Нет верифицированных записей для экспорта
            </p>
          ) : (
            <ScrollArea className="max-h-[50vh]">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 pr-2 w-8">
                      <Checkbox
                        checked={selected.size === validation.entriesReady.length && validation.entriesReady.length > 0}
                        onCheckedChange={toggleAll}
                      />
                    </th>
                    <th className="pb-2 pr-2">Документ</th>
                    <th className="pb-2 pr-2 w-24">Статус</th>
                    <th className="pb-2 w-32 text-right">Проблемы</th>
                  </tr>
                </thead>
                <tbody>
                  {exportableEntries.map((entry) => {
                    const entryIssues = validation.issues.filter((i) => i.entryId === entry.id)
                    const hasErrors = entryIssues.some((i) => i.severity === 'error')
                    return (
                      <tr key={entry.id} className="border-b last:border-0 hover:bg-muted/50">
                        <td className="py-2 pr-2">
                          <Checkbox
                            checked={selected.has(entry.id)}
                            onCheckedChange={() => toggleEntry(entry.id)}
                            disabled={hasErrors}
                          />
                        </td>
                        <td className="py-2 pr-2">
                          <div className="font-medium truncate max-w-xs">{entry.title}</div>
                          {entry.metadata.counterparty && (
                            <div className="text-xs text-muted-foreground truncate">
                              {entry.metadata.counterparty}
                            </div>
                          )}
                        </td>
                        <td className="py-2 pr-2">
                          <StatusBadge status={entry.status} />
                        </td>
                        <td className="py-2 text-right">
                          {entryIssues.length > 0 ? (
                            <div className="flex flex-wrap justify-end gap-1">
                              {entryIssues.map((issue, i) => (
                                <Badge
                                  key={i}
                                  variant={issue.severity === 'error' ? 'destructive' : 'outline'}
                                  className="text-[10px] px-1.5"
                                >
                                  {issue.issue}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <Badge variant="outline" className="text-[10px] px-1.5 text-green-600 border-green-600/30">
                              OK
                            </Badge>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      {/* История экспортов */}
      {exportHistory.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <History className="size-4" />
              История экспортов
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {exportHistory.map((event) => (
                <div key={event.id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">{formatDateTime(event.timestamp)}</span>
                    <span className="font-medium">{event.details || 'Экспорт'}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{event.userName}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
