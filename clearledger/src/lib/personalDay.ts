/**
 * Как назвать личный день работы.
 *
 * Личная дата — это ответ на «когда я этим займусь», и она никогда не значит
 * срок: срок принадлежит компании и живёт в `due_at`. Три случая различаются
 * словами, потому что означают разное:
 *
 *   сегодня  → «в моём дне»   — работа стоит в сегодняшнем дне;
 *   впереди  → «на 3 сент.»   — план на будущее, предмет на виду;
 *   позади   → «с 28 авг.»    — план был и не выполнен, работа перешла.
 *
 * Перенос — не просрочка: обязательство перед компанией могло и не наступить.
 * Поэтому он назван нейтрально и не красится тревожным цветом.
 */

/** Сегодняшний день в том же виде, в каком его хранит отметка (YYYY-MM-DD). */
export function todayKey(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** «3 сент.» — дату в строке читают глазом, а не разбирают по частям. */
export function shortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return isNaN(d.getTime()) ? iso
    : d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

export interface PlanLabel {
  text: string
  /** Перенос с прошлого дня: показывается спокойнее, чем сегодняшний план. */
  carried: boolean
}

/** Подпись личного плана, или `null` — если человек ничего не планировал. */
export function planLabel(takenFor: string | null | undefined,
                          today: string = todayKey()): PlanLabel | null {
  if (!takenFor) return null
  if (takenFor === today) return { text: 'в моём дне', carried: false }
  if (takenFor > today) return { text: `на ${shortDay(takenFor)}`, carried: false }
  return { text: `с ${shortDay(takenFor)}`, carried: true }
}
