/**
 * Переход из ВСТРОЕННОЙ витрины пространства.
 *
 * Панель «Приложения» в приложениях вне Ledger (Поддержка) — это тот же стол Ядра,
 * показанный фреймом (`public/eco-rail.js`). Обычный переход внутри такого фрейма
 * открыл бы продукт в рамке панели: шапка и меню чужого приложения остались бы
 * снаружи. Поэтому из фрейма уводим ВЕРХНЕЕ окно.
 *
 * Фрейм и хозяин живут на одном origin (docs/CORE.md §6), доступ к `window.top`
 * разрешён; чужой origin отдаёт исключение — тогда ведём себя как обычная страница.
 */

/** Окно, которым ходим: верхнее, если стол показан фреймом, иначе своё. */
export function topWindow(): Window {
  try {
    return window.top && window.top !== window.self ? window.top : window
  } catch {
    return window
  }
}

/** Стол показан фреймом внутри другого приложения. */
export const inFrame = () => topWindow() !== window

/** Уйти по адресу всем окном. Адрес приводим к абсолютному: у фрейма своя база. */
export function assignTop(url: string) {
  topWindow().location.assign(new URL(url, window.location.href).href)
}

/** Полный адрес маршрута пространства — маршрут склеивается с базой сборки. */
export const spaceUrl = (route: string) =>
  new URL(route.replace(/^\/+/, ''), new URL(import.meta.env.BASE_URL, window.location.origin)).href
