import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  ChevronDown, ChevronUp, FileCode, Fingerprint,
  ScanText, Tag, Layers, Gauge,
} from 'lucide-react'
import { getExtract, getSource } from '@/services/sourceStore'
import { getCategoryById, getSubcategoryById, getDocumentTypeById } from '@/config/categories'
import { useCompany } from '@/contexts/CompanyContext'
import type { DataEntry, ExtractRecord, SourceRecord } from '@/types'

interface TechnicalInfoCardProps {
  entry: DataEntry
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/** Человекочитаемое имя для _-ключей метаданных */
const metaKeyLabels: Record<string, string> = {
  _fingerprint: 'SHA-256 хеш',
  _textHash: 'Хеш текста',
  _duplicateOf: 'Дубликат ID',
  _pdfPages: 'Страниц (PDF)',
  '_pdf.truncated': 'PDF усечён',
  '_pdf.noText': 'PDF без текста',
  '_pdf.ocrUsed': 'OCR использован',
  '_pdf.ocrPages': 'OCR страниц',
  '_pdf.ocrTruncated': 'OCR усечён',
  '_ocr.confidence': 'OCR точность',
  '_ocr.language': 'OCR языки',
  _ocrSource: 'Источник OCR',
  _ocrError: 'Ошибка OCR',
  _extractError: 'Ошибка извлечения',
  '_email.from': 'Email от',
  '_email.to': 'Email кому',
  '_email.subject': 'Email тема',
  '_email.messageId': 'Email Message-ID',
  '_email.date': 'Email дата',
  '_email.attachments': 'Вложений',
  '_email.parentEntryId': 'Родительский email',
  '_email.attachmentIndex': 'Индекс вложения',
  '_email.originalFilename': 'Имя файла',
  '_1c.guid': '1С GUID',
  '_1c.docType': '1С тип документа',
  '_1c.number': '1С номер',
  '_word.format': 'Формат Word',
  '_word.encoding': 'Кодировка',
  '_word.source': 'Исходный файл',
  _wordCount: 'Слов',
  _wordWarnings: 'Предупреждения',
  _excluded: 'Исключён',
}

export function TechnicalInfoCard({ entry }: TechnicalInfoCardProps) {
  const { company } = useCompany()
  const [extract, setExtract] = useState<ExtractRecord | null>(null)
  const [source, setSource] = useState<SourceRecord | null>(null)
  const [textOpen, setTextOpen] = useState(false)
  const [fieldsOpen, setFieldsOpen] = useState(false)
  const [metaOpen, setMetaOpen] = useState(false)

  useEffect(() => {
    if (!entry.sourceId) return
    getExtract(entry.sourceId).then((r) => setExtract(r ?? null))
    getSource(entry.sourceId).then((r) => setSource(r ?? null))
  }, [entry.sourceId])

  const techMeta = Object.entries(entry.metadata).filter(([k]) => k.startsWith('_'))
  const hasClassification = extract?.classification
  const hasFields = extract && extract.fields.length > 0
  const hasText = extract && extract.fullText.trim().length > 0

  if (!source && techMeta.length === 0 && !extract) return null

  const categoryName = getCategoryById(company.profileId, entry.categoryId)?.label
  const subcategoryName = getSubcategoryById(company.profileId, entry.categoryId, entry.subcategoryId)?.label
  const docTypeName = entry.docTypeId ? getDocumentTypeById(company.profileId, entry.docTypeId)?.label : undefined

  return (
    <Card>
      <CardHeader className="border-b pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          <FileCode className="size-4" />
          Техническая информация
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Источник файла */}
        {source && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
              <Layers className="size-3.5" />
              Источник
            </h4>
            <div className="space-y-1.5">
              <InfoRow label="Файл" value={source.fileName} />
              <InfoRow label="MIME" value={source.mimeType} />
              <InfoRow label="Размер" value={formatFileSize(source.size)} />
              <InfoRow label="SHA-256" value={source.fingerprint} mono />
            </div>
          </div>
        )}

        {/* Классификация */}
        {hasClassification && (
          <>
            <Separator />
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
                <Tag className="size-3.5" />
                Классификация
              </h4>
              <div className="space-y-1.5">
                <InfoRow label="Категория" value={categoryName ?? extract.classification.categoryId} />
                <InfoRow label="Подкатегория" value={subcategoryName ?? extract.classification.subcategoryId} />
                {docTypeName && <InfoRow label="Тип документа" value={docTypeName} />}
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Уверенность</span>
                  <ConfidenceBadge value={extract.classification.confidence} />
                </div>
              </div>
            </div>
          </>
        )}

        {/* Извлечённые поля */}
        {hasFields && (
          <>
            <Separator />
            <div className="space-y-2">
              <button
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground w-full hover:text-foreground transition-colors"
                onClick={() => setFieldsOpen(!fieldsOpen)}
              >
                <ScanText className="size-3.5" />
                <span className="flex-1 text-left">Извлечённые поля ({extract.fields.length})</span>
                {fieldsOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </button>
              {fieldsOpen && (
                <div className="space-y-1.5">
                  {extract.fields.map((f, i) => (
                    <div key={i} className="flex items-start justify-between text-sm gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-muted-foreground">{f.key}</span>
                        <span className="text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground">{f.source}</span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="font-medium text-right max-w-[200px] truncate">{f.value}</span>
                        <ConfidenceBadge value={f.confidence} small />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {/* Техническая метадата */}
        {techMeta.length > 0 && (
          <>
            <Separator />
            <div className="space-y-2">
              <button
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground w-full hover:text-foreground transition-colors"
                onClick={() => setMetaOpen(!metaOpen)}
              >
                <Fingerprint className="size-3.5" />
                <span className="flex-1 text-left">Метаданные pipeline ({techMeta.length})</span>
                {metaOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </button>
              {metaOpen && (
                <div className="space-y-1.5">
                  {techMeta.map(([key, value]) => (
                    <InfoRow
                      key={key}
                      label={metaKeyLabels[key] ?? key}
                      value={value}
                      mono={key === '_fingerprint' || key === '_textHash' || key === '_email.messageId' || key === '_1c.guid'}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {/* Извлечённый текст */}
        {hasText && (
          <>
            <Separator />
            <div className="space-y-2">
              <button
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground w-full hover:text-foreground transition-colors"
                onClick={() => setTextOpen(!textOpen)}
              >
                <Gauge className="size-3.5" />
                <span className="flex-1 text-left">
                  Извлечённый текст ({extract.fullText.length.toLocaleString()} симв.)
                </span>
                {textOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </button>
              {textOpen && (
                <pre className="text-xs bg-muted/50 rounded-lg p-3 max-h-[300px] overflow-auto whitespace-pre-wrap break-words font-mono">
                  {extract.fullText.slice(0, 5000)}
                  {extract.fullText.length > 5000 && (
                    <span className="text-muted-foreground">
                      {'\n\n'}... ещё {(extract.fullText.length - 5000).toLocaleString()} символов
                    </span>
                  )}
                </pre>
              )}
            </div>
          </>
        )}

      </CardContent>
    </Card>
  )
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between text-sm gap-2">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className={`font-medium text-right max-w-[60%] break-all ${mono ? 'font-mono text-xs' : ''}`}>
        {value}
      </span>
    </div>
  )
}

function ConfidenceBadge({ value, small }: { value: number; small?: boolean }) {
  const color = value >= 80
    ? 'bg-green-500/10 text-green-400 border-green-500/30'
    : value >= 50
      ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30'
      : 'bg-red-500/10 text-red-400 border-red-500/30'

  return (
    <span className={`px-1.5 py-0.5 rounded-full border ${color} ${small ? 'text-[10px]' : 'text-xs'}`}>
      {value}%
    </span>
  )
}
