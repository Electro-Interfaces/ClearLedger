// node --test --experimental-strip-types src/lib/workCounts.test.ts
// Импортируются только типы приложения, а они стираются при запуске: сборка и
// окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import { workCounts } from './workCounts.ts'

const строка = (p: Record<string, unknown> = {}) => ({
  kind: 'task', id: 'x', reason: 'do', reason_name: '', key: '№1', title: 'Работа',
  note: null, due_at: null, overdue: false, bucket: 'later', ...p,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any

test('поставленное и наблюдаемое считаются по total сервера, а не по странице', () => {
  // Страница — сто строк. Пока данных мало, длина совпадала с итогом, и
  // ошибку было не видно; у человека с сотней поручений окно и меню начинали
  // показывать разное под одним словом.
  const c = workCounts({
    assigned: { tasks: [строка(), строка()], total: 137 },
    watching: { tasks: [], total: 4 },
  })
  assert.equal(c.assigned, 137)
  assert.equal(c.watching, 4)
})

test('спрятанное человеком в числа не идёт', () => {
  const c = workCounts({
    mine: { mine: [строка(), строка({ hidden: true }), строка({ overdue: true })] },
  })
  assert.equal(c.queue, 2)
  assert.equal(c.overdue, 1)
})

test('разрезы очереди считаются по причине', () => {
  const c = workCounts({
    mine: { mine: [
      строка({ reason: 'approve' }), строка({ reason: 'approve' }),
      строка({ reason: 'acquaint' }), строка({ reason: 'do' }),
      строка({ reason: 'own' }),
    ] },
  })
  assert.deepEqual(
    { approvals: c.approvals, acquaints: c.acquaints, errands: c.errands, own: c.own },
    { approvals: 2, acquaints: 1, errands: 1, own: 1 })
})

test('«Сегодня» — просроченное и сегодняшнее вместе', () => {
  const c = workCounts({
    mine: { mine: [
      строка({ bucket: 'overdue' }), строка({ bucket: 'today' }),
      строка({ bucket: 'week' }), строка({ bucket: 'later' }),
    ] },
  })
  assert.equal(c.hot, 2)
})
