import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluate, pickResult } from './calc.ts'

test('калькулятор: порядок действий, скобки, запятая, проценты', () => {
  assert.equal(evaluate('2 + 3 × 4'), 14)
  assert.equal(evaluate('(1 + 2) × 3'), 9)
  assert.equal(evaluate('1,5 + 1,5'), 3)
  assert.equal(evaluate('-3 + 1'), -2)
  assert.equal(evaluate('100 + 5%'), 105)
  assert.equal(evaluate('100 − 10%'), 90)
  assert.equal(evaluate('200 × 5%'), 10)
  assert.equal(evaluate('50%'), 0.5)
  assert.equal(evaluate('2 +'), null)
  assert.equal(evaluate('1 ÷ 0'), null)
})

test('действие с выделенным: по порядку щелчков', () => {
  assert.equal(pickResult([10, 3, 2], 'sum'), 15)
  assert.equal(pickResult([10, 3, 2], 'sub'), 5)
  assert.equal(pickResult([10, 3, 2], 'mul'), 60)
  assert.equal(pickResult([12, 3, 2], 'div'), 2)
  assert.equal(pickResult([10, 0], 'div'), null)
  assert.equal(pickResult([10, 20], 'avg'), 15)
  assert.equal(pickResult([], 'sum'), null)
})
