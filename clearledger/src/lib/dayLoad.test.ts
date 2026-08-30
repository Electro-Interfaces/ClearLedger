/**
 * Нагрузка дня: строка ничего не двигает, но и врать не имеет права.
 *
 * Главное, что здесь проверяется, — пересечения не удваивают занятость. Две
 * встречи, наложенные друг на друга, отнимают у дня один раз: человек всё
 * равно проживёт этот час однажды, и «занято 4 ч» при двухчасовом наложении
 * сделало бы подсказку поводом ей не верить.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { dayLoad, minutesOf, часы } from './dayLoad.ts'

const ДЕНЬ = new Date(2026, 7, 31)
const в = (ч: number, м = 0) =>
  new Date(2026, 7, 31, ч, м).toISOString()

test('пустой день — говорить не о чем', () => {
  const н = dayLoad([], 0, ДЕНЬ)
  assert.equal(н.text, null)
  assert.equal(н.занято, 0)
})

test('одна встреча: занято и свободно сходятся с окном', () => {
  const н = dayLoad([{ starts_at: в(10), ends_at: в(12) }], 0, ДЕНЬ)
  assert.equal(н.занято, 2)
  assert.equal(н.свободно, 7, 'окно 9–18 минус два часа встречи')
  assert.match(н.text ?? '', /встречи 2 ч/)
  assert.match(н.text ?? '', /свободно 7 ч/)
})

test('пересечение считается один раз', () => {
  const н = dayLoad([
    { starts_at: в(10), ends_at: в(12) },
    { starts_at: в(11), ends_at: в(13) },
  ], 0, ДЕНЬ)
  assert.equal(н.занято, 3, 'с 10 до 13 — три часа, а не четыре')
})

test('вложенная встреча не добавляет времени', () => {
  const н = dayLoad([
    { starts_at: в(10), ends_at: в(14) },
    { starts_at: в(11), ends_at: в(12) },
  ], 0, ДЕНЬ)
  assert.equal(н.занято, 4)
})

test('всёдневная и отменённая часов не отнимают', () => {
  const н = dayLoad([
    { starts_at: в(0), ends_at: в(23, 59), all_day: true },
    { starts_at: в(10), ends_at: в(12), status: 'cancelled' },
  ], 0, ДЕНЬ)
  assert.equal(н.занято, 0, 'отпуск и отменённое время не занимают')
})

test('встреча вне рабочего окна обрезается по окну', () => {
  const н = dayLoad([{ starts_at: в(7), ends_at: в(10) }], 0, ДЕНЬ)
  assert.equal(н.занято, 1, 'до девяти рабочего окна нет — считается только час')
})

test('свои рабочие часы уважаются', () => {
  const н = dayLoad([], 1, ДЕНЬ, '08:00', '20:00')
  assert.equal(н.свободно, 12)
  assert.match(н.text ?? '', /намечено дел: 1/)
})

test('день, забитый встречами, говорит об этом прямо', () => {
  const н = dayLoad([{ starts_at: в(9), ends_at: в(18) }], 3, ДЕНЬ)
  assert.equal(н.перегруз, true)
  assert.match(н.text ?? '', /свободного времени не осталось/)
})

test('свободное не уходит в минус', () => {
  const н = dayLoad([{ starts_at: в(6), ends_at: в(23) }], 0, ДЕНЬ)
  assert.ok(н.свободно >= 0, 'отрицательный запас времени не бывает')
})

test('нечитаемые рабочие часы падают на девять-восемнадцать', () => {
  assert.equal(minutesOf('99:99', 540), 540)
  assert.equal(minutesOf(null, 540), 540)
  assert.equal(minutesOf('08:30', 540), 510)
})

test('часы пишутся по-русски, с запятой', () => {
  assert.equal(часы(150), '2,5 ч')
  assert.equal(часы(120), '2 ч')
})
