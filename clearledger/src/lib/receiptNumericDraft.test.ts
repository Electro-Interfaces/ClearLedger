import test from 'node:test'
import assert from 'node:assert/strict'
import { parseReceiptNumber, removeReceiptNumericDraft } from './receiptNumericDraft.ts'

test('пустое, промежуточное и неверное число не становятся нулём', () => {
  for (const input of ['', ' ', '1e', '1e-', '-', 'NaN', 'Infinity', '1,2,3', 'abc', '0x12', '-1', '1000000001']) {
    assert.equal(parseReceiptNumber(input), null, input)
  }
  assert.equal(parseReceiptNumber('0'), 0)
})

test('приёмка принимает десятичную запятую, дроби и законченный exponent', () => {
  for (const [input, value] of [['1,5', 1.5], ['.5', 0.5], [' 9 ', 9], ['1e2', 100], ['1000000000', 1e9]] as const) {
    assert.equal(parseReceiptNumber(input), value)
  }
})

test('удаление строки не переносит её ошибку на соседний товар', () => {
  const source = { 0: { price: '' }, 1: { qty_fact: '1e' }, 3: { price: '5,5' } }
  assert.deepEqual(removeReceiptNumericDraft(source, 1), { 0: { price: '' }, 2: { price: '5,5' } })
  assert.deepEqual(removeReceiptNumericDraft(source, 0), { 0: { qty_fact: '1e' }, 2: { price: '5,5' } })
  assert.equal(source[1].qty_fact, '1e')
})
