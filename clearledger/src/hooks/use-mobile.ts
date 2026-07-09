import * as React from "react"

const MOBILE_BREAKPOINT = 768

export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return !!isMobile
}

/**
 * Ширина вьюпорта ≤ maxPx. Для точечных порогов (напр. рабочий стол переходит на
 * компактную раскладку на планшетах ≤1024, где десктопные боковые меню съедают
 * почти всё место под контент).
 */
export function useMaxWidth(maxPx: number) {
  const [below, setBelow] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${maxPx}px)`)
    const onChange = () => setBelow(window.innerWidth <= maxPx)
    mql.addEventListener("change", onChange)
    setBelow(window.innerWidth <= maxPx)
    return () => mql.removeEventListener("change", onChange)
  }, [maxPx])

  return !!below
}
