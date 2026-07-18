/**
 * Режим «Показать структуру» — обучающая подсветка зон интерфейса.
 *
 * По нажатию лампочки в шапке все функциональные зоны рабочего стола получают
 * яркую окантовку и подпись: навигация приложения, лента экранов, фильтр
 * рабочей области, разделы учёта, табы вида, параметры вида, данные, панель
 * взаимодействия. Пользователь видит структуру целиком, разбирается — и
 * возвращается к спокойному виду повторным нажатием.
 *
 * Механика: класс `cl-guide` на <html>. Вся визуализация — в index.css по
 * атрибуту `data-zone`, поэтому компонентам достаточно проставить этот атрибут
 * и не тянуть никакого состояния.
 */

import { useCallback, useEffect, useState } from 'react'

const KEY = 'cl-guide-mode'
const CLASS = 'cl-guide'

function apply(on: boolean): void {
  document.documentElement.classList.toggle(CLASS, on)
}

export function useGuideMode(): { on: boolean; toggle: () => void } {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem(KEY) === '1' } catch { return false }
  })

  useEffect(() => {
    apply(on)
    try { localStorage.setItem(KEY, on ? '1' : '0') } catch { /* ignore */ }
  }, [on])

  const toggle = useCallback(() => setOn((v) => !v), [])
  return { on, toggle }
}
