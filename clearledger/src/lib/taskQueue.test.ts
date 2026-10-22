import test from 'node:test'
import assert from 'node:assert/strict'
import { consumeTaskDraft, taskDraft, taskDraftParams, taskQueueIsCompact,
  taskReportParams, taskReportScope } from './taskQueue.ts'

test('прямая ссылка и reload: исполнитель остаётся фильтром, форма не открывается', () => {
  const params = new URLSearchParams('view=registry&assignee=executor&q=счёт&sort=due')
  assert.equal(taskDraft(params), undefined)
  assert.equal(consumeTaskDraft(params).toString(), params.toString())
  assert.equal(taskDraft(new URLSearchParams(params)), undefined)
})

test('новая заготовка отделена от фильтра и потребляется один раз', () => {
  const params = taskDraftParams('  Проверить счёт  ', 'executor')
  params.set('assignee', 'filtered-person')
  params.set('q', 'счёт')
  assert.deepEqual(taskDraft(params), { title: 'Проверить счёт', assigneeId: 'executor' })
  const consumed = consumeTaskDraft(params)
  assert.equal(consumed.get('assignee'), 'filtered-person')
  assert.equal(consumed.get('q'), 'счёт')
  assert.equal(taskDraft(consumed), undefined)
  assert.equal(params.get('draft'), 'Проверить счёт', 'исходный URL не мутируется')
})

test('старый draft с исполнителем читается, но одиночный assignee не потребляется', () => {
  const legacy = new URLSearchParams('draft=Позвонить&assignee=executor&type=call')
  assert.deepEqual(taskDraft(legacy), { title: 'Позвонить', assigneeId: 'executor' })
  assert.equal(consumeTaskDraft(legacy).toString(), 'type=call')
  assert.equal(consumeTaskDraft(new URLSearchParams('assignee=executor')).get('assignee'), 'executor')
})

test('заготовка только с исполнителем имеет явный маркер, пустая не открывает форму', () => {
  const params = taskDraftParams('', 'executor')
  assert.equal(params.has('draft'), true)
  assert.deepEqual(taskDraft(params), { title: undefined, assigneeId: 'executor' })
  assert.equal(taskDraftParams('  ', '').size, 0)
  assert.equal(taskDraft(new URLSearchParams('draft=')), undefined)
})

const period = { from: '2026-10-01', to: '2026-10-22' }
test('Закрыто передаёт closed_at период, включая при фильтре по человеку/типу', () => {
  for (const filters of [{ scope: 'closed' }, { scope: 'closed', assignee: 'executor' },
    { scope: 'closed', type: 'call' }, { scope: 'closed', object: 'office' }]) {
    const params = taskReportParams(filters, period)
    assert.equal(taskReportScope(params), 'closed')
    assert.equal(params.get('closed_from'), period.from)
    assert.equal(params.get('closed_to'), period.to)
    assert.equal(params.has('date_from'), false, 'это не период постановки')
    assert.equal(params.get('assignee'), filters.assignee ?? null)
    assert.equal(params.get('type'), filters.type ?? null)
    assert.equal(taskDraft(params), undefined)
  }
})

test('открытые и просроченные — остаток на сейчас без сужения по периоду', () => {
  for (const scope of ['open', 'overdue', 'mine', 'triage', 'all']) {
    const params = taskReportParams({ scope, assignee: 'executor' }, period)
    assert.equal(taskReportScope(params), scope)
    assert.equal(params.has('closed_from'), false)
    assert.equal(params.has('closed_to'), false)
    assert.equal(params.get('assignee'), 'executor')
  }
  assert.equal(taskReportScope(new URLSearchParams('scope=invalid')), undefined)
})

test('ширина очереди учитывает обе полосы и минимум списка, включая resize', () => {
  for (const width of [320, 390, 664, 767, 768, 802]) {
    assert.equal(taskQueueIsCompact(width, 224, 320), true, `${width}px`)
  }
  assert.equal(taskQueueIsCompact(1280, 224, 320), false)
  assert.equal(taskQueueIsCompact(1440, 420, 560), false)
  assert.equal(taskQueueIsCompact(1100, 420, 560), true, 'широкие сохранённые полосы')
  assert.equal(taskQueueIsCompact(900, 160, 220), false, 'узкие полосы оставляют место')
})
