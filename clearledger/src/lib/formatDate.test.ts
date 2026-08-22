// node --test --experimental-strip-types src/lib/formatDate.test.ts
// Файл ничего не импортирует из приложения — сборка и окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import { formatDate, formatDateTime, formatPeriod, formatBucket, formatMonth } from './formatDate.ts'

test('одиночная дата — DD.MM.YYYY', () => {
  assert.equal(formatDate('2026-08-22'), '22.08.2026')
  assert.equal(formatDate('2026-08-22T15:40:00Z'), '22.08.2026')
})

test('голая дата не съезжает на день назад', () => {
  // '2026-08-22' по стандарту = полночь UTC. В поясе западнее Гринвича это
  // 21 августа по местному времени, и срок документа показывался бы на день раньше.
  const tz = process.env.TZ
  process.env.TZ = 'America/New_York'
  try {
    assert.equal(formatDate('2026-08-22'), '22.08.2026')
  } finally {
    process.env.TZ = tz
  }
})

test('период — словом, год один раз при совпадении', () => {
  assert.equal(formatPeriod('2026-08-15', '2026-08-22'), '15 авг – 22 авг 2026')
  assert.equal(formatPeriod('2025-12-30', '2026-01-02'), '30 дек 2025 – 2 янв 2026')
})

test('подпись оси: день без года, месяц с коротким годом', () => {
  assert.equal(formatBucket('2026-07-15'), '15 июл')
  assert.equal(formatBucket('2026-01'), 'янв 26')
  assert.equal(formatMonth('2026-09'), 'сен 2026')
})

test('неразбираемое значение возвращается как есть', () => {
  assert.equal(formatDate('без даты'), 'без даты')
  assert.equal(formatDateTime(''), '')
})
