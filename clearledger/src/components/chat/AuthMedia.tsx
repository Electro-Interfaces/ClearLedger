/**
 * Отображение вложений чата, защищённых JWT. GET /api/files/{id} требует
 * заголовок Authorization, поэтому прямой адрес изображения не работает — грузим blob
 * через downloadBlob и показываем object URL. Кеш blob-URL — по пути файла.
 */
import { FileText, ImageOff, Loader2 } from 'lucide-react'
import { downloadAttachment, humanSize, useAuthBlob } from '@/lib/authFiles'

export function AuthImage({ path, alt, className, onClick }: {
  path: string; alt?: string; className?: string; onClick?: () => void
}) {
  const { url, error, loading } = useAuthBlob(path)
  if (error) {
    return (
      <div className={`flex items-center justify-center rounded bg-muted text-muted-foreground ${className ?? ''}`} style={{ minHeight: 80 }}>
        <ImageOff className="size-5" />
      </div>
    )
  }
  if (!url || loading) {
    return (
      <div className={`flex items-center justify-center rounded bg-muted ${className ?? ''}`} style={{ minHeight: 80 }}>
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      </div>
    )
  }
  return <img src={url} alt={alt ?? ''} className={className} onClick={onClick} />
}

export function AuthVideo({ path, className }: { path: string; className?: string }) {
  const { url, error } = useAuthBlob(path)
  if (error || !url) {
    return (
      <div className={`flex items-center justify-center rounded bg-muted text-muted-foreground ${className ?? ''}`} style={{ minHeight: 80 }}>
        <ImageOff className="size-5" />
      </div>
    )
  }
  return <video controls preload="metadata" className={className} src={url} />
}

/** Чип файла-вложения (не изображение/видео): имя, размер, скачивание. */
export function AuthFileChip({ path, name, size, mine }: {
  path: string; name?: string | null; size?: number | null; mine?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => downloadAttachment(path, name || undefined)}
      className={`mb-4 mt-1 flex max-w-full min-w-0 items-center gap-1.5 text-xs hover:underline ${mine ? 'text-primary-foreground' : 'text-primary'}`}
    >
      <FileText className="size-4 shrink-0" />
      <span className="min-w-0 max-w-[220px] truncate">{name || 'Файл'}</span>
      {/* Размер не сжимаем и не приглушаем: на своём сообщении (насыщенная заливка)
          мелкий полупрозрачный текст сливался с фоном и читался как каша. */}
      {size ? (
        <span className="shrink-0 whitespace-nowrap tabular-nums opacity-90">
          · {humanSize(size)}
        </span>
      ) : null}
    </button>
  )
}
