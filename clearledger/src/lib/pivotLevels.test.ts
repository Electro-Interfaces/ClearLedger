/**
 * Перестановка уровней сводной.
 *
 * Порядок уровней — главная механика сводной: «владелец → регион» и «регион →
 * владелец» это два разных ответа. Перетаскивание мышью на неё полагаться не может
 * (на тач-экранах HTML5 drag&drop не работает вовсе), поэтому рядом со стрелками
 * стоит эта проверка: сдвиг на край не должен ни терять уровень, ни дублировать его.
 *
 * Прогон: node --test --experimental-strip-types src/lib/pivotLevels.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { reorderDims } from '../services/fuel/pivotTree.ts'

test('уровень переезжает на соседнюю позицию', () => {
  assert.deepEqual(reorderDims(['owner', 'region', 'power'], 1, 0),
    ['region', 'owner', 'power'])
  assert.deepEqual(reorderDims(['owner', 'region', 'power'], 1, 2),
    ['owner', 'power', 'region'])
})

test('сдвиг за край ничего не портит', () => {
  const уровни = ['owner', 'region']
  // Стрелка «выше» у первого и «ниже» у последнего выключены, но если жест всё же
  // дойдёт — состав обязан остаться прежним, а не потерять уровень.
  assert.deepEqual(reorderDims(уровни, 0, -1), уровни)
  assert.deepEqual(reorderDims(уровни, 1, 2), уровни)
  assert.deepEqual(reorderDims(уровни, 0, 0), уровни)
})

test('состав уровней не меняется при любой перестановке', () => {
  const уровни = ['owner', 'region', 'power', 'current']
  for (let из = 0; из < уровни.length; из += 1) {
    for (let в = 0; в < уровни.length; в += 1) {
      const вышло = reorderDims(уровни, из, в)
      assert.equal(вышло.length, уровни.length)
      assert.deepEqual([...вышло].sort(), [...уровни].sort())
    }
  }
})
