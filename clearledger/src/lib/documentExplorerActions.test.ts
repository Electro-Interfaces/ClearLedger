import test from 'node:test'
import assert from 'node:assert/strict'
import { documentExplorerActions, primaryExplorerAction, pushExplorerHistory, readExplorerLocation, restoreExplorerHistory } from './documentExplorerActions.ts'

const allowed = () => true

test('DocCard opens independently of attachment and contract; file remains a separate action', () => {
  const actions = documentExplorerActions({ docId: 'paper', contractId: 'passport', fileId: 'pdf' }, allowed, '/operations')
  assert.deepEqual(actions.map((action) => [action.label, action.href]), [
    ['Карточка', '/docs?view=all&doc=paper'], ['Файл', '/api/files/pdf'],
    ['Договор', '/operations/contractors?sub=contracts&contract=passport'],
  ])
  assert.equal(primaryExplorerAction(actions)?.id, 'card')
  assert.equal(primaryExplorerAction(documentExplorerActions({ docId: 'empty-paper' }, allowed))?.href, '/docs?view=all&doc=empty-paper')
})

test('owner precedes file for a site row and a contract passport, without inventing a site from projectId', () => {
  assert.equal(primaryExplorerAction(documentExplorerActions({ contractId: 'passport', fileId: 'pdf' }, allowed))?.href, '/contractors?sub=contracts&contract=passport')
  assert.equal(primaryExplorerAction(documentExplorerActions({ siteId: 'site', projectId: 'different-project', siteDocId: 'source', fileId: 'pdf' }, allowed))?.href,
    '/projects?mode=projects&sub=pr_project&project=site&ptab=docs')
  assert.deepEqual(documentExplorerActions({ projectId: 'different-project' }, allowed), [{ id: 'project', label: 'Все проекты', href: '/projects?mode=projects&sub=pr_project' }])
})

test('route permissions hide inaccessible owners while retaining authenticated attachment opening', () => {
  const actions = documentExplorerActions({ docId: 'doc', fileId: 'file', contractId: 'contract', siteId: 'site' }, () => false)
  assert.deepEqual(actions, [{ id: 'file', label: 'Файл', href: '/api/files/file', attachment: true }])
  assert.equal(primaryExplorerAction([]), undefined)
})

test('opaque IDs cannot inject query or path segments', () => {
  const actions = documentExplorerActions({ docId: 'a&new=1', fileId: 'x/y', contractId: 'a?sub=corp', siteId: 'a#b' }, allowed)
  assert.equal(actions[0].href, '/docs?view=all&doc=a%26new%3D1')
  assert.equal(actions[1].href, '/api/files/x%2Fy')
  assert.equal(actions[2].href, '/contractors?sub=contracts&contract=a%3Fsub%3Dcorp')
  assert.ok(actions[3].href.includes('project=a%23b&ptab=docs'))
})

test('folder and search round trip through URL without dropping Unicode or unrelated parameters', () => {
  assert.deepEqual(readExplorerLocation('?folder=%D0%94%D0%BE%D0%B3%D0%BE%D0%B2%D0%BE%D1%80%D1%8B%2F2026&q=a%26b&sub=all'), { folder: ['Договоры', '2026'], query: 'a&b' })
  assert.deepEqual(readExplorerLocation(''), { folder: [], query: '' })
})

test('Back and Forward traverse visited siblings; Up is a separate new visit and truncates forward history', () => {
  const root = { folder: [], query: '' }
  const first = { folder: ['Договоры'], query: 'акт' }
  const second = { folder: ['Проекты'], query: '' }
  let history = pushExplorerHistory({ entries: [root], index: 0 }, first)
  history = pushExplorerHistory(history, second)
  assert.equal(history.index, 2)
  const back = { ...history, index: 1 }
  assert.deepEqual(back.entries[back.index], first)
  assert.deepEqual(back.entries[back.index + 1], second)
  const up = pushExplorerHistory(back, root)
  assert.deepEqual(up.entries, [root, first, root])
  assert.equal(up.index, 2)
  assert.equal(restoreExplorerHistory(up, root).index, 2)
  assert.equal(pushExplorerHistory(up, root), up)
})

test('return from card restores current folder/search and forward history; cold entry does not import another location', () => {
  const root = { folder: [], query: '' }
  const folder = { folder: ['Проекты'], query: 'акт' }
  const history = { entries: [root, folder], index: 1 }
  assert.deepEqual(restoreExplorerHistory(history, folder), history)
  assert.deepEqual(restoreExplorerHistory(history, root), { ...history, index: 0 })
  assert.deepEqual(restoreExplorerHistory(null, folder), { entries: [folder], index: 0 })
})


test('all linked contracts are reachable once, with stable distinct action keys', () => {
  const actions = documentExplorerActions({ docId: 'paper', contractId: 'first', contractIds: ['first', 'second', 'second'] }, allowed, '/sales')
  assert.deepEqual(actions.slice(1).map((action) => [action.id, action.label, action.href]), [
    ['contract', 'Договор', '/sales/contractors?sub=contracts&contract=first'],
    ['contract:second', 'Договор 2', '/sales/contractors?sub=contracts&contract=second'],
  ])
})

test('a new visit after browser Back branches at URL location, discarding future visits', () => {
  const root = { folder: [], query: '' }, first = { folder: ['Договоры'], query: '' }, second = { folder: ['Проекты'], query: '' }, child = { folder: ['Договоры', '2026'], query: '' }
  const stored = { entries: [root, first, second], index: 2 }
  const visible = restoreExplorerHistory(stored, first)
  assert.equal(visible.index, 1)
  const next = pushExplorerHistory(visible, child)
  assert.deepEqual(next.entries, [root, first, child])
  assert.equal(next.index, 2)
})
