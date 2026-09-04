/**
 * Числа разрезов «Моего» — один расчёт на меню «Трека» и на окно из шапки.
 *
 * Считали в двух местах, и числа под одним словом разошлись: меню брало `total`
 * сервера, окно — длину страницы (сто строк), и у человека с сотней поручений
 * «Я поставил» показывал разное в двух местах одного продукта. Спорить о том,
 * какому верить, не должен никто: расчёт один, вызывают его оба.
 *
 * Функция чистая и берёт готовые ответы запросов: ключи запросов у меню и у
 * окна совпадают, поэтому react-query отдаёт их из общего кэша, а не ходит на
 * сервер второй раз.
 */
import type { SpaceTask } from '@/services/tasksService'
import type { MyWorkItem, PersonalCounts } from '@/services/workService'

export interface WorkCountsInput {
  mine?: { mine: MyWorkItem[] }
  lists?: { counts: PersonalCounts }
  assigned?: { tasks: SpaceTask[]; total: number }
  watching?: { tasks: SpaceTask[]; total: number }
  triage?: { tasks: SpaceTask[]; total: number }
}

/** Ключи здесь те же, что в `badge` пунктов `DOCS_VIEWS`. */
export function workCounts(input: WorkCountsInput): Record<string, number> {
  // Спрятанное человеком в числа не идёт: он его убрал с глаз, и счётчик,
  // считающий скрытое, спорит с самим смыслом отложения.
  const mine = (input.mine?.mine ?? []).filter((r) => !r.hidden)
  const по = (reason: string) => mine.filter((r) => r.reason === reason).length
  // `total` сервера, а не длина страницы: страница — это сто строк, и на малых
  // данных совпадение выглядело правильным ответом. Оба разреза отсекают
  // закрытое на сервере, поэтому доклеивать фильтр незачем.
  const всего = (r?: { tasks: SpaceTask[]; total: number }) =>
    r?.total ?? (r?.tasks ?? []).length

  return {
    hot: mine.filter((r) => r.bucket === 'overdue' || r.bucket === 'today').length,
    queue: mine.length,
    approvals: по('approve'),
    acquaints: по('acquaint'),
    // Экран «Поручений» показывает работу НА МНЕ (scope=mine). Прибавлять сюда
    // своё без исполнителя значит обещать в меню число, которого на экране нет.
    errands: по('do'),
    own: по('own'),
    assigned: всего(input.assigned),
    watching: всего(input.watching),
    starred: input.lists?.counts.starred ?? 0,
    deferred: input.lists?.counts.deferred ?? 0,
    // Просроченное — отдельное число: «12, из них 3 горят» это два разных
    // ответа, и одним числом они не заменяются.
    overdue: mine.filter((r) => r.overdue).length,
    triage: всего(input.triage),
  }
}
