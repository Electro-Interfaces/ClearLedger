/**
 * «Поддержка» внутри оболочки пространства.
 *
 * Поддержка — отдельное приложение стека (/support), но человеку это знать незачем:
 * шапка, чаты, уведомления и меню вокруг неё те же, что у любого продукта, а внутри
 * рамки — её рабочая область. Раньше она открывалась своей страницей, и каждую общую
 * функцию (вход, уведомления, счётчики) приходилось делать в ней заново
 * (решение МАГа 23.09.2026).
 *
 * Адрес внутри Поддержки живёт параметром `?p=`, а не путём: вкладки оболочки держатся
 * по пути, и каждый переход внутри рамки иначе заводил бы новую вкладку с новой рамкой.
 * Путь сообщает сама Поддержка (`support:path`, `src/lib/spaceFrame.ts` в TSupport).
 */
import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

export default function SupportFramePage() {
  const [params, setParams] = useSearchParams()
  const path = params.get('p') || '/'
  const frame = useRef<HTMLIFrameElement>(null)
  // Где рамка сейчас: её собственный переход не должен перезагружать её же.
  const shown = useRef(path)
  const src = useRef(`/support${path}`).current

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.data?.type !== 'support:path') return
      if (e.source !== frame.current?.contentWindow) return
      shown.current = String(e.data.path)
      setParams({ p: shown.current }, { replace: true })
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [setParams])

  // Новый адрес пришёл снаружи (ссылка, закреплённая вкладка) — ведём рамку туда.
  useEffect(() => {
    if (path === shown.current) return
    shown.current = path
    frame.current?.contentWindow?.location.replace(`/support${path}`)
  }, [path])

  return <iframe ref={frame} src={src} title="Поддержка" className="h-full w-full border-0 bg-background" />
}
