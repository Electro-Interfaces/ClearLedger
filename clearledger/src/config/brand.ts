/**
 * Бренд экосистемы-контейнера (white-label). Контейнер = экосистема заказчика
 * (docs/CORE.md §1), поэтому имя экосистемы задаётся на контейнер, а не хардкодится.
 * Бакается на сборке фронт-образа компании (`VITE_ECOSYSTEM_BRAND`), как VITE_API_URL.
 * Дефолт — «ElsyPlus» (платформенный/дев-контур без явного бренда).
 *
 *   rushydro → «РусГидро», gig → «ГИГ», …
 */
export const ECOSYSTEM_BRAND: string =
  (import.meta.env.VITE_ECOSYSTEM_BRAND as string | undefined)?.trim() || 'ElsyPlus'

/** «Экосистема <бренд>» — имя ПРОСТРАНСТВА заказчика: шапки стола, Центра управления, вход. */
export const ECOSYSTEM_TITLE = `Экосистема ${ECOSYSTEM_BRAND}`

/**
 * Имя ПЛАТФОРМЫ — того, на чём построено пространство. Пространство принадлежит
 * заказчику и носит его бренд, а платформа остаётся нашей: на экране входа она мелкой
 * подписью, чтобы было понятно, чей продукт, но бренд заказчика оставался главным.
 * Переопределяется на сборке (`VITE_PLATFORM_NAME`) — для партнёрских поставок.
 */
export const PLATFORM_NAME: string =
  (import.meta.env.VITE_PLATFORM_NAME as string | undefined)?.trim() || 'ElsyPlus Экосистема'
