export type Cell = string | number

const nfq = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const qty = (v: number) => nfq.format(v)
export const num2 = (v: number) => nf2.format(v)
export const isMoney = (head?: string) => !!head?.includes('₽')
export const showNum = (v: number, head?: string) => (isMoney(head) ? num2(v) : qty(Math.round(v * 100) / 100))
export const showCell = (x: Cell, head?: string) => (typeof x === 'number' ? showNum(x, head) : x)

export function plural(n: number, one: string, few: string, many: string) {
  const a = Math.abs(n) % 100
  const b = a % 10
  if (a > 10 && a < 20) return many
  if (b > 1 && b < 5) return few
  if (b === 1) return one
  return many
}
