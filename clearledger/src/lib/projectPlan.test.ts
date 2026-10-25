import { test } from 'node:test'
import assert from 'node:assert/strict'
import { inWork, nextStepDue, nextStepText, planBuckets } from './projectPlan.ts'

const row = (p: Partial<Parameters<typeof planBuckets>[0][number]> & { stage?: string } = {}) => ({
  stage: 'lead', kind: 'new_build', closedOn: null,
  nextAction: null, nextActionDue: null, ...p,
})

test('в работе — живая воронка без заморозки, архива и интеграции', () => {
  assert.equal(inWork(row()), true)
  assert.equal(inWork(row({ stage: 'on_hold' })), false)
  assert.equal(inWork(row({ stage: 'archive' })), false)
  assert.equal(inWork(row({ kind: 'integration' })), false)
  assert.equal(inWork(row({ closedOn: '2026-10-01' })), false)
})

test('срок без текста шага не удваивает строку между группами', () => {
  const строки = [
    row({ nextActionDue: '2026-10-06' }),               // просрочен, текста шага нет
    row({ nextAction: 'Позвонить', nextActionDue: null }),
    row(),                                               // ни шага, ни срока
  ]
  const buckets = planBuckets(строки, '2026-10-25', '2026-11-01')
  const всего = buckets.reduce((a, b) => a + b.items.length, 0)
  assert.equal(всего, строки.length, 'строк в группах столько же, сколько проектов')
  assert.deepEqual(buckets.map((b) => b.key), ['overdue', 'nodate', 'nostep'])
  assert.equal(buckets.find((b) => b.key === 'nostep')!.items.length, 1)
})

test('группы по датам разводят просрочку, сегодня, неделю и дальше', () => {
  const buckets = planBuckets([
    row({ nextAction: 'а', nextActionDue: '2026-10-24' }),
    row({ nextAction: 'б', nextActionDue: '2026-10-25' }),
    row({ nextAction: 'в', nextActionDue: '2026-10-28' }),
    row({ nextAction: 'г', nextActionDue: '2026-12-01' }),
  ], '2026-10-25', '2026-11-01')
  assert.deepEqual(buckets.map((b) => [b.key, b.items.length]),
    [['overdue', 1], ['today', 1], ['week', 1], ['later', 1]])
})

test('шаг строки берётся из карточки, ручное поле — запасное', () => {
  assert.equal(nextStepText({ nextStep: 'Ожидание: ответ сетевой', nextAction: null }), 'Ожидание: ответ сетевой')
  assert.equal(nextStepDue({ nextStepDue: '2026-10-30', nextActionDue: null }), '2026-10-30')
  assert.equal(nextStepText({ nextAction: 'Позвонить' }), 'Позвонить')
  assert.equal(nextStepDue({ nextActionDue: '2026-11-02' }), '2026-11-02')
  assert.equal(nextStepText({}), null)
})
