/**
 * RegionCapture — встроенный захват области экрана для отправки в чат.
 *
 * Кнопка «камера» в композере → затемнение поверх приложения → пользователь
 * тянет рамку прямо по интерфейсу → выбранная область рендерится html2canvas в
 * PNG и прикрепляется. Без переключения в системные «ножницы».
 *
 * Оговорка по точности: это ре-рендер DOM, а не пиксельный снимок ОС — внешние
 * тайлы карт (CORS) и часть canvas-графики могут отрисоваться неточно. Быстрый
 * путь для интерфейсных элементов (таблицы, панели, формы, SVG-графики).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'

interface Rect { x: number; y: number; w: number; h: number }

function stamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
}

export function RegionCapture({ onCapture, onCancel }: {
  onCapture: (file: File) => void
  onCancel: () => void
}) {
  const [rect, setRect] = useState<Rect | null>(null)
  const [busy, setBusy] = useState(false)
  const startRef = useRef<{ x: number; y: number } | null>(null)
  const busyRef = useRef(false)

  const finish = useCallback(async (r: Rect) => {
    if (busyRef.current) return
    if (r.w < 8 || r.h < 8) { onCancel(); return }
    busyRef.current = true
    setBusy(true)
    try {
      // html2canvas-pro — форк с поддержкой oklch()/lab()/color() (Tailwind 4).
      // Оригинальный html2canvas 1.4.1 падает на современных цветовых функциях.
      const html2canvas = (await import('html2canvas-pro')).default
      const scale = Math.min(2, window.devicePixelRatio || 1)
      const bg = getComputedStyle(document.body).backgroundColor || null
      const full = await html2canvas(document.body, {
        backgroundColor: bg,
        scale,
        useCORS: true,
        logging: false,
        // не захватывать сам оверлей выделения и любые помеченные элементы
        ignoreElements: (el) => (el as HTMLElement).dataset?.captureIgnore === '1',
        scrollX: 0,
        scrollY: 0,
        windowWidth: document.documentElement.clientWidth,
        windowHeight: document.documentElement.clientHeight,
      })
      const crop = document.createElement('canvas')
      crop.width = Math.max(1, Math.round(r.w * scale))
      crop.height = Math.max(1, Math.round(r.h * scale))
      const ctx = crop.getContext('2d')
      if (!ctx) throw new Error('canvas 2d недоступен')
      ctx.drawImage(full, Math.round(r.x * scale), Math.round(r.y * scale),
        Math.round(r.w * scale), Math.round(r.h * scale), 0, 0, crop.width, crop.height)
      const blob = await new Promise<Blob | null>((res) => crop.toBlob(res, 'image/png'))
      if (blob) onCapture(new File([blob], `Снимок-${stamp()}.png`, { type: 'image/png' }))
      else onCancel()
    } catch {
      toast.error('Не удалось сделать снимок области')
      onCancel()
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }, [onCapture, onCancel])

  useEffect(() => {
    // pointer-события покрывают мышь, тач и перо (работает на тач-планшетах)
    const onDown = (e: PointerEvent) => {
      if (busyRef.current) return
      startRef.current = { x: e.clientX, y: e.clientY }
      setRect({ x: e.clientX, y: e.clientY, w: 0, h: 0 })
    }
    const onMove = (e: PointerEvent) => {
      const s = startRef.current
      if (!s || busyRef.current) return
      setRect({
        x: Math.min(s.x, e.clientX), y: Math.min(s.y, e.clientY),
        w: Math.abs(e.clientX - s.x), h: Math.abs(e.clientY - s.y),
      })
    }
    const onUp = (e: PointerEvent) => {
      const s = startRef.current
      startRef.current = null
      if (!s || busyRef.current) return
      finish({
        x: Math.min(s.x, e.clientX), y: Math.min(s.y, e.clientY),
        w: Math.abs(e.clientX - s.x), h: Math.abs(e.clientY - s.y),
      })
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busyRef.current) onCancel() }
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('keydown', onKey)
    }
  }, [finish, onCancel])

  return createPortal(
    <div data-capture-ignore="1" className="fixed inset-0 z-[200] cursor-crosshair select-none touch-none">
      {/* затемнение */}
      <div className="absolute inset-0 bg-black/40" />
      {/* окно выделения (прозрачное, с рамкой) */}
      {rect && rect.w > 0 && rect.h > 0 && (
        <div className="absolute border-2 border-primary bg-primary/5 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]"
          style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}>
          <span className="absolute -top-6 left-0 whitespace-nowrap rounded bg-primary px-1.5 py-0.5 text-[11px] font-medium text-primary-foreground">
            {Math.round(rect.w)} × {Math.round(rect.h)}
          </span>
        </div>
      )}
      {/* подсказка */}
      {!rect && (
        <div className="absolute left-1/2 top-6 -translate-x-1/2 rounded-full bg-black/70 px-4 py-2 text-sm text-white">
          Выделите область для отправки в чат · Esc — отмена
        </div>
      )}
      {busy && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-2 rounded-lg bg-black/75 px-4 py-2.5 text-sm text-white">
            <Loader2 className="size-4 animate-spin" /> Готовим снимок…
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}
