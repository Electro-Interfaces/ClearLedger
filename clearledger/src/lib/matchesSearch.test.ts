/** Поиск по строке таблицы «Мониторинга»: слова запроса ищутся по всем полям строки. */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { matchesSearch } from './textUtils.ts'

describe('поиск по строке таблицы', () => {
  const строка = ['ТП 8244', '185', 'Омск', 'Омская область', 'на связи, энергии нет 44 дн']

  it('слова запроса — в разных полях', () => {
    assert.equal(matchesSearch('омск тп 82', строка), true)
  })
  it('знак номера и ё не мешают', () => {
    assert.equal(matchesSearch('№185', строка), true)
    assert.equal(matchesSearch('Березовка', ['Берёзовка']), true)
  })
  it('причина ищется', () => {
    assert.equal(matchesSearch('энергии нет', строка), true)
  })
  it('слово, которого нет, отсекает строку', () => {
    assert.equal(matchesSearch('омск хабаровск', строка), false)
  })
  it('пустые поля и пустой запрос', () => {
    assert.equal(matchesSearch('  ', [null, undefined]), true)
    assert.equal(matchesSearch('тп', [null, 'ТП 1']), true)
  })
})
