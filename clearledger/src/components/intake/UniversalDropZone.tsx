/**
 * UniversalDropZone — принимает любые файлы drag-n-drop или через диалог выбора.
 */

import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Image, Mail, Table2, Code } from 'lucide-react'

interface UniversalDropZoneProps {
  onFiles: (files: File[]) => void
  disabled?: boolean
}

const ACCEPTED_TYPES: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'image/*': ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
  'text/csv': ['.csv'],
  'application/xml': ['.xml'],
  'text/xml': ['.xml'],
  'message/rfc822': ['.eml'],
  'text/plain': ['.txt'],
  'application/json': ['.json'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/msword': ['.doc'],
}

const MAX_SIZE = 50 * 1024 * 1024 // 50 МБ

export function UniversalDropZone({ onFiles, disabled }: UniversalDropZoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) onFiles(accepted)
    },
    [onFiles],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: MAX_SIZE,
    disabled,
    multiple: true,
  })

  return (
    <div
      {...getRootProps()}
      className={`
        relative flex items-center justify-center gap-5 rounded-xl border-2 border-dashed px-6 py-5
        transition-all cursor-pointer
        ${isDragActive
          ? 'border-primary bg-primary/5 scale-[1.01]'
          : 'border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30'
        }
        ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
      `}
    >
      <input {...getInputProps()} />

      <div className={`rounded-full p-3 shrink-0 transition-colors ${isDragActive ? 'bg-primary/10' : 'bg-muted'}`}>
        <Upload className={`size-6 ${isDragActive ? 'text-primary' : 'text-muted-foreground'}`} />
      </div>

      <div className="min-w-0">
        <p className="font-medium">
          {isDragActive ? 'Отпустите файлы здесь' : 'Бросайте файлы сюда'}
          <span className="text-sm text-muted-foreground font-normal ml-2">
            или нажмите для выбора — до 50 МБ
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-2 mt-1.5">
          <FormatBadge icon={FileText} label="PDF" />
          <FormatBadge icon={Image} label="Фото" />
          <FormatBadge icon={Table2} label="Excel/CSV" />
          <FormatBadge icon={Mail} label="Email" />
          <FormatBadge icon={Code} label="XML/JSON" />
        </div>
      </div>
    </div>
  )
}

function FormatBadge({ icon: Icon, label }: { icon: typeof FileText; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
      <Icon className="size-3" />
      {label}
    </span>
  )
}
