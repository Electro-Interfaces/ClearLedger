import test from 'node:test'
import assert from 'node:assert/strict'
import { clampTaskDefer, selectedTaskType, taskDueDay } from './taskCardInput.ts'

test('явный none переживает загрузку default и восстановление JSON-черновика', () => {
  const draft = JSON.parse(JSON.stringify({ typeId: 'none' }))
  assert.equal(selectedTaskType(draft.typeId, ''), '')
  assert.equal(selectedTaskType(draft.typeId, 'general'), '')
  assert.equal(selectedTaskType('', 'general'), 'general')
  assert.equal(selectedTaskType('project-type', 'general'), 'project-type')
  assert.equal(selectedTaskType('', ''), '')
})

test('местный день не теряется при roundtrip UTC, включая границы года', () => {
  for (const day of ['2026-10-30', '2027-01-01', '2026-03-29', '2026-10-25']) {
    for (const time of ['00:00', '00:30', '23:59']) {
      assert.equal(taskDueDay(new Date(`${day}T${time}`).toISOString()), day)
    }
  }
  assert.equal(taskDueDay('2026-10-30'), '2026-10-30')
  assert.equal(taskDueDay(null), '')
  assert.equal(taskDueDay('bad'), '')
})

test('сокрытие за срок ограничено тем же местным днём', () => {
  const due = new Date('2026-10-25T00:00').toISOString()
  assert.equal(clampTaskDefer('2026-10-26', due), '2026-10-25')
  assert.equal(clampTaskDefer('2026-10-25', due), '2026-10-25')
  assert.equal(clampTaskDefer('2026-10-24', due), '2026-10-24')
  assert.equal(clampTaskDefer('2026-10-26', null), '2026-10-26')
})

test('пояс профиля задаёт личную границу даже при другом поясе браузера', () => {
  const due = '2026-10-24T21:00:00Z'
  assert.equal(clampTaskDefer('2026-10-26', due, 'Europe/Moscow'), '2026-10-25')
  assert.equal(clampTaskDefer('2026-10-26', due, 'America/Los_Angeles'), '2026-10-24')
  assert.equal(clampTaskDefer('2026-10-26', due, 'invalid/timezone'), '2026-10-25')
})
