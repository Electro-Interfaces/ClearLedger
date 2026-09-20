/**
 * Разрешение имени станции: по чему её узнают в чужой форме.
 *
 * Прогон: node --test --experimental-strip-types src/lib/stationIndex.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { findStation, type StationLike } from './stationIndex.ts'

const сеть: StationLike[] = [
  { id: 'u-1', code: 'EZS-001', name: 'Чита, Ленина 5', metadata: { number: '42' } },
  { id: 'u-2', code: '17', name: 'Хабаровск, Муравьёва', metadata: { number: '0017' } },
  { id: 'u-3', code: 'EZS-003', name: 'Владивосток, Светланская', metadata: {} },
]

test('номер паспорта важнее кода: в выгрузках станция ходит номером', () => {
  assert.equal(findStation(сеть, '42')?.id, 'u-1')
})

test('ведущие нули не мешают', () => {
  assert.equal(findStation(сеть, '17')?.id, 'u-2')
  assert.equal(findStation(сеть, '0017')?.id, 'u-2')
})

test('код паспорта тоже узнаётся', () => {
  assert.equal(findStation(сеть, 'EZS-003')?.id, 'u-3')
  assert.equal(findStation(сеть, 'ezs-003')?.id, 'u-3', 'регистр не должен решать')
})

test('идентификатор — прямое попадание', () => {
  assert.equal(findStation(сеть, 'u-2')?.id, 'u-2')
})

test('название — последняя попытка', () => {
  assert.equal(findStation(сеть, 'Чита, Ленина 5')?.id, 'u-1')
})

test('номер поста в журнале сессий не мешает', () => {
  // «295-1» в журнале — это первый пост станции 295. Таких кодов у пилота 24 из
  // 479, а сессий за ними тысячи: без отсечения поста самые загруженные станции
  // Владивостока ссылкой не открывались.
  assert.equal(findStation(сеть, '42-1')?.id, 'u-1')
  assert.equal(findStation(сеть, '0017-2')?.id, 'u-2')
})

test('чужого не придумываем', () => {
  // Ссылка на несуществующий объект хуже её отсутствия: человек жмёт и попадает
  // в пустоту, а потом не верит и остальным ссылкам.
  assert.equal(findStation(сеть, '999'), null)
  assert.equal(findStation(сеть, ''), null)
  assert.equal(findStation(сеть, null), null)
  assert.equal(findStation([], '42'), null)
})
