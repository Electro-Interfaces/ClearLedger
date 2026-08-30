/**
 * Подпись личного дня: три случая означают разное, и путать их нельзя.
 *
 * Главное, что проверяется, — перенос не называется просрочкой. Срок
 * принадлежит компании, личный план не принадлежит никому, кроме хозяина, и
 * несделанный вчера план не делает работу просроченной.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { planLabel, shortDay, todayKey } from './personalDay.ts'

const СЕГОДНЯ = '2026-08-30'

test('без плана подписи нет', () => {
  assert.equal(planLabel(null, СЕГОДНЯ), null)
  assert.equal(planLabel(undefined, СЕГОДНЯ), null)
  assert.equal(planLabel('', СЕГОДНЯ), null)
})

test('сегодняшний план — «в моём дне»', () => {
  assert.deepEqual(planLabel(СЕГОДНЯ, СЕГОДНЯ), { text: 'в моём дне', carried: false })
})

test('будущий план называет день', () => {
  const п = planLabel('2026-09-03', СЕГОДНЯ)
  assert.equal(п?.carried, false)
  assert.match(п?.text ?? '', /^на 3 сент/)
})

test('прошлый план — перенос, а не просрочка', () => {
  const п = planLabel('2026-08-28', СЕГОДНЯ)
  assert.equal(п?.carried, true, 'перенос обязан отличаться от плана на сегодня')
  assert.match(п?.text ?? '', /^с 28 авг/)
  assert.doesNotMatch(п?.text ?? '', /просроч/i,
    'личный перенос не имеет права называться просрочкой')
})

test('граница суток: вчера и завтра по разные стороны', () => {
  assert.equal(planLabel('2026-08-29', СЕГОДНЯ)?.carried, true)
  assert.equal(planLabel('2026-08-31', СЕГОДНЯ)?.carried, false)
})

test('todayKey даёт тот же вид, в каком хранится отметка', () => {
  assert.equal(todayKey(new Date(2026, 7, 3)), '2026-08-03')
  assert.match(todayKey(), /^\d{4}-\d{2}-\d{2}$/)
})

test('нечитаемую дату возвращаем как есть, а не «Invalid Date»', () => {
  assert.equal(shortDay('не-дата'), 'не-дата')
})
