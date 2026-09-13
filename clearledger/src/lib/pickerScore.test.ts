/**
 * Поиск в списках выбора: по одной букве не должен показывать весь справочник.
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { pickerScore } from './pickerScore.ts'

describe('вес строки при поиске', () => {
  it('по букве «м» находит Михеева, а не Кашеварова Владимировича', () => {
    assert.ok(pickerScore('Михеев Андрей Геннадьевич', 'м') > 0)
    assert.ok(pickerScore('Марков Антон Александрович', 'м') > 0)
    assert.equal(pickerScore('Кашеваров Антон Владимирович', 'м'), 0)
    assert.equal(pickerScore('Администратор', 'м'), 0)
  })

  it('фамилия важнее имени: начало строки выше начала слова', () => {
    assert.ok(pickerScore('Марков Антон', 'мар') > pickerScore('Демьянова Мария', 'мар'))
  })

  it('с трёх букв ищет и внутри слова — «иров» находит Чурилова', () => {
    assert.ok(pickerScore('Чурилов Леонид', 'илов') > 0)
    assert.equal(pickerScore('Чурилов Леонид', 'ур').toFixed(0), '0')
  })

  it('пустой запрос оставляет список целым', () => {
    assert.equal(pickerScore('кто угодно', '  '), 1)
  })
})
