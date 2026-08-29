/**
 * В какой колонке доски стоит карточка.
 *
 * Правило вынесено из экрана, потому что оно единственное нетривиальное в
 * доске: карточка обязана стоять ровно в ОДНОЙ колонке. Предмет, попавший в
 * две, превращает перенос в загадку «переместить или добавить», а предмет, не
 * попавший ни в одну, просто исчезает с доски — и то и другое видно не сразу,
 * а через неделю работы.
 *
 * Порядок ответов и есть старшинство: спрятанное важнее взятого в день, взятое
 * в день важнее подборки, в которой предмет лежит. Иначе отложенная работа
 * продолжала бы стоять в подборке и «отложить» переставало бы что-либо значить.
 */

export type BoardAxis = 'state' | 'place' | 'due'

/** Ровно то, от чего зависит колонка. Целую строку работы сюда не тащим: тогда
 *  правило нельзя проверить без половины приложения. */
export interface BoardItem {
  state: string
  due_at: string | null
  /** Считает сервер: срок прошёл, и работа ещё жива. */
  overdue: boolean
  mark?: {
    list_id: string | null
    taken_for: string | null
    deferred_until: string | null
  } | null
}

export interface BoardHorizon {
  /** Местная дата человека, `YYYY-MM-DD`. У пространства от Владивостока до
   *  Москвы единого «сегодня» нет, поэтому день приходит снаружи. */
  today: string
  tomorrow: string
  /** Последний день текущей недели. */
  weekEnd: string
  /** Подборки, которые у человека есть. Отметка на удалённую подборку не должна
   *  уносить карточку в несуществующую колонку — там её никто не найдёт. */
  lists?: Set<string>
}

export function columnOf(axis: BoardAxis, item: BoardItem, h: BoardHorizon): string {
  if (axis === 'state') return item.state

  if (axis === 'place') {
    const m = item.mark
    if (m?.deferred_until && m.deferred_until > h.today) return 'deferred'
    if (m?.taken_for === h.today) return 'day'
    if (m?.list_id && (h.lists?.has(m.list_id) ?? false)) return `list:${m.list_id}`
    return 'loose'
  }

  if (!item.due_at) return 'none'
  // Просрочка старше всего остального: работа со сроком в прошлом не «сегодня»,
  // сколько бы часов ни осталось до полуночи.
  if (item.overdue) return 'overdue'
  const день = item.due_at.slice(0, 10)
  // `<=` а не `===`: срок сегодня утром, ещё не наступивший по времени, — это
  // всё равно сегодня, и в «Просрочено» он попадёт сам, когда время пройдёт.
  if (день <= h.today) return 'today'
  if (день === h.tomorrow) return 'tomorrow'
  return день <= h.weekEnd ? 'week' : 'later'
}
