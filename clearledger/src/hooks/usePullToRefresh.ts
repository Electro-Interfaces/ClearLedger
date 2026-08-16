/**
 * «Потянуть вниз — обновить»: жест, которого на телефоне ждут по умолчанию.
 *
 * Пространство показывает живые цифры, и человек, увидев вчерашнюю сумму, тянет
 * экран — так устроены все мобильные приложения. Без обработчика жест ничего не
 * делал, и это читалось как «приложение зависло».
 *
 * Работает только при вводе пальцем и только когда список прокручен вверх: иначе
 * жест перехватывал бы обычную прокрутку. Порог 70 px — как в ElsyPlus Monitor.
 */
import { useEffect, useRef, useState } from 'react'

const THRESHOLD = 70
const MAX_PULL = 110

export type PullState = 'idle' | 'pulling' | 'ready' | 'refreshing'

export function usePullToRefresh(
  onRefresh: () => Promise<unknown> | unknown,
  enabled = true,
) {
  const ref = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<PullState>('idle')
  const [distance, setDistance] = useState(0)
  // Обработчики висят на узле, а колбэк меняется каждый рендер — держим свежий
  // в ref, иначе пришлось бы переподписываться на touch-события.
  const cb = useRef(onRefresh)
  cb.current = onRefresh
  // Актуальная дистанция для обработчика конца жеста: он замкнут на первый рендер.
  const distanceRef = useRef(0)
  distanceRef.current = distance

  useEffect(() => {
    const el = ref.current
    if (!el || !enabled) return
    // Курсор такого жеста не делает: на десктопе он только мешал бы прокрутке.
    if (!window.matchMedia('(pointer: coarse)').matches) return

    let startY = 0
    let pulling = false
    let frame = 0

    const onStart = (e: TouchEvent) => {
      if (el.scrollTop > 0) return       // тянем только от самого верха
      startY = e.touches[0].clientY
      pulling = true
    }

    const onMove = (e: TouchEvent) => {
      if (!pulling) return
      const d = e.touches[0].clientY - startY
      if (d <= 0) { setDistance(0); setState('idle'); return }
      // Сопротивление: палец проходит больше, чем едет экран — жест ощущается
      // тугим и не срабатывает от случайного касания.
      const shown = Math.min(d * 0.5, MAX_PULL)
      // Один пересчёт на кадр: без этого палец даёт до 120 setState в секунду,
      // и жест на недорогом телефоне идёт рывками — ровно там, где он и нужен.
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0
          setDistance(shown)
          setState(shown >= THRESHOLD ? 'ready' : 'pulling')
        })
      }
      if (shown > 4 && e.cancelable) e.preventDefault()
    }

    const onEnd = async () => {
      if (!pulling) return
      pulling = false
      const ready = distanceRef.current >= THRESHOLD
      setDistance(0)
      if (!ready) { setState('idle'); return }
      setState('refreshing')
      // Короткая вибрация — подтверждение, что жест принят (Android; iOS её игнорирует).
      navigator.vibrate?.(30)
      try { await cb.current() } finally { setState('idle') }
    }

    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('touchcancel', onEnd)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
    }
  }, [enabled])

  return { ref, state, distance }
}
