import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ZoomIn, ZoomOut, RotateCw, FileText, Image, FileSpreadsheet, File } from 'lucide-react'
import { useState, useEffect } from 'react'
import type { DataEntry } from '@/types'
import { getSourceBlobUrl, getExtract } from '@/services/sourceStore'

function getFileIcon(fileType?: string) {
  if (!fileType) return File
  if (fileType.startsWith('image/')) return Image
  if (fileType === 'application/pdf') return FileText
  if (fileType.includes('spreadsheet') || fileType.includes('csv') || fileType.includes('excel')) return FileSpreadsheet
  return File
}

function getFileLabel(fileType?: string) {
  if (!fileType) return 'Файл'
  if (fileType.startsWith('image/')) return 'Изображение'
  if (fileType === 'application/pdf') return 'PDF документ'
  if (fileType.includes('csv')) return 'CSV файл'
  if (fileType.includes('spreadsheet') || fileType.includes('excel')) return 'Excel таблица'
  return 'Документ'
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

interface DocumentPreviewProps {
  entry: DataEntry
}

export function DocumentPreview({ entry }: DocumentPreviewProps) {
  const [zoom, setZoom] = useState(100)
  const [rotation, setRotation] = useState(0)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [extractText, setExtractText] = useState<string | null>(null)

  // Загрузить blob через sourceId из IndexedDB
  useEffect(() => {
    let revoked = false
    if (entry.sourceId) {
      getSourceBlobUrl(entry.sourceId).then((url) => {
        if (!revoked && url) setBlobUrl(url)
      })
    }
    return () => {
      revoked = true
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.sourceId])

  // Загрузить извлечённый текст из IndexedDB
  useEffect(() => {
    let cancelled = false
    if (entry.sourceId) {
      getExtract(entry.sourceId).then((rec) => {
        if (!cancelled && rec?.fullText) setExtractText(rec.fullText)
      })
    }
    return () => { cancelled = true }
  }, [entry.sourceId])

  const previewUrl = blobUrl ?? entry.fileUrl
  const FileIcon = getFileIcon(entry.fileType)
  const label = getFileLabel(entry.fileType)
  const isImage = entry.fileType?.startsWith('image/')
  const isPdf = entry.fileType === 'application/pdf'
  return (
    <Card className="h-full">
      <CardHeader className="flex-row items-center justify-between border-b pb-4">
        <CardTitle className="text-base">Предпросмотр</CardTitle>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setZoom((z) => Math.max(25, z - 25))}
            title="Уменьшить"
          >
            <ZoomOut />
          </Button>
          <span className="text-xs text-muted-foreground w-10 text-center">{zoom}%</span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setZoom((z) => Math.min(200, z + 25))}
            title="Увеличить"
          >
            <ZoomIn />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setRotation((r) => (r + 90) % 360)}
            title="Повернуть"
          >
            <RotateCw />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="min-h-[300px]">
        {isImage && previewUrl ? (
          <div
            className="flex items-center justify-center w-full overflow-hidden"
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transition: 'transform 0.2s ease',
            }}
          >
            <img
              src={previewUrl}
              alt={entry.title}
              className="max-w-full max-h-[500px] object-contain rounded-lg"
            />
          </div>
        ) : isImage ? (
          <div
            className="flex items-center justify-center bg-muted/50 rounded-lg w-full h-[400px] border border-dashed border-muted-foreground/25"
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transition: 'transform 0.2s ease',
            }}
          >
            <div className="flex flex-col items-center gap-3 text-muted-foreground">
              <Image className="size-16 opacity-30" />
              <span className="text-sm">{entry.title}</span>
              {entry.fileSize && (
                <span className="text-xs">{formatFileSize(entry.fileSize)}</span>
              )}
            </div>
          </div>
        ) : isPdf && previewUrl ? (
          <div
            className="w-full h-[500px]"
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transition: 'transform 0.2s ease',
              transformOrigin: 'top center',
            }}
          >
            <iframe
              src={previewUrl}
              title={entry.title}
              className="w-full h-full rounded-lg border"
            />
          </div>
        ) : isPdf && extractText ? (
          <div className="w-full max-h-[70vh] overflow-y-auto">
            <pre className="text-sm text-foreground whitespace-pre-wrap break-words font-mono p-4 leading-relaxed">
              {extractText}
            </pre>
          </div>
        ) : isPdf ? (
          <div
            className="flex items-center justify-center bg-muted/50 rounded-lg w-full h-[400px] border border-dashed border-muted-foreground/25"
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transition: 'transform 0.2s ease',
            }}
          >
            <div className="flex flex-col items-center gap-3 text-muted-foreground">
              <FileText className="size-16 opacity-50" />
              <span className="text-sm font-medium">PDF</span>
              <span className="text-xs">{entry.title}</span>
              {entry.fileSize && (
                <span className="text-xs">{formatFileSize(entry.fileSize)}</span>
              )}
            </div>
          </div>
        ) : extractText ? (
          <div className="w-full max-h-[70vh] overflow-y-auto">
            <pre className="text-sm text-foreground whitespace-pre-wrap break-words font-mono p-4 leading-relaxed">
              {extractText}
            </pre>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-muted-foreground py-12">
            <FileIcon className="size-16 opacity-50" />
            <span className="text-sm font-medium">{label}</span>
            <span className="text-xs">{entry.title}</span>
            {entry.fileSize && (
              <span className="text-xs">{formatFileSize(entry.fileSize)}</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
