/**
 * Компонент импорта документов 1С из EnterpriseData XML.
 * Drag-n-drop, preview, результат.
 */

import { useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Upload, FileText, CheckCircle, AlertCircle } from 'lucide-react'
import { XMLParser } from 'fast-xml-parser'
import type { AccountingDoc, AccountingDocType, AccountingDocLine } from '@/types'
import { useImportAccountingDocs } from '@/hooks/useAccountingDocs'
import { nanoid } from 'nanoid'

// Маппинг типов документов 1С → AccountingDocType
const DOC_TYPE_MAP: Record<string, AccountingDocType> = {
  'ПоступлениеТоваровУслуг': 'receipt',
  'Документ.ПоступлениеТоваровУслуг': 'receipt',
  'СчётФактураПолученный': 'invoice-received',
  'СчетФактураПолученный': 'invoice-received',
  'Документ.СчетФактураПолученный': 'invoice-received',
  'ПлатёжноеПоручение': 'payment-out',
  'ПлатежноеПоручение': 'payment-out',
  'Документ.ПлатежноеПоручениеИсходящее': 'payment-out',
  'ПоступлениеНаРасчётныйСчёт': 'payment-in',
  'ПоступлениеНаРасчетныйСчет': 'payment-in',
  'Документ.ПоступлениеНаРасчетныйСчет': 'payment-in',
  'РеализацияТоваровУслуг': 'sales',
  'Документ.РеализацияТоваровУслуг': 'sales',
  'СчётФактураВыданный': 'invoice-issued',
  'СчетФактураВыданный': 'invoice-issued',
  'Документ.СчетФактураВыданный': 'invoice-issued',
  'АктСверкиВзаиморасчётов': 'reconciliation',
  'АктСверкиВзаиморасчетов': 'reconciliation',
  'Документ.АктСверкиВзаиморасчетов': 'reconciliation',
}

function str(val: unknown): string {
  if (val === null || val === undefined) return ''
  return String(val).trim()
}

function ensureArray<T>(val: T | T[] | undefined): T[] {
  if (!val) return []
  return Array.isArray(val) ? val : [val]
}

type ParsedDoc = Omit<AccountingDoc, 'id' | 'companyId' | 'matchStatus' | 'createdAt' | 'updatedAt'>

function parseDocsFromXml(content: string): { docs: ParsedDoc[]; errors: string[] } {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    isArray: (name) => Object.keys(DOC_TYPE_MAP).some((t) => name.includes(t)) || name === 'Строка' || name === 'Товар',
  })

  const parsed = parser.parse(content)
  const root = parsed['EnterpriseData'] || parsed['ОбменДанными'] || parsed['Body'] || parsed
  const docs: ParsedDoc[] = []
  const errors: string[] = []

  for (const [xmlType, accType] of Object.entries(DOC_TYPE_MAP)) {
    const nodes = ensureArray(root[xmlType])
    for (const node of nodes) {
      try {
        const lines: AccountingDocLine[] = []
        const lineNodes = ensureArray(node['Товары']?.['Строка'] ?? node['Товары'] ?? node['Строки']?.['Строка'] ?? node['Строки'])
        for (const ln of lineNodes) {
          if (typeof ln !== 'object' || !ln) continue
          lines.push({
            nomenclatureCode: str(ln['Номенклатура']?.['Код'] || ln['НоменклатураКод'] || ln['Код']),
            nomenclatureName: str(ln['Номенклатура']?.['Наименование'] || ln['НоменклатураНаименование'] || ln['Наименование'] || 'Без названия'),
            quantity: parseFloat(str(ln['Количество'])) || 0,
            price: parseFloat(str(ln['Цена'])) || 0,
            amount: parseFloat(str(ln['Сумма'])) || 0,
            vatRate: parseFloat(str(ln['СтавкаНДС'] || ln['НДС'] || '20')) || 20,
            vatAmount: ln['СуммаНДС'] ? parseFloat(str(ln['СуммаНДС'])) : undefined,
          })
        }

        docs.push({
          externalId: str(node['Ссылка'] || node['Ref'] || node['@_Ref'] || node['GUID']) || nanoid(),
          docType: accType,
          number: str(node['Номер'] || node['Number']) || 'б/н',
          date: str(node['Дата'] || node['Date']),
          counterpartyName: str(node['Контрагент']?.['Наименование'] || node['Контрагент'] || node['КонтрагентНаименование'] || ''),
          counterpartyInn: str(node['Контрагент']?.['ИНН'] || node['КонтрагентИНН']) || undefined,
          organizationName: str(node['Организация']?.['Наименование'] || node['Организация'] || node['ОрганизацияНаименование']) || undefined,
          amount: parseFloat(str(node['СуммаДокумента'] || node['Сумма'])) || 0,
          vatAmount: node['СуммаНДС'] ? parseFloat(str(node['СуммаНДС'])) : undefined,
          status1c: str(node['Проведен'] || node['Проведён']) === 'true' || !node['Проведен'] ? 'Проведён' : 'Не проведён',
          lines,
          warehouseCode: str(node['Склад']?.['Код'] || node['СкладКод']) || undefined,
        })
      } catch (e) {
        errors.push(`Ошибка парсинга документа ${xmlType}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }

  return { docs, errors }
}

interface Props {
  onImported?: () => void
}

export function ImportAccountingDocs({ onImported }: Props) {
  const [dragActive, setDragActive] = useState(false)
  const [parsedDocs, setParsedDocs] = useState<ParsedDoc[]>([])
  const [parseErrors, setParseErrors] = useState<string[]>([])
  const [fileName, setFileName] = useState('')
  const importMut = useImportAccountingDocs()

  const handleFile = useCallback(async (file: File) => {
    setFileName(file.name)
    const text = await file.text()
    const { docs, errors } = parseDocsFromXml(text)
    setParsedDocs(docs)
    setParseErrors(errors)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const handleImport = async () => {
    if (parsedDocs.length === 0) return
    await importMut.mutateAsync(parsedDocs)
    onImported?.()
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <Card
        className={`border-2 border-dashed transition-colors cursor-pointer ${
          dragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.accept = '.xml'
          input.onchange = (e) => {
            const file = (e.target as HTMLInputElement).files?.[0]
            if (file) handleFile(file)
          }
          input.click()
        }}
      >
        <CardContent className="flex flex-col items-center justify-center py-8 gap-2">
          <Upload className="size-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Перетащите XML-файл выгрузки из 1С или нажмите для выбора
          </p>
          <p className="text-xs text-muted-foreground">
            Формат: EnterpriseData XML (документы)
          </p>
        </CardContent>
      </Card>

      {/* Preview */}
      {fileName && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <FileText className="size-4" />
            <span className="font-medium text-sm">{fileName}</span>
            <Badge variant="outline">{parsedDocs.length} документов</Badge>
          </div>

          {parseErrors.length > 0 && (
            <div className="rounded-md bg-destructive/10 p-3">
              {parseErrors.map((err, i) => (
                <div key={i} className="flex gap-2 text-sm text-destructive">
                  <AlertCircle className="size-4 shrink-0 mt-0.5" />
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}

          {parsedDocs.length > 0 && (
            <>
              {/* Stats by type */}
              <div className="flex flex-wrap gap-2">
                {Object.entries(
                  parsedDocs.reduce<Record<string, number>>((acc, d) => {
                    acc[d.docType] = (acc[d.docType] || 0) + 1
                    return acc
                  }, {}),
                ).map(([type, count]) => (
                  <Badge key={type} variant="secondary">
                    {type}: {count}
                  </Badge>
                ))}
              </div>

              {/* Import button */}
              <Button
                onClick={handleImport}
                disabled={importMut.isPending}
                className="w-full"
              >
                {importMut.isPending ? 'Импорт...' : `Импортировать ${parsedDocs.length} документов`}
              </Button>

              {importMut.isSuccess && importMut.data && (
                <div className="flex items-center gap-2 text-sm text-green-600">
                  <CheckCircle className="size-4" />
                  <span>
                    Импорт завершён: создано {importMut.data.created}, обновлено {importMut.data.updated}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
