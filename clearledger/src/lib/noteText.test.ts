// node --test --experimental-strip-types src/lib/noteText.test.ts
// Файл ничего не импортирует из приложения — сборка и окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import { nextEvening, nextMorning, toItems, toText } from './noteText.ts'

test('строки становятся пунктами, пустые выбрасываются', () => {
  assert.deepEqual(toItems('молоко\n\nхлеб\n  '), ['молоко', 'хлеб'])
})

test('маркер, набранный руками, не удваивается', () => {
  // Оставь дефис — и в готовом списке у каждого пункта будет второй маркер.
  assert.deepEqual(toItems('- молоко\n• хлеб\n— соль\n* сахар'),
    ['молоко', 'хлеб', 'соль', 'сахар'])
})

test('дефис внутри строки не трогаем', () => {
  assert.deepEqual(toItems('счёт-фактура на 5-е'), ['счёт-фактура на 5-е'])
})

test('пустой текст списка не даёт', () => {
  assert.deepEqual(toItems('\n  \n'), [])
})

test('превращение обратимо', () => {
  const исходный = 'молоко\nхлеб\nсоль'
  assert.equal(toText(toItems(исходный).map((text) => ({ text }))), исходный)
})

test('прежний текст остаётся первым', () => {
  // Список обычно вырастает ПОД записью: склеить наоборот значит перевернуть её.
  assert.equal(toText([{ text: 'молоко' }], 'Купить по дороге'),
    'Купить по дороге\nмолоко')
})

test('вечером — сегодня, пока не вечер', () => {
  const днём = new Date(2026, 7, 31, 11, 0)
  assert.equal(nextEvening(днём), '2026-08-31T18:00')
})

test('вечером после шести — завтрашний', () => {
  // Иначе кнопка мертва: напоминание в прошлое сервер молча не ставит.
  const вечером = new Date(2026, 7, 31, 19, 30)
  assert.equal(nextEvening(вечером), '2026-09-01T18:00')
})

test('ровно в шесть — уже завтрашний', () => {
  assert.equal(nextEvening(new Date(2026, 7, 31, 18, 0)), '2026-09-01T18:00')
})

test('завтра утром — всегда следующий день', () => {
  assert.equal(nextMorning(new Date(2026, 7, 31, 2, 0)), '2026-09-01T09:00')
  assert.equal(nextMorning(new Date(2026, 7, 31, 23, 0)), '2026-09-01T09:00')
})

test('конец месяца переваливает корректно', () => {
  assert.equal(nextMorning(new Date(2026, 11, 31, 10, 0)), '2027-01-01T09:00')
})
