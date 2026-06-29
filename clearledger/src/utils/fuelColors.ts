/**
 * Цвета видов топлива (бейджи/легенда). Перенесено 1:1 из TradeFrame.
 */
export interface FuelColorMeta {
  bg: string
  text: string
  hex: string
  label: string
  name: string
}

interface FuelColorRule extends FuelColorMeta {
  matches: Array<string | RegExp>
}

const FUEL_COLOR_RULES: FuelColorRule[] = [
  { matches: ['аи-92', '92'], bg: 'bg-red-500', text: 'text-red-600 dark:text-red-400', hex: '#ef4444', label: '92', name: 'АИ-92' },
  { matches: ['аи-95', '95'], bg: 'bg-orange-500', text: 'text-orange-600 dark:text-orange-400', hex: '#f97316', label: '95', name: 'АИ-95' },
  { matches: ['аи-98', '98'], bg: 'bg-yellow-500', text: 'text-yellow-600 dark:text-yellow-400', hex: '#eab308', label: '98', name: 'АИ-98' },
  { matches: ['аи-100', '100'], bg: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400', hex: '#f59e0b', label: '100', name: 'АИ-100' },
  { matches: ['дтз', /дт.*зим/i, /диз.*зим/i, /аркт/i], bg: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400', hex: '#3b82f6', label: 'ДТЗ', name: 'ДТ зимнее' },
  { matches: ['дтл', /дт.*лет/i, /диз.*лет/i], bg: 'bg-lime-500', text: 'text-lime-600 dark:text-lime-400', hex: '#84cc16', label: 'ДТЛ', name: 'ДТ летнее' },
  { matches: ['дт', 'диз', 'дизель', 'diesel'], bg: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', hex: '#10b981', label: 'ДТ', name: 'Дизельное топливо' },
  { matches: ['суг', 'газ', 'lpg', 'propane', 'пропан'], bg: 'bg-violet-500', text: 'text-violet-600 dark:text-violet-400', hex: '#8b5cf6', label: 'СУГ', name: 'СУГ / Газ' },
  { matches: ['метан', 'cng'], bg: 'bg-cyan-500', text: 'text-cyan-600 dark:text-cyan-400', hex: '#06b6d4', label: 'МЕТ', name: 'Метан' },
  { matches: ['бензин', 'petrol', 'gasoline'], bg: 'bg-slate-400', text: 'text-slate-600 dark:text-slate-400', hex: '#94a3b8', label: 'БЕН', name: 'Бензин' },
]

const UNKNOWN_FUEL: FuelColorMeta = {
  bg: 'bg-muted-foreground', text: 'text-muted-foreground', hex: '#94a3b8', label: 'ТОПЛ.', name: 'Топливо',
}

function normalizeFuelInput(input: string | number | null | undefined): string {
  return String(input ?? '').trim().toLowerCase()
}

function makeShortLabel(raw: string): string {
  const compact = raw.replace(/[^a-zA-Zа-яА-Я0-9]/g, '').toUpperCase()
  return compact.slice(0, 6) || UNKNOWN_FUEL.label
}

export function getFuelColor(input: string | number | null | undefined): FuelColorMeta {
  const normalized = normalizeFuelInput(input)
  const match = FUEL_COLOR_RULES.find((rule) =>
    rule.matches.some((pattern) =>
      typeof pattern === 'string' ? normalized.includes(pattern) : pattern.test(normalized),
    ),
  )
  if (match) {
    return { bg: match.bg, text: match.text, hex: match.hex, label: match.label, name: match.name }
  }
  return { ...UNKNOWN_FUEL, label: makeShortLabel(String(input ?? '')), name: String(input ?? UNKNOWN_FUEL.name) || UNKNOWN_FUEL.name }
}
