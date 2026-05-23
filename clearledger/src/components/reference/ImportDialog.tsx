/**
 * Диалог импорта справочников и документов из 1С.
 * Поддерживает множественные JSON-файлы (выгрузка ClearLedger Export .epf).
 */

import { useState, useCallback } from 'react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, FolderOpen } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useQueryClient } from '@tanstack/react-query'
import {
  importReferences, readFileAsText, detectImportFormat,
  import1CExportFiles, type ImportResult, type FolderImportResult,
} from '@/services/referenceImportService'
import { toast } from 'sonner'
import { useDropzone } from 'react-dropzone'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImportDialog({ open, onOpenChange }: ImportDialogProps) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [files, setFiles] = useState<File[]>([])
  const [format, setFormat] = useState<string>('')
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<FolderImportResult | null>(null)

  const onDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0) return
    setFiles(accepted)
    setResult(null)

    if (accepted.length === 1) {
      try {
        const text = await readFileAsText(accepted[0])
        const fmt = detectImportFormat(text)
        setFormat(fmt === 'enterprise-data-xml' ? 'EnterpriseData XML' : fmt === 'json' ? 'JSON' : 'Неизвестный')
      } catch {
        setFormat('Ошибка чтения')
      }
    } else {
      setFormat(`${accepted.length} файлов JSON`)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/json': ['.json'],
      'application/xml': ['.xml'],
      'text/xml': ['.xml'],
      'text/plain': ['.json', '.xml'],
      'application/octet-stream': ['.json', '.xml'],
    },
    multiple: true,
    validator: (file) => {
      const ext = file.name.toLowerCase().split('.').pop()
      if (ext === 'json' || ext === 'xml') return null
      return { code: 'wrong-ext', message: 'Только .json и .xml файлы' }
    },
  })

  const handleImport = async () => {
    if (files.length === 0) return
    setImporting(true)
    try {
      let res: FolderImportResult

      if (files.length === 1) {
        const text = await readFileAsText(files[0])
        const fmt = detectImportFormat(text)
        if (fmt === 'json') {
          // Проверяем — это documents.json или справочники
          const data = JSON.parse(text)
          if (data.documents) {
            res = await import1CExportFiles(companyId, files)
          } else {
            const refRes = await importReferences(companyId, text)
            const emptyExtra = { documents: { total: 0, created: 0, updated: 0 }, balances: { total: 0, imported: 0 }, fixedAssets: { total: 0, added: 0 }, osv: { total: 0 }, journal: { total: 0 }, chartOfAccounts: { total: 0 }, accountingPolicy: { total: 0 }, filings: { total: 0 }, meta: null }
            res = { ...refRes, ...emptyExtra }
          }
        } else {
          const refRes = await importReferences(companyId, text)
          const emptyExtra = { documents: { total: 0, created: 0, updated: 0 }, balances: { total: 0, imported: 0 }, fixedAssets: { total: 0, added: 0 }, osv: { total: 0 }, journal: { total: 0 }, chartOfAccounts: { total: 0 }, accountingPolicy: { total: 0 }, filings: { total: 0 }, meta: null }
          res = { ...refRes, ...emptyExtra }
        }
      } else {
        res = await import1CExportFiles(companyId, files)
      }

      setResult(res)
      qc.invalidateQueries({ queryKey: ['references', companyId] })
      qc.invalidateQueries({ queryKey: ['accounting-docs', companyId] })

      const refTotal = res.counterparties.added + res.organizations.added +
        res.nomenclature.added + res.contracts.added
      const docTotal = res.documents.created + res.documents.updated
      const balTotal = res.balances.imported

      if (refTotal + docTotal + balTotal > 0) {
        const parts: string[] = []
        if (refTotal > 0) parts.push(`${refTotal} записей в справочники`)
        if (res.documents.created > 0) parts.push(`${res.documents.created} новых документов`)
        if (res.documents.updated > 0) parts.push(`${res.documents.updated} обновлено`)
        if (balTotal > 0) parts.push(`${balTotal} записей сальдо`)
        toast.success(`Импорт: ${parts.join(', ')}`)
      } else if (res.errors.length > 0) {
        toast.warning('Импорт завершён с ошибками')
      } else {
        toast.info('Все записи уже есть в системе')
      }
    } catch (err) {
      toast.error(`Ошибка импорта: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setImporting(false)
    }
  }

  const handleClose = () => {
    setFiles([])
    setFormat('')
    setResult(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Импорт из 1С</DialogTitle>
          <DialogDescription>
            Загрузите файлы выгрузки из 1С:Бухгалтерия — один файл (XML/JSON) или папку выгрузки ClearLedger Export
            (counterparties.json, documents.json и т.д.).
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <div className="space-y-4">
            <div
              {...getRootProps()}
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50'
              }`}
            >
              <input {...getInputProps()} />
              {files.length > 0 ? (
                <div className="space-y-1">
                  {files.length === 1 ? (
                    <div className="flex items-center justify-center gap-2">
                      <FileText className="size-5 text-primary" />
                      <span className="font-medium">{files[0].name}</span>
                      <Badge variant="outline">{format}</Badge>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <div className="flex items-center justify-center gap-2">
                        <FolderOpen className="size-5 text-primary" />
                        <span className="font-medium">{format}</span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {files.map(f => f.name).join(', ')}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <Upload className="size-8 mx-auto text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    Перетащите файлы или нажмите для выбора
                  </p>
                  <p className="text-xs text-muted-foreground">
                    .xml (EnterpriseData) или .json (выгрузка ClearLedger Export)
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {result.meta && (
              <div className="text-xs text-muted-foreground bg-muted rounded px-3 py-2">
                Выгрузка: {result.meta.source} · {result.meta.periodFrom} — {result.meta.periodTo}
              </div>
            )}
            <ResultRow label="Контрагенты" result={result.counterparties} />
            <ResultRow label="Организации" result={result.organizations} />
            <ResultRow label="Номенклатура" result={result.nomenclature} />
            <ResultRow label="Договоры" result={result.contracts} />
            <ResultRow label="Основные средства" result={result.fixedAssets} />
            <DocResultRow label="Документы" result={result.documents} />
            <BalanceResultRow label="Сальдо" result={result.balances} />
            <SnapshotResultRow label="ОСВ" total={result.osv.total} />
            <SnapshotResultRow label="Проводки" total={result.journal.total} />
            <SnapshotResultRow label="План счетов" total={result.chartOfAccounts.total} />
            <SnapshotResultRow label="Учётная политика" total={result.accountingPolicy.total} />
            <SnapshotResultRow label="Отчётность" total={result.filings.total} />
            {result.errors.length > 0 && (
              <div className="mt-2 space-y-1">
                <p className="text-sm font-medium text-destructive flex items-center gap-1">
                  <AlertCircle className="size-4" />
                  Ошибки ({result.errors.length})
                </p>
                <div className="max-h-24 overflow-auto text-xs text-muted-foreground space-y-0.5">
                  {result.errors.map((e, i) => (
                    <p key={i}>{e}</p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {result ? 'Закрыть' : 'Отмена'}
          </Button>
          {!result && (
            <Button onClick={handleImport} disabled={files.length === 0 || importing || format === 'Неизвестный'}>
              {importing && <Loader2 className="size-4 mr-2 animate-spin" />}
              Импортировать
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ResultRow({ label, result }: { label: string; result: { total: number; added: number } }) {
  if (result.total === 0) return null
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">Найдено: {result.total}</span>
        {result.added > 0 ? (
          <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
            <CheckCircle2 className="size-3 mr-1" />
            +{result.added} новых
          </Badge>
        ) : (
          <Badge variant="secondary">Все обновлены</Badge>
        )}
      </div>
    </div>
  )
}

function DocResultRow({ label, result }: { label: string; result: { total: number; created: number; updated: number } }) {
  if (result.total === 0) return null
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">Всего: {result.total}</span>
        {result.created > 0 && (
          <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
            <CheckCircle2 className="size-3 mr-1" />
            +{result.created}
          </Badge>
        )}
        {result.updated > 0 && (
          <Badge variant="secondary">{result.updated} обновл.</Badge>
        )}
      </div>
    </div>
  )
}

function BalanceResultRow({ label, result }: { label: string; result: { total: number; imported: number } }) {
  if (result.total === 0) return null
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">Записей: {result.total}</span>
        <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
          <CheckCircle2 className="size-3 mr-1" />
          Загружено
        </Badge>
      </div>
    </div>
  )
}

function SnapshotResultRow({ label, total }: { label: string; total: number }) {
  if (total === 0) return null
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">{total} записей</span>
        <Badge variant="secondary">
          <CheckCircle2 className="size-3 mr-1" />
          Сохранено
        </Badge>
      </div>
    </div>
  )
}
