/**
 * Утилиты для нормализации текста.
 * Shared: используется в bundleService, normalizationService, referenceService.
 */

/** Нормализация названия контрагента для сравнения / fuzzy match */
export function normalizeCounterparty(raw: string): string {
  return raw
    .toLowerCase()
    .trim()
    .replace(/["«»"']/g, '')
    .replace(/\b(ооо|зао|оао|пао|ип|ао)\b/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Извлекает контрагента из metadata (приоритет полей) */
export function getCounterpartyFromMeta(metadata: Record<string, string>): string {
  return metadata.counterparty
    || metadata._1c_counterparty
    || metadata.contractor
    || metadata.sender
    || ''
}

/** Извлекает номер документа из metadata */
export function getDocNumberFromMeta(metadata: Record<string, string>): string {
  return metadata.docNumber
    || metadata.number
    || metadata._1c_number
    || ''
}

/**
 * Fuzzy-сравнение двух строк (Dice coefficient).
 * Возвращает 0..1 (1 = идентичны).
 */
export function diceCoefficient(a: string, b: string): number {
  const na = a.toLowerCase()
  const nb = b.toLowerCase()
  if (na === nb) return 1
  if (na.length < 2 || nb.length < 2) return 0

  const bigramsA = new Map<string, number>()
  for (let i = 0; i < na.length - 1; i++) {
    const bigram = na.substring(i, i + 2)
    bigramsA.set(bigram, (bigramsA.get(bigram) || 0) + 1)
  }

  let matches = 0
  for (let i = 0; i < nb.length - 1; i++) {
    const bigram = nb.substring(i, i + 2)
    const count = bigramsA.get(bigram) || 0
    if (count > 0) {
      bigramsA.set(bigram, count - 1)
      matches++
    }
  }

  return (2 * matches) / (na.length - 1 + nb.length - 1)
}
