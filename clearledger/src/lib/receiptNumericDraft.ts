/** Сырой ввод хранится отдельно: пустое/ошибочное значение не означает ноль. */
export type ReceiptNumericField = 'qty_expected' | 'qty_fact' | 'price'
export type ReceiptNumericDrafts = Record<number, Partial<Record<ReceiptNumericField, string>>>

export function parseReceiptNumber(raw: string): number | null {
  const value = raw.trim()
  if (!/^[+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$/.test(value)) return null
  const parsed = Number(value.replace(',', '.'))
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1_000_000_000 ? parsed : null
}

export function removeReceiptNumericDraft(drafts: ReceiptNumericDrafts, index: number): ReceiptNumericDrafts {
  return Object.fromEntries(Object.entries(drafts)
    .filter(([key]) => Number(key) !== index)
    .map(([key, value]) => [Number(key) > index ? Number(key) - 1 : Number(key), value]))
}
