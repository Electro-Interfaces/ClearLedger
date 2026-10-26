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

/**
 * Телефон — узкий экран ИЛИ невысокий под палец: повёрнутый телефон шире 768 px,
 * и по одной ширине получал раскладку компьютера, где шапки съедали весь экран
 * (QA календаря 27.10.2026). Планшет и ноутбук выше 500 px не задеваются.
 */
export const PHONE_QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px), (max-height: 500px) and (pointer: coarse)`

export function useIsMobile() {
  return useMediaMatch(PHONE_QUERY)
}

/** Невысокий экран под палец — телефон в альбоме: каждая строка оболочки на счету. */
export function useShortTouch() {
  return useMediaMatch('(max-height: 500px) and (pointer: coarse)')
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
