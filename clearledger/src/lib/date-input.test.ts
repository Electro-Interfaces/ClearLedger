/**
 * Разбор набранного руками: `npm run test:unit`
 *
 * Тест здесь потому, что ошибка разбора не падает, а молча ставит встречу не на тот день:
 * «31.02» превращается в 3 марта, «26» в 1926 год, «930» в 93 часа. Человек этого не
 * видит — он уже перешёл к участникам.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import { dateToText, textToDate, textToTime } from './date-input.ts'

const base = new Date(2026, 8, 16)   // 16.09.2026 — «текущий» год для коротких форм

test('дата: цифрами, с разделителями и без', () => {
  assert.equal(textToDate('17.09.2026'), '2026-09-17')
  assert.equal(textToDate('17092026'), '2026-09-17')
  assert.equal(textToDate('1709', base), '2026-09-17')      // год из текущего
  assert.equal(textToDate('17.09.26'), '2026-09-17')        // две цифры года — это 20xx
  assert.equal(textToDate('01.01.2027'), '2027-01-01')
})

test('дата: незаконченное и несуществующее не проходит', () => {
  assert.equal(textToDate(''), null)
  assert.equal(textToDate('17'), null)                      // ещё печатает
  assert.equal(textToDate('170'), null)
  assert.equal(textToDate('31.02.2026'), null)              // 3 марта молча не подставляем
  assert.equal(textToDate('32.01.2026'), null)
  assert.equal(textToDate('17.13.2026'), null)
})

test('дата: обратно в текст', () => {
  assert.equal(dateToText('2026-09-17'), '17.09.2026')
  assert.equal(dateToText(''), '')
  assert.equal(dateToText('мусор'), '')
})

test('время: короткие формы', () => {
  assert.equal(textToTime('930'), '09:30')
  assert.equal(textToTime('9'), '09:00')
  assert.equal(textToTime('17'), '17:00')
  assert.equal(textToTime('1745'), '17:45')
  assert.equal(textToTime('09:05'), '09:05')
  assert.equal(textToTime('0'), '00:00')
})

test('время: невозможное не проходит', () => {
  assert.equal(textToTime(''), null)
  assert.equal(textToTime('25'), null)
  assert.equal(textToTime('1265'), null)
  assert.equal(textToTime('99:99'), null)
})
