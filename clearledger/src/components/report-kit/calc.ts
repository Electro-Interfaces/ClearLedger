import { useSyncExternalStore } from 'react'
import type { Cell } from './format'

export type PinItem = { id: number; label: string; value: number; money: boolean }
type ToolsState = { expr: string; pins: PinItem[] }

let tools: ToolsState = { expr: '', pins: [] }
const subs = new Set<() => void>()
const set = (patch: Partial<ToolsState>) => {
  tools = { ...tools, ...patch }
  subs.forEach((f) => f())
}

export const useTools = () =>
  useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => tools,
  )

const text = (n: number) => String(Math.round(n * 100) / 100).replace('.', ',')

export const setExpr = (expr: string) => set({ expr })

export function feedNumber(n: number) {
  const e = tools.expr.trim()
  const value = n < 0 ? `(${text(n)})` : text(n)
  set({ expr: !e ? value : /[+\-−×÷(]$/.test(e) ? `${e} ${value}` : `${e} + ${value}` })
}

export function addPin(label: string, value: number, money = false) {
  set({ pins: [{ id: Date.now(), label, value: Math.round(value * 100) / 100, money }, ...tools.pins].slice(0, 20) })
}

export const dropPin = (id: number) => set({ pins: tools.pins.filter((p) => p.id !== id) })

export function evaluate(expr: string): number | null {
  const src = expr.replace(/\s+/g, '').replace(/,/g, '.').replace(/×/g, '*').replace(/÷/g, '/').replace(/−/g, '-')
  if (!src) return null
  let at = 0
  const peek = () => src[at]
  const number = (): number => {
    if (peek() === '(') {
      at++
      const v = sum()
      if (peek() !== ')') throw new Error('paren')
      at++
      return v
    }
    if (peek() === '-') {
      at++
      return -number()
    }
    const m = /^\d+(\.\d+)?/.exec(src.slice(at))
    if (!m) throw new Error('number')
    at += m[0].length
    return Number(m[0])
  }
  const product = (): number => {
    let v = number()
    while (peek() === '*' || peek() === '/') {
      const op = src[at++]
      const r = number()
      v = op === '*' ? v * r : v / r
    }
    return v
  }
  const sum = (): number => {
    let v = product()
    while (peek() === '+' || peek() === '-') {
      const op = src[at++]
      const r = product()
      v = op === '+' ? v + r : v - r
    }
    return v
  }
  try {
    const v = sum()
    return at === src.length && Number.isFinite(v) ? v : null
  } catch {
    return null
  }
}

export type CalcTotal = 'sum' | 'formula' | 'none'
export type CalcCol = { id: number; name: string; expr: string; total: CalcTotal }

const REF = /\[([^\]]+)\]/g
const round = (v: number) => Math.round(v * 100) / 100

export const refsOf = (expr: string) => [...expr.matchAll(REF)].map((m) => m[1].trim())

export function calcValue(expr: string, head: string[], row: Cell[]): Cell {
  let bad = false
  const src = expr.replace(REF, (_, name: string) => {
    const v = row[head.indexOf(name.trim())]
    if (typeof v !== 'number') bad = true
    return typeof v === 'number' ? `(${v.toFixed(6)})` : '0'
  })
  if (bad) return ''
  const v = evaluate(src)
  return v === null ? '' : round(v)
}

export function checkCalc(c: { name: string; expr: string }, head: string[]): string {
  if (!c.name.trim()) return 'Дайте столбцу название.'
  if (head.includes(c.name.trim())) return 'Столбец с таким названием уже есть.'
  if (!c.expr.trim()) return 'Соберите формулу из столбцов и знаков.'
  const unknown = refsOf(c.expr).find((r) => !head.includes(r))
  if (unknown) return `Нет столбца «${unknown}».`
  if (!refsOf(c.expr).length) return 'В формуле нет ни одного столбца.'
  let k = 0
  if (evaluate(c.expr.replace(REF, () => String(1.37 * ++k))) === null) return 'Формула не закончена: проверьте знаки и скобки.'
  return ''
}

export function withCalc<S extends { head: string[]; rows: Cell[][]; total?: Cell[] }>(sheet: S, calcs: CalcCol[]): S {
  if (!calcs.length) return sheet
  const head = [...sheet.head]
  const rows = sheet.rows.map((r) => [...r])
  const total = sheet.total && [...sheet.total]
  for (const c of calcs) {
    for (const r of rows) r.push(calcValue(c.expr, head, r))
    if (total) {
      const i = head.length
      total.push(
        c.total === 'none'
          ? ''
          : c.total === 'formula'
            ? calcValue(c.expr, head, total)
            : round(rows.reduce((s, r) => s + (typeof r[i] === 'number' ? (r[i] as number) : 0), 0)),
      )
    }
    head.push(c.name)
  }
  return { ...sheet, head, rows, total }
}

export function deriveTotals(head: string[], calcs: CalcCol[]) {
  const base = head.length - calcs.length
  if (!calcs.some((c) => c.total === 'formula')) return undefined
  return (t: Cell[]) => {
    const out = [...t]
    calcs.forEach((c, k) => {
      if (c.total === 'formula') out[base + k] = calcValue(c.expr, head, out)
    })
    return out
  }
}
