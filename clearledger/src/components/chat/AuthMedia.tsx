/**
 * Отображение вложений чата, защищённых JWT. GET /api/files/{id} требует
 * заголовок Authorization, поэтому прямой адрес изображения не работает — грузим blob
 * через downloadBlob и показываем object URL. Кеш blob-URL — по пути файла.
 */
import { useEffect, useRef, useState } from 'react'
import { FileText, Film, Image as ImageIcon, ImageOff, Loader2, Play } from 'lucide-react'
import { downloadAttachment, humanSize, useAuthBlob } from '@/lib/authFiles'

/**
 * Картинка грузится, когда доезжает до экрана.
 *
 * Вложения качаются через `fetch` с токеном, и без этого сторожа открытие переписки
 * тянуло разом ВСЕ снимки ленты — включая те, что за сотню сообщений выше. Запас в
 * 400 px: к моменту, когда картинка появляется в поле зрения, она уже на месте.
 */
function useNearViewport<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  // Браузер без наблюдателя (старый Safari, тестовая среда) грузит сразу: лучше
  // лишний запрос, чем пустая лента.
  const [видно, показать] = useState(() => typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const el = ref.current
    if (!el || видно) return
    const ob = new IntersectionObserver((записи) => {
      if (записи.some((з) => з.isIntersecting)) { показать(true); ob.disconnect() }
    }, { rootMargin: '400px' })
    ob.observe(el)
    return () => ob.disconnect()
  }, [видно])
  return { ref, видно }
}

export function AuthImage({ path, alt, className, onClick }: {
  path: string; alt?: string; className?: string; onClick?: () => void
}) {
  const { ref, видно } = useNearViewport<HTMLDivElement>()
  const { url, error, loading } = useAuthBlob(видно ? path : null)
  if (!видно) {
    // Место под картинку занято сразу: иначе лента прыгает, когда снимки доезжают.
    return (
      <div ref={ref} className={`flex items-center justify-center rounded bg-muted ${className ?? ''}`} style={{ minHeight: 140 }}>
        <ImageIcon className="size-5 text-muted-foreground/60" />
      </div>
    )
  }
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

/**
 * Видео в ленте: сначала карточка, файл — по нажатию.
 *
 * Вложение закрыто JWT, поэтому ролик качается целиком через `fetch`, а не
 * подтягивается плеером по кусочкам. Раньше это начиналось само, у каждого видео в
 * переписке сразу: открытие чата с пятью роликами стоило сотни мегабайт, и всё это
 * время на их месте было пустое место. Теперь видно кадр, имя и вес — а качаем
 * только то, что человек решил посмотреть (МАГ, 13.09.2026).
 */
export function AuthVideo({ path, poster, name, size, className }: {
  path: string; poster?: string | null; name?: string | null
  size?: number | null; className?: string
}) {
  const [играть, включить] = useState(false)
  // Хук нельзя звать по условию, поэтому путь передаём пустым, пока не нажали:
  // `useAuthBlob(null)` ничего не качает.
  const { url, error, loading } = useAuthBlob(играть ? path : null)

  if (играть && url) {
    return <video controls autoPlay preload="metadata" className={`rounded ${className ?? ''}`} src={url} />
  }

  return (
    <button type="button" onClick={() => включить(true)} disabled={играть}
      title={играть ? 'Загружается…' : 'Показать видео'}
      className={`group relative block overflow-hidden rounded border border-border bg-black/80 text-left ${className ?? ''}`}>
      {poster
        ? <AuthImage path={poster} alt={name ?? 'Кадр видео'} className="block max-h-[220px] w-full object-cover" />
        : (
          // Кадра нет (видео отправлено до 13.09.2026 или браузер его не отдал) —
          // тогда карточка сама объясняет, что здесь: пустой прямоугольник читался
          // как поломка.
          <div className="flex h-[120px] w-full items-center justify-center bg-muted">
            <Film className="size-7 text-muted-foreground" />
          </div>
        )}
      <span className="absolute inset-0 flex items-center justify-center">
        <span className="flex size-11 items-center justify-center rounded-full bg-black/55 backdrop-blur-sm transition group-hover:bg-black/70">
          {играть && loading
            ? <Loader2 className="size-5 animate-spin text-white" />
            : <Play className="size-5 translate-x-[1px] fill-white text-white" />}
        </span>
      </span>
      <span className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-gradient-to-t from-black/75 to-transparent px-2 pb-1 pt-4 text-[11px] text-white/90">
        <span className="min-w-0 flex-1 truncate">{name || 'Видео'}</span>
        {size ? <span className="shrink-0 tabular-nums">{humanSize(size)}</span> : null}
      </span>
      {error && (
        <span className="absolute inset-x-0 top-0 bg-destructive/90 px-2 py-0.5 text-[11px] text-white">
          Не удалось загрузить
        </span>
      )}
    </button>
  )
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
