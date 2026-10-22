import test from 'node:test'
import assert from 'node:assert/strict'
import {
  counterpartyPatch, localReferenceId, reconcileContractLinks, resumeCreation,
  searchContractCounterparties, type CreationProgress,
} from './contractFormSave.ts'

const imported = { id: 'local-cp', externalRef: 'onec-cp', name: 'ООО Энергия', inn: '1234567890' }

test('поиск импортированного контрагента по имени и ИНН сохраняет локальный ID выбора', () => {
  for (const query of [' эНеРгИя ', '456789']) {
    const [selected] = searchContractCounterparties([imported], query)
    assert.equal(selected.id, 'local-cp')
    assert.equal(localReferenceId(selected.id, [imported]), 'local-cp')
  }
  assert.deepEqual(searchContractCounterparties([imported], 'другая организация'), [])
})

test('старые ссылки из группы, корпклиента и договора разрешаются в локальные ID обеих сторон', () => {
  const org = { id: 'local-org', externalRef: 'onec-org' }
  assert.equal(localReferenceId('onec-cp', [imported]), 'local-cp')
  assert.equal(localReferenceId('onec-org', [org]), 'local-org')
  assert.equal(localReferenceId('local-org', [org]), 'local-org')
  assert.equal(localReferenceId('unknown', [imported]), '')
  assert.equal(localReferenceId('onec-cp', [imported, { ...imported, id: 'duplicate' }]), '')
  assert.equal(localReferenceId('local-cp', [imported, { id: 'other', externalRef: 'local-cp' }]), 'local-cp')
})

test('PATCH очищает все nullable реквизиты явным null и не затрагивает отсутствующие поля', () => {
  const empty = Object.fromEntries([
    'shortName', 'fullName', 'kpp', 'ogrn', 'okpo', 'okved', 'legalAddress', 'actualAddress',
    'phone', 'email', 'directorName', 'directorPosition', 'bankAccount', 'bankBik', 'bankName',
  ].map((key) => [key, undefined]))
  const wire = JSON.parse(JSON.stringify(counterpartyPatch({ name: 'Новое имя', inn: '123', ...empty })))
  for (const key of Object.keys(empty)) assert.equal(wire[key], null, key)
  assert.deepEqual(counterpartyPatch({ phone: '123', email: '', kpp: null }), { phone: '123', email: null, kpp: null })
  assert.deepEqual(counterpartyPatch({ name: 'Имя' }), { name: 'Имя' })
})

for (const failed of ['scope', 'links']) {
  test(`договор: отказ ${failed}, повтор продолжает прежний Contract без нового POST`, async () => {
    const progress: CreationProgress = { completed: [] }
    const calls: string[] = []
    let fail = true
    const create = async () => { calls.push('POST'); return { id: 'contract-1' } }
    const steps = ['scope', 'links'].map((name) => ({ name, run: async (id: string) => {
      assert.equal(id, 'contract-1'); calls.push(name)
      if (name === failed && fail) throw new Error('отказ второго шага')
    } }))
    await assert.rejects(resumeCreation(progress, create, steps), /отказ/)
    assert.equal(progress.id, 'contract-1')
    fail = false
    assert.equal(await resumeCreation(progress, create, steps), 'contract-1')
    assert.equal(calls.filter((call) => call === 'POST').length, 1)
    assert.equal(calls.filter((call) => call === failed).length, 2)
    if (failed === 'links') assert.equal(calls.filter((call) => call === 'scope').length, 1)
  })
}

for (const failed of ['relation', 'upload', 'register']) {
  test(`бумага: отказ ${failed}, одна DocCard и пропуск уже завершённых этапов`, async () => {
    const progress: CreationProgress = { completed: [] }
    const cards: string[] = []
    const calls: string[] = []
    let fail = true
    const createDoc = async () => { cards.push('doc-1'); return { id: 'doc-1' } }
    const names = ['relation', 'upload', 'register']
    const steps = names.map((name) => ({ name, run: async (id: string) => {
      assert.equal(id, cards[0]); calls.push(name)
      if (name === failed && fail) throw new Error('отказ')
    } }))
    await assert.rejects(resumeCreation(progress, createDoc, steps), /отказ/)
    assert.deepEqual(progress.completed, names.slice(0, names.indexOf(failed)))
    fail = false
    await resumeCreation(progress, createDoc, steps)
    assert.deepEqual(cards, ['doc-1'])
    assert.deepEqual(progress.completed, names)
    for (const name of names) assert.equal(calls.filter((call) => call === name).length, name === failed ? 2 : 1)
  })
}

test('ошибка создания не запускает следующие этапы и разрешает повтор POST', async () => {
  const progress: CreationProgress = { completed: [] }
  await assert.rejects(resumeCreation(progress, async () => { throw new Error('409: карточка уже есть') }, [
    { name: 'scope', run: async () => assert.fail('scope до создания') },
  ]), /409/)
  assert.equal(progress.id, undefined)
  assert.equal(await resumeCreation(progress, async () => ({ id: 'new' }), []), 'new')
})

test('два одновременных сохранения не вызывают второй create', async () => {
  const progress: CreationProgress = { completed: [] }
  let unblock!: () => void
  const wait = new Promise<void>((resolve) => { unblock = resolve })
  const first = resumeCreation(progress, async () => { await wait; return { id: 'one' } }, [])
  await assert.rejects(resumeCreation(progress, async () => assert.fail('второй POST'), []), /уже выполняется/)
  unblock()
  assert.equal(await first, 'one')
})

test('частично сохранённые связи перечитываются, успешное удаление и добавление не повторяются', async () => {
  type Link = { id?: string; app: string; projectRef?: string | null }
  let stored: Link[] = [{ id: 'old', app: 'books' }]
  const wanted: Link[] = [{ app: 'docs' }, { app: 'projects', projectRef: 'site:1' }]
  const calls: string[] = []
  let fail = true
  const save = () => reconcileContractLinks(wanted, async () => stored.slice(), async (id) => {
    calls.push(`remove:${id}`); stored = stored.filter((link) => link.id !== id)
  }, async (link) => {
    calls.push(`add:${link.app}`)
    if (link.app === 'projects' && fail) throw new Error('отказ связи')
    stored.push({ ...link, id: link.app })
  })
  await assert.rejects(save(), /отказ/)
  fail = false
  await save()
  assert.deepEqual(calls, ['remove:old', 'add:docs', 'add:projects', 'add:projects'])
  assert.deepEqual(stored.map(({ app, projectRef }) => ({ app, projectRef })), wanted.map(({ app, projectRef }) => ({ app, projectRef })))
})
