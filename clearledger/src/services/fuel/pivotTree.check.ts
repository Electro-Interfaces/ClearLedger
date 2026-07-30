/**
 * Самопроверка дерева сводной. Запуск (тест-раннера в проекте нет, тащить его ради
 * одного файла не стали):
 *
 *   npx esbuild src/services/fuel/pivotTree.check.ts --bundle --platform=node --format=cjs | node
 *
 * Проверяем ровно то, что ломается молча: подытоги против общего итога, доли от
 * родителя, независимость итогов от порядка уровней, устойчивость к чужому измерению
 * и чистоту `reorderDims`.
 */
import {
  allExpandablePaths, buildPivotTree, flattenVisible, reorderDims,
  type PivotLeaf, type PivotNode,
} from './pivotTree'

const eq = (a: unknown, b: unknown, msg: string) => {
  const x = JSON.stringify(a), y = JSON.stringify(b)
  if (x !== y) throw new Error(`${msg}: ${x} != ${y}`)
}
const near = (a: number, b: number, msg: string) => {
  if (Math.abs(a - b) > 1e-6) throw new Error(`${msg}: ${a} != ${b}`)
}

const DIMS = ['station', 'fuel', 'payment']
const leaves: PivotLeaf[] = [
  { keys: ['210', 'ДТ', 'Наличные'], ops: 10, liters: 300, amount: 20000 },
  { keys: ['210', 'ДТ', 'Карта'], ops: 5, liters: 150, amount: 10000 },
  { keys: ['210', 'АИ-95', 'Наличные'], ops: 4, liters: 80, amount: 5000 },
  { keys: ['211', 'ДТ', 'Карта'], ops: 1, liters: 40, amount: 2500 },
  { keys: ['211', null, 'Карта'], ops: 2, liters: 20, amount: 1500 },
]
const labeler = (dim: string, v: string | null) =>
  v === null || v === '' ? '— не указано —' : dim === 'station' ? `АЗС ${v}` : v

// 1. Подытоги сходятся с общим итогом на каждом уровне
const { nodes, totals } = buildPivotTree(leaves, DIMS, DIMS, 'amount', labeler)
eq(totals, { ops: 22, liters: 590, amount: 39000 }, 'общий итог')
near(nodes.reduce((s, n) => s + n.amount, 0), totals.amount, 'сумма первого уровня')
const walkCheck = (list: PivotNode[]) => {
  for (const n of list) {
    if (n.children.length) {
      near(n.children.reduce((s, c) => s + c.amount, 0), n.amount, `подытог ${n.path}`)
      near(n.children.reduce((s, c) => s + c.liters, 0), n.liters, `литры ${n.path}`)
      near(n.children.reduce((s, c) => s + c.ops, 0), n.ops, `операции ${n.path}`)
      walkCheck(n.children)
    }
  }
}
walkCheck(nodes)

// 2. Доли считаются ОТ РОДИТЕЛЯ: у детей одного узла сумма долей = 1
near(nodes.reduce((s, n) => s + n.share, 0), 1, 'доли верхнего уровня')
for (const n of nodes) {
  if (n.children.length) near(n.children.reduce((s, c) => s + c.share, 0), 1, `доли внутри ${n.path}`)
}

// 3. Перестановка уровней не меняет итог (в сеть за этим ходить незачем)
const swapped = buildPivotTree(leaves, DIMS, ['payment', 'station', 'fuel'], 'amount', labeler)
eq(swapped.totals, totals, 'итог после перестановки')

// 4. Путь узла с разделителем: ветки не склеиваются
const paths = allExpandablePaths(nodes)
if (!paths.every((p) => p.split('¦').length <= 2)) throw new Error('глубина путей')
if (new Set(paths).size !== paths.length) throw new Error('пути не уникальны')

// 5. Чужое измерение отбрасывается, а не рушит дерево
const withUnknown = buildPivotTree(leaves, DIMS, ['station', 'nonexistent', 'fuel'], 'amount', labeler)
near(withUnknown.totals.amount, totals.amount, 'итог с чужим измерением')
if (withUnknown.nodes[0].children[0].dim !== 'fuel') throw new Error('чужое измерение не пропущено')

// 6. Пустое значение получает подпись, а не null
const empty = buildPivotTree(leaves, DIMS, ['fuel'], 'amount', labeler)
if (!empty.nodes.some((n) => n.label === '— не указано —')) throw new Error('пустое значение без подписи')

// 7. reorderDims не мутирует исходный массив
const src = ['a', 'b', 'c']
const moved = reorderDims(src, 0, 2)
eq(src, ['a', 'b', 'c'], 'исходный массив не тронут')
eq(moved, ['b', 'c', 'a'], 'перестановка')

// 8. Видимые строки: без раскрытия виден только первый уровень
eq(flattenVisible(nodes, new Set()).length, nodes.length, 'свёрнутое дерево')
const firstExpanded = flattenVisible(nodes, new Set([nodes[0].path]))
eq(firstExpanded.length, nodes.length + nodes[0].children.length, 'раскрыт один узел')

// 9. Сортировка по метрике на каждом уровне
const byLiters = buildPivotTree(leaves, DIMS, DIMS, 'liters', labeler)
for (let i = 1; i < byLiters.nodes.length; i++) {
  if (byLiters.nodes[i - 1].liters < byLiters.nodes[i].liters) throw new Error('сортировка уровня 1')
}

console.log('pivotTree: все проверки прошли')
