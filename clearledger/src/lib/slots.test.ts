// node --test --experimental-strip-types src/lib/slots.test.ts
// Файл ничего не импортирует из приложения — сборка и окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import { findSlots, inWorkWindow, localParts, minutesOf, type Person } from './slots.ts'

const МСК = 'Europe/Moscow'
const ВВО = 'Asia/Vladivostok'

/** Понедельник 31 августа 2026. Время задаём в UTC — так же, как приходит с сервера. */
const utc = (h: number, m = 0) => new Date(Date.UTC(2026, 7, 31, h, m))

const человек = (over: Partial<Person> = {}): Person => ({
  user_id: 'a', name: 'А', tz: МСК, work_start: '09:00', work_end: '18:00',
  busy: [], ...over,
})

test('время читается в поясе человека, а не сервера', () => {
  // 02:00 UTC — 05:00 в Москве и 12:00 во Владивостоке.
  assert.equal(localParts(utc(2), МСК).minutes, 5 * 60)
  assert.equal(localParts(utc(2), ВВО).minutes, 12 * 60)
})

test('мусор в настройке не роняет подбор', () => {
  assert.equal(minutesOf('', 540), 540)
  assert.equal(minutesOf('девять', 540), 540)
  assert.equal(minutesOf('09:30', 540), 570)
})

test('встреча обязана помещаться в окно целиком', () => {
  // 17:30–18:30 по Москве: начало в окне, конец — нет. Это не «успел», это
  // «остался после работы».
  const p = человек()
  assert.equal(inWorkWindow(utc(14, 30), utc(15, 30), p), false)
  assert.equal(inWorkWindow(utc(13), utc(14), p), true)
})

test('выходной — не рабочее окно', () => {
  // Суббота 29 августа, полдень по Москве.
  const сб = new Date(Date.UTC(2026, 7, 29, 9))
  const до = new Date(Date.UTC(2026, 7, 29, 10))
  assert.equal(inWorkWindow(сб, до, человек()), false)
})

test('общее окно Москвы и Владивостока — узкое', () => {
  // У Владивостока 09:00–18:00 это 23:00–08:00 UTC вчера-сегодня, у Москвы —
  // 06:00–15:00 UTC. Пересечение: 06:00–08:00 UTC, то есть 09:00–11:00 по Москве
  // и 16:00–18:00 по Владивостоку.
  const мск = человек({ user_id: 'm', name: 'Москва', tz: МСК })
  const ввл = человек({ user_id: 'v', name: 'Владивосток', tz: ВВО })
  const слоты = findSlots({
    people: [мск, ввл], requiredIds: ['m', 'v'],
    from: utc(0), to: utc(23), minutes: 60,
  })
  assert.ok(слоты.length > 0, 'общее окно должно найтись')
  for (const s of слоты) {
    const час = new Date(s.at).getUTCHours()
    assert.ok(час >= 6 && час < 8, `кандидат в ${час}:00 UTC вне общего окна`)
  }
})

test('занятость обязательного участника выбрасывает кандидата', () => {
  const занят = человек({
    busy: [{ starts_at: utc(7).toISOString(), ends_at: utc(9).toISOString() }],
  })
  const слоты = findSlots({
    people: [занят], requiredIds: ['a'], from: utc(6), to: utc(12), minutes: 60,
  })
  for (const s of слоты) {
    const t = new Date(s.at).getTime()
    assert.ok(t + 3600_000 <= utc(7).getTime() || t >= utc(9).getTime(),
      'кандидат наложился на занятость')
  }
})

test('необязательный отбор не проваливает, но виден', () => {
  const главный = человек({ user_id: 'a', name: 'А' })
  const гость = человек({
    user_id: 'b', name: 'Б',
    busy: [{ starts_at: utc(7).toISOString(), ends_at: utc(8).toISOString() }],
  })
  const слоты = findSlots({
    people: [главный, гость], requiredIds: ['a'],
    from: utc(7), to: utc(9), minutes: 60,
  })
  const первый = слоты.find((s) => new Date(s.at).getTime() === utc(7).getTime())
  assert.ok(первый, 'кандидат не должен пропасть из-за необязательного')
  assert.deepEqual(первый!.busyOptional, ['Б'])
})

test('кандидаты встают на ровные получасы', () => {
  const слоты = findSlots({
    people: [человек()], requiredIds: ['a'],
    from: new Date(Date.UTC(2026, 7, 31, 6, 7)), to: utc(12), minutes: 60,
  })
  for (const s of слоты) {
    assert.equal(new Date(s.at).getUTCMinutes() % 30, 0)
  }
})

test('без обязательных участников кандидатов нет', () => {
  // Иначе «найти время» ответило бы любым часом суток, ничего не проверив.
  assert.deepEqual(findSlots({
    people: [человек()], requiredIds: [], from: utc(6), to: utc(12), minutes: 60,
  }), [])
})

test('нулевая длительность не порождает бесконечность', () => {
  assert.deepEqual(findSlots({
    people: [человек()], requiredIds: ['a'], from: utc(6), to: utc(12), minutes: 0,
  }), [])
})
