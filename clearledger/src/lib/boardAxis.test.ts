// node --test --experimental-strip-types src/lib/boardAxis.test.ts
// Файл ничего не импортирует из приложения — сборка и окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import { columnOf, type BoardHorizon, type BoardItem } from './boardAxis.ts'

const горизонт: BoardHorizon = {
  today: '2026-08-29',
  tomorrow: '2026-08-30',
  weekEnd: '2026-08-30',
  lists: new Set(['aaa', 'bbb']),
}

const предмет = (p: Partial<BoardItem> = {}): BoardItem => ({
  state: 'in_work', due_at: null, overdue: false, ...p,
})

const отметка = (p: Partial<NonNullable<BoardItem['mark']>> = {}) => ({
  list_id: null, taken_for: null, deferred_until: null, ...p,
})

test('ось состояния — это само состояние, без правил', () => {
  assert.equal(columnOf('state', предмет({ state: 'approval' }), горизонт), 'approval')
})

test('раскладка: спрятанное старше дня и подборки', () => {
  // Иначе отложенная работа продолжает стоять в подборке, и «отложить»
  // перестаёт что-либо значить.
  const m = отметка({ deferred_until: '2026-09-05', taken_for: '2026-08-29', list_id: 'aaa' })
  assert.equal(columnOf('place', предмет({ mark: m }), горизонт), 'deferred')
})

test('раскладка: вчерашнее сокрытие уже не прячет', () => {
  const m = отметка({ deferred_until: '2026-08-29', list_id: 'aaa' })
  assert.equal(columnOf('place', предмет({ mark: m }), горизонт), 'list:aaa')
})

test('раскладка: день старше подборки', () => {
  const m = отметка({ taken_for: '2026-08-29', list_id: 'aaa' })
  assert.equal(columnOf('place', предмет({ mark: m }), горизонт), 'day')
})

test('раскладка: вчерашний день — уже не мой день', () => {
  const m = отметка({ taken_for: '2026-08-28' })
  assert.equal(columnOf('place', предмет({ mark: m }), горизонт), 'loose')
})

test('раскладка: отметка на удалённую подборку не уносит карточку в никуда', () => {
  const m = отметка({ list_id: 'ccc' })
  assert.equal(columnOf('place', предмет({ mark: m }), горизонт), 'loose')
})

test('раскладка: неразложенное и звезда сама по себе — «Не разложено»', () => {
  assert.equal(columnOf('place', предмет(), горизонт), 'loose')
  assert.equal(columnOf('place', предмет({ mark: отметка() }), горизонт), 'loose')
})

test('срок: просрочка старше всего, кроме отсутствия срока', () => {
  assert.equal(columnOf('due', предмет({ due_at: '2026-08-29T09:00:00Z', overdue: true }),
    горизонт), 'overdue')
  assert.equal(columnOf('due', предмет({ overdue: true }), горизонт), 'none')
})

test('срок: сегодня, завтра, неделя, позже', () => {
  const н = (d: string, overdue = false) => columnOf('due',
    предмет({ due_at: `${d}T18:00:00Z`, overdue }), горизонт)
  assert.equal(н('2026-08-29'), 'today')
  assert.equal(н('2026-08-30'), 'tomorrow')
  assert.equal(н('2026-09-01'), 'later')
})

test('срок: конец недели дальше завтра — граница попадает в «неделю»', () => {
  const далеко: BoardHorizon = { ...горизонт, tomorrow: '2026-08-30', weekEnd: '2026-09-06' }
  const н = (d: string) => columnOf('due', предмет({ due_at: `${d}T18:00:00Z` }), далеко)
  assert.equal(н('2026-09-06'), 'week')
  assert.equal(н('2026-09-07'), 'later')
})

test('каждый предмет попадает ровно в одну колонку', () => {
  // Главное свойство доски, и проверять его надо перебором: правило старшинства
  // ломается молча — карточка либо двоится, либо исчезает.
  const колонкиРаскладки = ['day', 'list:aaa', 'list:bbb', 'loose', 'deferred']
  const колонкиСрока = ['overdue', 'today', 'tomorrow', 'week', 'later', 'none']
  const случаи: BoardItem[] = []
  for (const deferred_until of [null, '2026-08-28', '2026-09-05']) {
    for (const taken_for of [null, '2026-08-28', '2026-08-29']) {
      for (const list_id of [null, 'aaa', 'ccc']) {
        случаи.push(предмет({ mark: отметка({ deferred_until, taken_for, list_id }) }))
      }
    }
  }
  for (const i of случаи) {
    assert.equal(колонкиРаскладки.filter((c) => columnOf('place', i, горизонт) === c).length, 1)
  }
  for (const due_at of [null, '2026-08-20T18:00:00Z', '2026-08-29T18:00:00Z',
    '2026-08-30T18:00:00Z', '2026-09-30T18:00:00Z']) {
    for (const overdue of [false, true]) {
      const i = предмет({ due_at, overdue })
      assert.equal(колонкиСрока.filter((c) => columnOf('due', i, горизонт) === c).length, 1)
    }
  }
})
