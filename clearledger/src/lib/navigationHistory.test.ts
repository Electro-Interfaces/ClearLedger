import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  startNavigationHistory, advanceNavigationHistory, navigationEntryId, NavigationViewStore,
} from './navigationHistory.ts'

test('возврат и переход вперёд сохраняют состояние каждого посещения', () => {
  const views = new NavigationViewStore()
  let history = startNavigationHistory('files')
  views.set('files:search', 'ДГ-42')
  history = advanceNavigationHistory(history, 'contracts', 'PUSH')
  views.set('contracts:search', 'аренда')
  views.set('contracts:type', 'Аренда')
  history = advanceNavigationHistory(history, 'files', 'POP')
  assert.equal(history.index, 0)
  assert.equal(views.get('files:search', ''), 'ДГ-42')
  history = advanceNavigationHistory(history, 'contracts', 'POP')
  assert.equal(history.index, 1)
  assert.equal(views.get('contracts:search', ''), 'аренда')
  assert.equal(views.get('contracts:type', ''), 'Аренда')
})

test('изменение URL через REPLACE не добавляет шаг и не теряет отбор', () => {
  let history = startNavigationHistory('files')
  history = advanceNavigationHistory(history, 'contracts', 'PUSH')
  const id = navigationEntryId(history, 'contracts')
  history = advanceNavigationHistory(history, 'contracts-project', 'REPLACE')
  assert.equal(history.index, 1)
  assert.equal(history.entries.length, 2)
  assert.equal(navigationEntryId(history, 'contracts-project'), id)
  // Отложенная нормализация URL и быстрый POP могут доставить прежний key
  // той же записи. Он не должен становиться новым посещением с пустым поиском.
  history = advanceNavigationHistory(history, 'contracts', 'POP')
  assert.equal(navigationEntryId(history, 'contracts'), id)
  assert.equal(history.index, 1)
  assert.equal(navigationEntryId(history, 'contracts'), id)
  history = advanceNavigationHistory(history, 'files', 'POP')
  history = advanceNavigationHistory(history, 'contracts-project', 'POP')
  assert.equal(history.index, 1)
  assert.equal(navigationEntryId(history, 'contracts-project'), id)
})

test('новый переход после Назад отбрасывает прежнюю ветку вперёд', () => {
  let history = startNavigationHistory('files')
  history = advanceNavigationHistory(history, 'contracts', 'PUSH')
  history = advanceNavigationHistory(history, 'files', 'POP')
  history = advanceNavigationHistory(history, 'objects', 'PUSH')
  assert.deepEqual(history.entries.map((entry) => entry.key), ['files', 'objects'])
})

test('REPLACE нового экрана после пропущенного React-рендера PUSH сохраняет путь назад', () => {
  const start = startNavigationHistory('contracts', 7)
  const files = advanceNavigationHistory(start, 'files-with-filter', 'REPLACE', 8)
  assert.equal(files.index, 1)
  assert.equal(navigationEntryId(files, 'contracts'), 'contracts')
  const back = advanceNavigationHistory(files, 'contracts', 'POP', 7)
  assert.equal(back.index, 0)
  const forward = advanceNavigationHistory(back, 'files-normalized', 'REPLACE', 8)
  assert.equal(forward.index, 1)
  assert.equal(forward.entries[1].id, 'files-with-filter')
})

test('Forward посещения, чей первый рендер отменён быстрым Back, не теряет исходную запись', () => {
  const start = startNavigationHistory('contracts', 7)
  const files = advanceNavigationHistory(start, 'files', 'POP', 8)
  assert.equal(files.index, 1)
  const normalized = advanceNavigationHistory(files, 'files-with-filter', 'REPLACE', 8)
  const back = advanceNavigationHistory(normalized, 'contracts', 'POP', 7)
  assert.equal(back.index, 0)
  assert.equal(navigationEntryId(back, 'contracts'), 'contracts')
})

test('прямая ссылка и неизвестная история не разрешают уходить за границу пространства', () => {
  const history = startNavigationHistory('direct-contracts')
  assert.equal(history.index, 0)
  const unknown = advanceNavigationHistory(history, 'outside', 'POP')
  assert.equal(unknown.index, 0)
  assert.equal(unknown.entries.length, 1)
})

test('состояние разных пространств и посещений изолировано', () => {
  const first = new NavigationViewStore()
  const second = new NavigationViewStore()
  first.set('contracts:search', 'Сохранённый поиск')
  assert.equal(second.get('contracts:search', ''), '')
  first.set('other-visit:search', 'Другой поиск')
  assert.equal(first.get('contracts:search', ''), 'Сохранённый поиск')
})
