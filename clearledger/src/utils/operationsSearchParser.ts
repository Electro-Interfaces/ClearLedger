/**
 * Разбор строки поиска «Операций» в поля серверного запроса.
 *
 * Перенос из «Монитора» (TradeFrame, `src/utils/operationsSearchParser.ts`):
 * поиск вида «смена 9 азс 6 чек 42 карта 1234» — распознанные сущности уходят
 * точными фильтрами, остаток строки идёт свободным текстом (карта/топливо/число).
 * Числу без ключевого слова доверяем как чеку — самый частый случай у оператора.
 */
export interface ParsedSearch {
  shift?: string
  station?: string
  receipt?: string
  pos?: string
  card?: string
  search?: string
}

const PATTERNS: { regex: RegExp; field: keyof ParsedSearch }[] = [
  { regex: /(?:смена|shift)\s+(\d+)/i, field: 'shift' },
  { regex: /(\d+)\s+(?:смена|shift)/i, field: 'shift' },
  { regex: /(?:азс|станция|station|тт)\s+(\d+)/i, field: 'station' },
  { regex: /(\d+)\s+(?:азс|станция|station|тт)/i, field: 'station' },
  { regex: /(?:чек|receipt)\s+(\d+)/i, field: 'receipt' },
  { regex: /(\d+)\s+(?:чек|receipt)/i, field: 'receipt' },
  { regex: /(?:карта|card)\s+(\S+)/i, field: 'card' },
  { regex: /(?:pos|пос|трк)\s+(\d+)/i, field: 'pos' },
]

export function parseOperationsSearch(query: string): ParsedSearch {
  const q = (query || '').trim()
  if (!q) return {}

  const result: ParsedSearch = {}
  let remaining = q

  for (const { regex, field } of PATTERNS) {
    if (result[field]) continue // поле уже распознано
    const m = remaining.match(regex)
    if (m) {
      result[field] = m[1]
      remaining = remaining.replace(m[0], ' ')
    }
  }

  const rest = remaining.trim().replace(/\s+/g, ' ')
  if (rest) result.search = rest
  return result
}

/** Число из распознанного поля — undefined, если поля не было. */
export const parsedInt = (v: string | undefined): number | undefined =>
  v != null && /^\d+$/.test(v) ? Number(v) : undefined
