/**
 * Подбор общего времени: когда все свободны и всем можно.
 *
 * «Свободно» и «можно» — разные вещи, и именно на их смешении ломаются
 * планировщики. Человек, у которого в восемь утра пусто, не свободен: он ещё не
 * работает. Пространство растянуто от Владивостока до Москвы, и общее окно у
 * такой пары бывает в два часа шириной — предложить им девять утра значит
 * предложить одному ночь.
 *
 * Поэтому кандидат обязан пройти три проверки: он внутри рабочего окна КАЖДОГО
 * обязательного участника в ЕГО поясе, он не пересекается ни с чьей занятостью,
 * и он целиком помещается в запрошенную длительность.
 *
 * Необязательные участники в отбор не входят — иначе встречу на пять человек не
 * собрать никогда, — но их занятость показывается числом: организатор видит,
 * скольких он теряет, выбирая это время.
 */

export interface Busy {
  starts_at: string
  ends_at: string
  all_day?: boolean
}

export interface Person {
  user_id: string
  name: string
  /** Имя IANA. Пусто — считаем по поясу смотрящего: врать про чужое утро хуже,
   *  чем признать, что мы его не знаем. */
  tz?: string | null
  /** «09:00». Пусто — рабочее окно по умолчанию. */
  work_start?: string | null
  work_end?: string | null
  busy: Busy[]
}

export interface Slot {
  /** Начало кандидата, ISO. */
  at: string
  /** Кто из НЕобязательных занят в это время. Отбор они не проваливают. */
  busyOptional: string[]
}

const ПО_УМОЛЧАНИЮ_НАЧАЛО = 9 * 60
const ПО_УМОЛЧАНИЮ_КОНЕЦ = 18 * 60

/** «09:30» → 570 минут от полуночи. Мусор — к умолчанию: подбор не должен
 *  падать из-за опечатки в чужой настройке. */
export function minutesOf(value: string | null | undefined, fallback: number): number {
  if (!value) return fallback
  const [ч, м] = value.split(':')
  const час = Number(ч)
  const мин = Number(м ?? 0)
  if (!Number.isFinite(час) || !Number.isFinite(мин)) return fallback
  return час * 60 + мин
}

/** Который час у человека в его поясе, в минутах от полуночи, и какой это день
 *  недели. Через `Intl`, а не сложением смещения: смещение меняется при
 *  переводе часов, и «10:00 по Владивостоку» иначе уедет на час дважды в год. */
export function localParts(at: Date, tz: string | null | undefined) {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz || undefined,
    hour: '2-digit', minute: '2-digit', weekday: 'short', hour12: false,
  })
  const parts = fmt.formatToParts(at)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const дни: Record<string, number> = {
    Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0,
  }
  return {
    minutes: Number(get('hour')) * 60 + Number(get('minute')),
    weekday: дни[get('weekday')] ?? 1,
  }
}

function пересекается(aFrom: number, aTo: number, b: Busy): boolean {
  const bFrom = new Date(b.starts_at).getTime()
  const bTo = new Date(b.ends_at).getTime()
  return aFrom < bTo && aTo > bFrom
}

/** Помещается ли отрезок в рабочее окно человека целиком.
 *
 *  Целиком, а не началом: встреча, начатая за десять минут до конца дня, — это
 *  не «успел», это «остался после работы». */
export function inWorkWindow(from: Date, to: Date, p: Person): boolean {
  const н = localParts(from, p.tz)
  const к = localParts(to, p.tz)
  if (н.weekday === 0 || н.weekday === 6) return false
  // Через полночь встречу не подбираем: конец обязан быть в том же дне.
  if (к.weekday !== н.weekday) return false
  const начало = minutesOf(p.work_start, ПО_УМОЛЧАНИЮ_НАЧАЛО)
  const конец = minutesOf(p.work_end, ПО_УМОЛЧАНИЮ_КОНЕЦ)
  return н.minutes >= начало && к.minutes <= конец
}

/**
 * Кандидаты на встречу.
 *
 * @param people        все, кого зовут (обязательные и необязательные)
 * @param requiredIds   чьё рабочее окно и занятость обязательны
 * @param from,to       окно поиска
 * @param minutes       длительность встречи
 * @param stepMinutes   шаг сетки кандидатов
 */
export function findSlots({
  people, requiredIds, from, to, minutes, stepMinutes = 30, limit = 40,
}: {
  people: Person[]
  requiredIds: string[]
  from: Date
  to: Date
  minutes: number
  stepMinutes?: number
  limit?: number
}): Slot[] {
  const обязательные = people.filter((p) => requiredIds.includes(p.user_id))
  const необязательные = people.filter((p) => !requiredIds.includes(p.user_id))
  if (!обязательные.length || minutes <= 0) return []

  const шаг = stepMinutes * 60_000
  const длина = minutes * 60_000
  // Начинаем с ровного получаса: «в 14:07» никто не назначает.
  const старт = Math.ceil(from.getTime() / шаг) * шаг
  const out: Slot[] = []

  for (let t = старт; t + длина <= to.getTime(); t += шаг) {
    const начало = new Date(t)
    const конец = new Date(t + длина)
    if (!обязательные.every((p) => inWorkWindow(начало, конец, p))) continue
    if (обязательные.some((p) => p.busy.some((b) => пересекается(t, t + длина, b)))) continue
    out.push({
      at: начало.toISOString(),
      busyOptional: необязательные
        .filter((p) => p.busy.some((b) => пересекается(t, t + длина, b)))
        .map((p) => p.name),
    })
    if (out.length >= limit) break
  }
  return out
}
