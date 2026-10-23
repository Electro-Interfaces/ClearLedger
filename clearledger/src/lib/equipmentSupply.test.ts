import { test } from 'node:test'
import assert from 'node:assert/strict'
import { supplyLinesValid, supplyLinePayload } from '../components/equipment/supplyValidation.ts'

test('экземпляры целые, материалы допускают дробное количество', () => {
  assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'station', qtyPlanned: 1 }]), true)
  assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'station', qtyPlanned: 1.5 }]), false)
  assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'spare', partId: 'material', qtyPlanned: 0.125 }]), true)
})

for (const unitPrice of [-1, NaN, Infinity]) {
  test(`неверная цена ${unitPrice} блокирует сохранение спецификации`, () => {
    assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'station', qtyPlanned: 1, unitPrice }]), false)
  })
}

test('бесплатная поставка допустима, ЗИП требует выбранную номенклатуру', () => {
  assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'station', qtyPlanned: 1, unitPrice: 0 }]), true)
  assert.equal(supplyLinesValid([{ _key: 1, lineKind: 'spare', qtyPlanned: 1 }]), false)
})

test('служебные ключи формы не заменяют реквизиты строки поставки', () => {
  assert.deepEqual(supplyLinePayload({ _key: 7, id: 'ui-row', locked: false, lineKind: 'spare',
    partId: 'material', qtyPlanned: 2.5, unitPrice: 0, vatRate: '0%' }),
  { lineKind: 'spare', partId: 'material', qtyPlanned: 2.5, unitPrice: 0, vatRate: '0%' })
})
