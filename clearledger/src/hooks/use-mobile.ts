import * as React from "react"

const MOBILE_BREAKPOINT = 768

/**
 * Ширину читаем СРАЗУ при первом рендере, а не в эффекте.
 *
 * Раньше состояние стартовало с `undefined`, а `!!undefined` — это false, то есть
 * «десктоп». Правильное значение приходило только после монтирования, поэтому каждый
 * переход в приложение показывал один кадр десктопной раскладки и лишь затем
 * перерисовывался в мобильную: на телефоне это читалось как «оно сначала открылось
 * в десктопном виде». Ленивый инициализатор снимает лишний кадр целиком.
 */
function useMediaMatch(query: string) {
  const [matches, setMatches] = React.useState(() => window.matchMedia(query).matches)

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    // Ширина могла измениться между первым рендером и подпиской (поворот экрана,
    // раскрытие панели браузера) — сверяемся ещё раз.
    onChange()
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}

export function useIsMobile() {
  return useMediaMatch(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}

/**
 * Ширина вьюпорта ≤ maxPx. Для точечных порогов (напр. рабочий стол переходит на
 * компактную раскладку на планшетах ≤1024, где десктопные боковые меню съедают
 * почти всё место под контент).
 */
export function useMaxWidth(maxPx: number) {
  return useMediaMatch(`(max-width: ${maxPx}px)`)
}

/**
 * Работа пальцем, а не курсором (`ecosystem-deploy/docs/MOBILE.md` §1): развилка
 * идёт по способу ввода, а не по ширине окна — планшет держат в руках так же, как
 * телефон, а узкое окно на ноутбуке остаётся десктопом.
 */
export function useTouchInput() {
  return useMediaMatch('(hover: none) and (pointer: coarse)')
}
