/**
 * Панель на весь экран — для разделов, где смотрят карту и данные вокруг неё.
 *
 * В рабочей области между рельсой разделов, фильтрами и шапкой карте остаётся
 * половина экрана: на обзоре страны точки сливаются, а таблицу рядом приходится
 * листать. Разбор места — работа на весь стол (МАГ, 13.09.2026).
 *
 * Не `requestFullscreen` браузера: тот прячет шапку пространства вместе с
 * переключателем организации и уведомлениями, а человек остаётся в приложении и
 * продолжает работать. Здесь панель просто занимает окно целиком.
 */
import { useEffect, useState } from 'react'

export function useFullscreenPanel(
  base = 'flex h-full min-h-0 flex-col gap-3 p-4',
  // Карте нужна вся высота окна, поэтому внешней прокрутки у неё быть не должно:
  // с `overflow-auto` блок `flex-1` считает высоту по содержимому, и полотно
  // остаётся прежнего размера. Панелям с длинным разбором прокрутка, наоборот,
  // нужна — отсюда развилка.
  { scroll = true }: { scroll?: boolean } = {},
) {
  const [on, setOn] = useState(false)

  // Escape — общий выход из «поверх всего»: так ведут себя диалоги пространства,
  // и панель не должна быть исключением.
  useEffect(() => {
    if (!on) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOn(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [on])

  return {
    on,
    toggle: () => setOn((v) => !v),
    className: on
      ? `fixed inset-0 z-50 flex min-h-0 flex-col gap-3 bg-background p-4 ${
        scroll ? 'overflow-auto' : 'overflow-hidden'}`
      : base,
  }
}
