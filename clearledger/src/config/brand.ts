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

/** «Экосистема <бренд>» — подпись в шапках рабочего стола и Центра управления. */
export const ECOSYSTEM_TITLE = `Экосистема ${ECOSYSTEM_BRAND}`
