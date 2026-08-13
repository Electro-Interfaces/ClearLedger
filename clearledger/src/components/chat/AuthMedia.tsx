/**
 * Отображение вложений чата, защищённых JWT. GET /api/files/{id} требует
 * заголовок Authorization, поэтому <img src> напрямую не работает — грузим blob
 * через downloadBlob и показываем object URL. Кеш blob-URL — по пути файла.
 */
import { useEffect, useState } from 'react'
import { FileText, ImageOff, Loader2 } from 'lucide-react'
import { downloadBlob } from '@/services/apiClient'

const blobCache = new Map<string, string>()

function useBlobUrl(path: string | null): { url: string | null; error: boolean; loading: boolean } {
  const [url, setUrl] = useState<string | null>(() => (path ? blobCache.get(path) ?? null : null))
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!path) { setUrl(null); return }
    const cached = blobCache.get(path)
    if (cached) { setUrl(cached); setError(false); return }
    let alive = true
    setLoading(true); setError(false)
    downloadBlob(path)
      .then((blob) => {
        if (!alive) return
        const objUrl = URL.createObjectURL(blob)
        blobCache.set(path, objUrl)
        setUrl(objUrl)
      })
      .catch(() => { if (alive) setError(true) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path])

  return { url, error, loading }
}

export function AuthImage({ path, alt, className, onClick }: {
  path: string; alt?: string; className?: string; onClick?: () => void
}) {
  const { url, error, loading } = useBlobUrl(path)
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
  const { url, error } = useBlobUrl(path)
  if (error || !url) {
    return (
      <div className={`flex items-center justify-center rounded bg-muted text-muted-foreground ${className ?? ''}`} style={{ minHeight: 80 }}>
        <ImageOff className="size-5" />
      </div>
    )
  }
  return <video controls preload="metadata" className={className} src={url} />
}

/** Разрешить blob-URL по пути (для Lightbox/скачивания). Возвращает null пока грузится. */
export function useAuthBlobUrl(path: string | null): string | null {
  return useBlobUrl(path).url
}

/** Скачать защищённый файл по клику (тянет blob с JWT, сохраняет под именем). */
export async function downloadAttachment(path: string, name?: string): Promise<void> {
  const cached = blobCache.get(path)
  const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
  if (!cached) blobCache.set(path, objUrl)
  const a = document.createElement('a')
  a.href = objUrl
  a.download = name || 'файл'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/**
 * Размер вложения в человеческих единицах: килобайты у документа, мегабайты у
 * архива. Раньше всё делилось на 1024 и округлялось до целого — файл на 900 байт
 * показывался как «1 КБ», а архив на 40 МБ как «40960 КБ».
 */
export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  const mb = bytes / (1024 * 1024)
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} МБ`
}

/** Чип файла-вложения (не изображение/видео): имя, размер, скачивание. */
export function AuthFileChip({ path, name, size, mine }: {
  path: string; name?: string | null; size?: number | null; mine?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => downloadAttachment(path, name || undefined)}
      className={`mt-1 flex items-center gap-1.5 text-xs hover:underline ${mine ? 'text-primary-foreground' : 'text-primary'}`}
    >
      <FileText className="size-4 shrink-0" />
      <span className="truncate max-w-[220px]">{name || 'Файл'}</span>
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
