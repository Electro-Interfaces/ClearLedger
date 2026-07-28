/**
 * Ключи доступа: `<продукт>` — рабочее место целиком, `<продукт>:<раздел>` — его часть.
 *
 * Правила отметок одни для роли и для человека, поэтому живут здесь, а не в каждом
 * экране: матрица ролей и карта сотрудников должны понимать «продукт покрывает свои
 * разделы» одинаково, иначе одна и та же галочка значит разное.
 */

/** Что даёт набор ключей по продукту. `null` — полный доступ (админ / все продукты). */
export type AppAccess = 'full' | 'part' | 'none'

export function appState(keys: string[] | null, app: string): AppAccess {
  if (keys === null || keys.includes(app)) return 'full'
  return keys.some((k) => k.startsWith(`${app}:`)) ? 'part' : 'none'
}

/** Переключить продукт или его раздел. Отметка продукта поглощает его разделы. */
export function toggleAccessKey(keys: string[], key: string, app: string): string[] {
  const set = new Set(keys)
  if (set.has(key)) set.delete(key)
  else set.add(key)
  // Продукт целиком — частные разделы становятся шумом; сняли продукт — уходят и они.
  if (key === app) for (const k of [...set]) if (k.startsWith(`${app}:`)) set.delete(k)
  return [...set]
}

export const sameAccess = (a: string[] | null, b: string[] | null) =>
  a === null || b === null ? a === b : a.length === b.length && a.every((k) => b.includes(k))
