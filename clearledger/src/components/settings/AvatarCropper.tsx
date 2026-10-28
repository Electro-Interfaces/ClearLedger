/**
 * Кадрирование фото профиля.
 *
 * Аватар показывается квадратом, а снимок с телефона — вертикальный
 * прямоугольник: `object-cover` обрезал его по центру вслепую, и у половины
 * людей в чате оказывался подбородок или потолок. Здесь человек сам решает,
 * что попадёт в круг: тянет снимок и меняет масштаб.
 *
 * Без библиотеки: нужен один квадрат и один ползунок, а пакет кадрирования —
 * это ещё одна зависимость, которую потом обновлять.
 */
import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/** Сторона готового снимка. Больше незачем: аватар нигде не крупнее 128 px. */
const СТОРОНА = 512
/** Сторона рамки на экране. */
const ОКНО = 288

type Точка = { x: number; y: number }

export function AvatarCropper({ file, onCancel, onReady }: {
  file: File | null
  onCancel: () => void
  onReady: (file: File) => void
}) {
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [сдвиг, setСдвиг] = useState<Точка>({ x: 0, y: 0 })
  const [занят, setЗанят] = useState(false)
  const холст = useRef<HTMLCanvasElement>(null)
  const тянем = useRef<Точка | null>(null)

  // Картинка читается один раз: FileReader на каждый кадр подвесил бы окно.
  useEffect(() => {
    if (!file) { setImg(null); return }
    const url = URL.createObjectURL(file)
    const i = new Image()
    i.onload = () => { setImg(i); setZoom(1); setСдвиг({ x: 0, y: 0 }) }
    i.src = url
    return () => URL.revokeObjectURL(url)
  }, [file])

  /** Масштаб, при котором снимок закрывает рамку целиком. */
  const базовый = img ? Math.max(ОКНО / img.width, ОКНО / img.height) : 1

  useEffect(() => {
    const c = холст.current
    if (!c || !img) return
    const ctx = c.getContext('2d')
    if (!ctx) return
    const k = базовый * zoom
    const w = img.width * k
    const h = img.height * k
    ctx.clearRect(0, 0, ОКНО, ОКНО)
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, ОКНО, ОКНО)
    ctx.drawImage(img, (ОКНО - w) / 2 + сдвиг.x, (ОКНО - h) / 2 + сдвиг.y, w, h)
  }, [img, zoom, сдвиг, базовый])

  function начать(e: React.PointerEvent) {
    тянем.current = { x: e.clientX - сдвиг.x, y: e.clientY - сдвиг.y }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  function тянуть(e: React.PointerEvent) {
    if (!тянем.current) return
    setСдвиг({ x: e.clientX - тянем.current.x, y: e.clientY - тянем.current.y })
  }
  const отпустить = () => { тянем.current = null }

  async function готово() {
    if (!img || !file) return
    setЗанят(true)
    try {
      const c = document.createElement('canvas')
      c.width = c.height = СТОРОНА
      const ctx = c.getContext('2d')
      if (!ctx) return
      const k = (базовый * zoom) * (СТОРОНА / ОКНО)
      const w = img.width * k
      const h = img.height * k
      const s = СТОРОНА / ОКНО
      ctx.drawImage(img, (СТОРОНА - w) / 2 + сдвиг.x * s, (СТОРОНА - h) / 2 + сдвиг.y * s, w, h)
      const blob = await new Promise<Blob | null>((r) => c.toBlob(r, 'image/jpeg', 0.9))
      if (blob) {
        const имя = file.name.replace(/\.[^.]+$/, '') || 'photo'
        onReady(new File([blob], `${имя}.jpg`, { type: 'image/jpeg' }))
      }
    } finally {
      setЗанят(false)
    }
  }

  return (
    <Dialog open={!!file} onOpenChange={(o) => { if (!o) onCancel() }}>
      <DialogContent className="sm:max-w-[360px]">
        <DialogHeader>
          <DialogTitle>Как показывать фото</DialogTitle>
          <DialogDescription>
            Потяните снимок и выберите масштаб — в круге то, что увидят в чате.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col items-center gap-3">
          <div className="relative" style={{ width: ОКНО, height: ОКНО }}>
            <canvas ref={холст} width={ОКНО} height={ОКНО}
              className="cursor-grab touch-none rounded-lg active:cursor-grabbing"
              onPointerDown={начать} onPointerMove={тянуть}
              onPointerUp={отпустить} onPointerCancel={отпустить} />
            {/* Затемнение с «дыркой»: тень круглого элемента заливает всё вокруг,
                внутри круга снимок остаётся чистым. Кликов слой не ловит. */}
            <div className="pointer-events-none absolute rounded-full ring-2 ring-white/70"
              style={{ inset: ОКНО * 0.06, boxShadow: '0 0 0 9999px rgba(15,23,42,.55)' }} />
          </div>
          <label className="flex w-full items-center gap-3 text-xs text-muted-foreground">
            Масштаб
            <input type="range" min={1} max={3} step={0.01} value={zoom}
              aria-label="Масштаб фото"
              onChange={(e) => setZoom(Number(e.target.value))} className="flex-1" />
          </label>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onCancel}>Отмена</Button>
          <Button type="button" onClick={() => void готово()} disabled={!img || занят}>
            {занят && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Поставить фото
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
