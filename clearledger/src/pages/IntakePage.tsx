/**
 * Страница загрузки файлов и документов.
 * MVP: drag-drop зона + список загруженных.
 * Полный pipeline (detect → extract → classify) будет восстановлен из master.
 */

import { useState, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Upload, FileText, Image, FileSpreadsheet, File, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { nanoid } from 'nanoid'

interface LoadedFile {
  id: string
  name: string
  size: number
  type: string
  status: 'loaded' | 'processing' | 'classified'
  loadedAt: string
}

const FILE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  'application/pdf': FileText,
  'image/': Image,
  'application/vnd.openxmlformats': FileSpreadsheet,
  'application/vnd.ms-excel': FileSpreadsheet,
  'text/csv': FileSpreadsheet,
}

function getFileIcon(mimeType: string) {
  for (const [key, Icon] of Object.entries(FILE_ICONS)) {
    if (mimeType.startsWith(key)) return Icon
  }
  return File
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

export function IntakePage() {
  const [files, setFiles] = useState<LoadedFile[]>([])
  const [dragging, setDragging] = useState(false)

  const handleFiles = useCallback((fileList: FileList) => {
    const newFiles: LoadedFile[] = Array.from(fileList).map((f) => ({
      id: nanoid(8),
      name: f.name,
      size: f.size,
      type: f.type,
      status: 'loaded' as const,
      loadedAt: new Date().toISOString(),
    }))
    setFiles((prev) => [...newFiles, ...prev])
    toast.success(`Загружено ${newFiles.length} файл(ов)`)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)
    }
  }, [handleFiles])

  const handleRemove = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Загрузка файлов и документов</h1>
        <p className="text-sm text-muted-foreground">
          Перетащите файлы или выберите для загрузки. PDF, Excel, изображения, XML, Email.
        </p>
      </div>

      {/* Drop zone */}
      <Card
        className={`border-2 border-dashed transition-colors cursor-pointer ${
          dragging ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-primary/50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.multiple = true
          input.accept = '.pdf,.xlsx,.xls,.csv,.xml,.jpg,.jpeg,.png,.tiff,.eml,.txt,.json,.doc,.docx'
          input.onchange = () => { if (input.files) handleFiles(input.files) }
          input.click()
        }}
      >
        <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
          <Upload className={`h-10 w-10 ${dragging ? 'text-primary' : 'text-muted-foreground/40'}`} />
          <div className="text-center">
            <p className="text-sm font-medium">
              {dragging ? 'Отпустите файлы' : 'Перетащите файлы сюда'}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              или нажмите для выбора · PDF, Excel, CSV, XML, фото, Email · до 50 МБ
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Loaded files */}
      {files.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Загруженные ({files.length})</CardTitle>
              <Button variant="ghost" size="sm" className="text-xs text-muted-foreground"
                onClick={() => { setFiles([]); toast.info('Список очищен') }}>
                Очистить
              </Button>
            </div>
            <CardDescription className="text-xs">
              Полная обработка (классификация, извлечение данных) — в следующей версии
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-border/30">
              {files.map((f) => {
                const IconComp = getFileIcon(f.type)
                return (
                  <div key={f.id} className="flex items-center gap-3 py-2.5">
                    <IconComp className="h-5 w-5 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{f.name}</p>
                      <p className="text-[10px] text-muted-foreground">{formatSize(f.size)}</p>
                    </div>
                    <Badge variant="outline" className="text-[9px] shrink-0">
                      {f.status === 'loaded' ? 'Загружен' : f.status === 'processing' ? 'Обработка...' : 'Распознан'}
                    </Badge>
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => handleRemove(f.id)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default IntakePage
