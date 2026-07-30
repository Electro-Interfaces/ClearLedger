/**
 * Дерево сводной таблицы - чистые функции без React.
 *
 * Сервер отдаёт только листья: агрегаты по НАБОРУ измерений. Иерархию, подытоги и
 * доли собирает браузер. Отсюда главное свойство: **перестановка уровней не идёт в
 * сеть**, те же листья пересобираются в другое дерево за миллисекунды.
 *
 * Доля считается **от родителя**, а не от общего итога: внутри АЗС виды топлива дают
 * 100 %, внутри топлива - способы оплаты. Так читается структура продаж, а доля от
 * общего итога на третьем уровне превращается в набор долей процента.
 *
 * Метрики не зашиты: узел держит их словарём. У реализаций это операции, литры и
 * выручка, у поступлений - массы по документу и факту с отклонением. Один и тот же
 * экран сводной работает над обоими, потому что складывает по ключам, а не по
 * заранее известным полям.
 */

/** Лист от сервера: значения измерений в порядке `dims` плюс метрики словарём. */
export interface PivotLeaf {
  keys: (string | null)[]
  m: Record<string, number>
}

export interface PivotNode {
  /** Путь узла с разделителем: `station=210¦fuel=ДТ`. Простая склейка слепила бы ветки. */
  path: string
  /** Ключ измерения этого уровня. */
  dim: string
  /** Сырое значение (для выгрузки и фильтров). */
  value: string | null
  /** Человеческая подпись. */
  label: string
  level: number
  /** Суммы метрик по поддереву. */
  m: Record<string, number>
  /** Доля метрики сортировки от родителя, 0..1. */
  share: number
  children: PivotNode[]
}

export type PivotTotals = Record<string, number>

const SEP = '¦'
export const PIVOT_PATH_SEP = SEP
export const EMPTY_LABEL = '— не указано —'

/** Подпись значения измерения: коды станций в имена, пустые в «не указано». */
export type PivotLabeler = (dim: string, value: string | null) => string

/**
 * Собрать дерево из листьев.
 *
 * `serverDims` - порядок значений в `keys` (как отдал сервер).
 * `displayDims` - порядок уровней на экране. Перестановка меняет только его.
 * `sortBy` - ключ метрики, по которой сортируются узлы и считаются доли.
 */
export function buildPivotTree(
  leaves: PivotLeaf[],
  serverDims: string[],
  displayDims: string[],
  sortBy: string,
  labeler: PivotLabeler,
): { nodes: PivotNode[]; totals: PivotTotals } {
  // Измерение, которого нет в ответе сервера, пропускаем: дерево должно пережить
  // рассинхрон конструктора и запроса, а не рухнуть.
  const order = displayDims
    .map((d) => ({ dim: d, idx: serverDims.indexOf(d) }))
    .filter((x) => x.idx >= 0)

  const totals: PivotTotals = {}
  const roots: PivotNode[] = []
  const index = new Map<string, PivotNode>()

  const addMetrics = (target: Record<string, number>, src: Record<string, number>) => {
    for (const k of Object.keys(src)) target[k] = (target[k] ?? 0) + (src[k] ?? 0)
  }

  for (const leaf of leaves) {
    addMetrics(totals, leaf.m)

    let parentPath = ''
    let siblings = roots
    for (let level = 0; level < order.length; level++) {
      const { dim, idx } = order[level]
      const value = leaf.keys[idx] ?? null
      const path = parentPath ? `${parentPath}${SEP}${dim}=${value ?? ''}` : `${dim}=${value ?? ''}`
      let node = index.get(path)
      if (!node) {
        node = { path, dim, value, label: labeler(dim, value), level, m: {}, share: 0, children: [] }
        index.set(path, node)
        siblings.push(node)
      }
      addMetrics(node.m, leaf.m)
      parentPath = path
      siblings = node.children
    }
  }

  sortTree(roots, sortBy)
  shareFromParent(roots, totals[sortBy] ?? 0, sortBy)
  return { nodes: roots, totals }
}

function sortTree(nodes: PivotNode[], sortBy: string): void {
  nodes.sort((a, b) => (b.m[sortBy] ?? 0) - (a.m[sortBy] ?? 0))
  for (const n of nodes) sortTree(n.children, sortBy)
}

/** Доля от родителя: сумма долей детей одного узла = 100 %. */
function shareFromParent(nodes: PivotNode[], parentValue: number, sortBy: string): void {
  for (const n of nodes) {
    const v = n.m[sortBy] ?? 0
    n.share = parentValue > 0 ? v / parentValue : 0
    shareFromParent(n.children, v, sortBy)
  }
}

/** Видимые строки: узел показывается, если все его предки развёрнуты. */
export function flattenVisible(nodes: PivotNode[], expanded: Set<string>): PivotNode[] {
  const out: PivotNode[] = []
  const walk = (list: PivotNode[]) => {
    for (const n of list) {
      out.push(n)
      if (n.children.length && expanded.has(n.path)) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

/** Все пути, которые вообще можно раскрыть (для кнопки «развернуть всё»). */
export function allExpandablePaths(nodes: PivotNode[]): string[] {
  const out: string[] = []
  const walk = (list: PivotNode[]) => {
    for (const n of list) {
      if (n.children.length) { out.push(n.path); walk(n.children) }
    }
  }
  walk(nodes)
  return out
}

/** Перестановка уровня. Возвращает НОВЫЙ массив: исходный не трогаем. */
export function reorderDims(dims: string[], from: number, to: number): string[] {
  if (from === to || from < 0 || to < 0 || from >= dims.length || to >= dims.length) return dims.slice()
  const next = dims.slice()
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

/** Плоские строки дерева для листа «Сводная» в Excel (с уровнем и подытогами). */
export function flattenAll(nodes: PivotNode[]): PivotNode[] {
  const out: PivotNode[] = []
  const walk = (list: PivotNode[]) => {
    for (const n of list) { out.push(n); walk(n.children) }
  }
  walk(nodes)
  return out
}
