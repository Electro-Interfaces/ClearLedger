/**
 * Диалог импорта справочников из 1С.
 */

import { useState, useCallback } from 'react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useQueryClient } from '@tanstack/react-query'
import { importReferences, readFileAsText, detectImportFormat, type ImportResult } from '@/services/referenceImportService'
import { toast } from 'sonner'
import { useDropzone } from 'react-dropzone'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImportDialog({ open, onOpenChange }: ImportDialogProps) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<string>('')
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)

  const onDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0) return
    const f = accepted[0]
    setFile(f)
    setResult(null)
    try {
      const text = await readFileAsText(f)
      const fmt = detectImportFormat(text)
      setFormat(fmt === 'enterprise-data-xml' ? 'EnterpriseData XML' : fmt === 'json' ? 'JSON' : 'Неизвестный')
    } catch {
      setFormat('Ошибка чтения')
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/xml': ['.xml'],
      'text/xml': ['.xml'],
      'application/json': ['.json'],
    },
    maxFiles: 1,
    multiple: false,
  })

  const handleImport = async () => {
    if (!file) return
    setImporting(true)
    try {
      const text = await readFileAsText(file)
      const res = await importReferences(companyId, text)
      setResult(res)
      qc.invalidateQueries({ queryKey: ['references', companyId] })

      const total = res.counterparties.added + res.organizations.added + res.nomenclature.added + res.contracts.added
      if (total > 0) {
        toast.success(`Импорт завершён: ${total} новых записей`)
      } else if (res.errors.length > 0) {
        toast.warning('Импорт завершён с ошибками')
      } else {
        toast.info('Все записи уже есть в справочниках')
      }
    } catch (err) {
      toast.error(`Ошибка импорта: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setImporting(false)
    }
  }

  const handleClose = () => {
    setFile(null)
    setFormat('')
    setResult(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Импорт справочников из 1С</DialogTitle>
          <DialogDescription>
            Загрузите файл выгрузки из 1С:Бухгалтерия (EnterpriseData XML или JSON).
            Существующие записи будут обновлены, новые — добавлены.
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
              {file ? (
                <div className="flex items-center justify-center gap-2">
                  <FileText className="size-5 text-primary" />
                  <span className="font-medium">{file.name}</span>
                  <Badge variant="outline">{format}</Badge>
                </div>
              ) : (
                <div className="space-y-2">
                  <Upload className="size-8 mx-auto text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    Перетащите файл или нажмите для выбора
                  </p>
                  <p className="text-xs text-muted-foreground">
                    .xml (EnterpriseData) или .json
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <ResultRow label="Контрагенты" result={result.counterparties} />
            <ResultRow label="Организации" result={result.organizations} />
            <ResultRow label="Номенклатура" result={result.nomenclature} />
            <ResultRow label="Договоры" result={result.contracts} />
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
            <Button onClick={handleImport} disabled={!file || importing || format === 'Неизвестный'}>
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
