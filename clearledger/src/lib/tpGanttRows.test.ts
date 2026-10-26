import test from 'node:test'
import assert from 'node:assert/strict'
import { tpGanttRows } from '../components/sites/tpGanttRows.ts'
import type { TechConnectionView } from '../services/techConnectionView.ts'
const now = Date.parse('2030-01-10T12:00:00Z')
const base = (): TechConnectionView => ({ enabled: true, scenario: 'Новое присоединение', branches: [], steps: [], overdue: false, deadlines: [], openRemarks: 0, stagesTotal: 0, stagesAccepted: 0, archived: false, syncedAt: null, error: null, nextWork: null })
test('отсутствующие факты не превращаются в интервалы', () => {
  const v = base();v.branches = [{ key: 'tp_connection', label: 'ТП', state: null, stage: {}, performer: null, due: null, overdue: false, steps: [], history: [] }]
  v.steps = [{ key: 'applied', no: '3.2', label: 'Заявка', branch: 'main', date: null, plannedDate: '2030-01-05', overdue: true }]
  const row = tpGanttRows(v, now, () => {})[0].rows[0]
  assert.deepEqual(row.segments, []);assert.equal(row.state, 'future');assert.equal(row.deadlineOverdue, true)
  assert.match(row.marks![0].title, /^План:/)
})
test('Гант сохраняет оба посещения стадии после возврата', () => {
  const v = base();v.branches = [{ key: 'tp_connection', label: 'ТП', state: 'running', stage: { code: 'grid' }, performer: { id: 'x', name: 'Энергетик' }, due: null, overdue: false,
    startedAt: '2030-01-01T00:00:00Z', steps: [{ code: 'grid', name: 'Сетевая', is_initial: true }, { code: 'correction', name: 'Дополнение' }],
    history: [{ from_code: 'grid', to_code: 'correction', at: '2030-01-03T00:00:00Z' }, { from_code: 'correction', to_code: 'grid', at: '2030-01-06T00:00:00Z' }] }]
  const rows = tpGanttRows(v, now, () => {})[0].rows
  assert.equal(rows[0].segments.length, 2);assert.equal(rows[0].segments[1].end, now)
  assert.equal(rows[1].segments.length, 1);assert.equal(rows[1].state, 'done')
})
test('ТП и сбыт остаются независимыми группами', () => {
  const v = base();v.branches = ['tp_connection', 'tp_supply'].map((key) => ({ key, label: key, state: null, stage: {}, performer: null, due: null, overdue: false, steps: [], history: [] }))
  v.steps = [{ key: 'applied', no: '3.2', label: 'Заявка ТП', branch: 'main', date: '2030-01-02', plannedDate: null, overdue: false }, { key: 'supply_applied', no: '8.3', label: 'Заявка сбыта', branch: 'supply', date: null, plannedDate: null, overdue: false }]
  const groups = tpGanttRows(v, now, () => {})
  assert.equal(groups.length, 2);assert.equal(groups[0].rows[0].state, 'done');assert.equal(groups[1].rows[0].state, 'future')
})
test('ознакомление завершается датой последнего получателя', () => {
  const v = base();v.handover = { exists: true, done: true, createdAt: '2030-01-02T00:00:00Z', recipients: [{ id: '1', name: 'Контролирующий', status: 'done', readAt: '2030-01-05T00:00:00Z' }] }
  const row = tpGanttRows(v, now, () => {})[0].rows[0]
  assert.equal(row.state, 'done');assert.equal(row.segments[0].end, Date.parse('2030-01-05T00:00:00Z'))
})

test('у завершённого ознакомления без даты нет выдуманной полосы до сегодня', () => {
  const v = base();v.handover = { exists: true, done: true, createdAt: '2030-01-02T00:00:00Z', recipients: [{ id: '1', name: 'Контролирующий', status: 'done', readAt: null }] }
  const row = tpGanttRows(v, now, () => {})[0].rows[0]
  assert.equal(row.state, 'done');assert.deepEqual(row.segments, [])
})
