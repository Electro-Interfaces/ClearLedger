/**
 * Горизонтальный скролл с полосой прокрутки СВЕРХУ и СНИЗУ.
 * Верхняя полоса появляется только когда содержимое шире контейнера (не влезает).
 * Обе полосы синхронизированы. Для широких таблиц (детали смены и т.п.).
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export function DualScrollX({ children, className }: { children: ReactNode; className?: string }) {
  const topRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [innerWidth, setInnerWidth] = useState(0)
  const lock = useRef(false)

  useLayoutEffect(() => {
    const inner = bottomRef.current?.firstElementChild as HTMLElement | null
    if (!inner) return
    const measure = () => setInnerWidth(inner.scrollWidth)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(inner)
    return () => ro.disconnect()
  }, [])

  const sync = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (lock.current) { lock.current = false; return }
    if (from && to) { lock.current = true; to.scrollLeft = from.scrollLeft }
  }

  return (
    <div className={className}>
      {/* Верхняя полоса прокрутки — spacer шириной с содержимое */}
      <div ref={topRef} onScroll={() => sync(topRef.current, bottomRef.current)}
        className="overflow-x-auto overflow-y-hidden">
        <div style={{ width: innerWidth, height: 1 }} />
      </div>
      {/* Содержимое + нижняя полоса прокрутки */}
      <div ref={bottomRef} onScroll={() => sync(bottomRef.current, topRef.current)}
        className="overflow-x-auto rounded-lg border border-border">
        {children}
      </div>
    </div>
  )
}
