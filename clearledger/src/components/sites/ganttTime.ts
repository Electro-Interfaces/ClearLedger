/** Время для диаграмм Ганта проектов: подписи дат и длительностей. */
export const H = 3_600_000
export const DAY = 24 * H
export const ruDate = (t: number) => new Date(t).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
export const hm = (t: number) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
export const dur = (ms: number) => ms < H ? '<1 ч' : ms < DAY ? `${Math.round(ms / H)} ч` : `${Math.round(ms / DAY)} дн.`
