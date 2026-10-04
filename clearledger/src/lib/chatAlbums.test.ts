/**
 * Сборка альбомов: одной плиткой показывается ОДНА отправка, а не всё, что
 * человек прислал за две минуты.
 *
 * Прогон: node --test --experimental-strip-types src/lib/chatAlbums.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { albumCaption, collectAlbums, type AlbumMessage } from './chatAlbums.ts'

interface Сообщение extends AlbumMessage {
  id: string
  картинка?: boolean
}

const картинка = (m: Сообщение) => Boolean(m.картинка)

function лента(...msgs: Partial<Сообщение>[]): Сообщение[] {
  return msgs.map((m, i) => ({
    id: String(i + 1), userId: 'u1', content: '', картинка: true,
    createdAt: new Date(Date.UTC(2026, 8, 18, 10, 0, i * 5)).toISOString(),
    ...m,
  }))
}

test('одна отправка — один альбом', () => {
  const items = collectAlbums(лента(
    { id: 'a', batchId: 'п1', content: 'три снимка' },
    { id: 'b', batchId: 'п1' },
    { id: 'c', batchId: 'п1' },
  ), картинка)
  assert.equal(items.length, 1)
  assert.deepEqual(items[0].album?.map((m) => m.id), ['a', 'b', 'c'])
})

test('следующая отправка не прилипает к предыдущей', () => {
  // Ровно жалоба: сообщение уже отправлено, человек шлёт ещё фото — и оно
  // оказывалось в чужой плитке.
  const items = collectAlbums(лента(
    { id: 'a', batchId: 'п1', content: 'первое' },
    { id: 'b', batchId: 'п1' },
    { id: 'c', batchId: 'п2', content: 'второе, отдельное' },
  ), картинка)
  assert.equal(items.length, 2)
  assert.deepEqual(items[0].album?.map((m) => m.id), ['a', 'b'])
  assert.equal(items[1].msg.id, 'c')
  assert.equal(items[1].album, undefined)
})

test('старые сообщения без признака отправки склеиваются узким окном', () => {
  const быстро = collectAlbums(лента({ id: 'a' }, { id: 'b' }), картинка)
  assert.equal(быстро.length, 1, 'снимки через пять секунд — одна отправка')

  const минута = collectAlbums([
    { id: 'a', userId: 'u1', content: '', картинка: true, createdAt: '2026-09-18T10:00:00.000Z' },
    { id: 'b', userId: 'u1', content: '', картинка: true, createdAt: '2026-09-18T10:01:00.000Z' },
  ], картинка)
  assert.equal(минута.length, 2, 'минута спустя — отдельное сообщение')
})

test('подпись не склеивает: текст значит новое сообщение', () => {
  const items = collectAlbums(лента(
    { id: 'a' },
    { id: 'b', content: 'а вот это уже про другое' },
  ), картинка)
  assert.equal(items.length, 2)
})

test('чужое сообщение в альбом не попадает', () => {
  const items = collectAlbums(лента(
    { id: 'a', batchId: 'п1' },
    { id: 'b', batchId: 'п1', userId: 'u2' },
  ), картинка)
  assert.equal(items.length, 2)
})

test('не-картинки остаются как есть', () => {
  const items = collectAlbums(лента(
    { id: 'a', картинка: false, content: 'текст' },
    { id: 'b', batchId: 'п1' },
    { id: 'c', batchId: 'п1' },
    { id: 'd', картинка: false, content: 'ещё текст' },
  ), картинка)
  assert.deepEqual(items.map((x) => x.msg.id), ['a', 'b', 'd'])
  assert.equal(items[1].album?.length, 2)
})

test('подпись альбома — текст отправки, где бы он ни оказался', () => {
  assert.equal(albumCaption(лента({ content: 'к снимкам' }, {})), 'к снимкам')
  // Файлы догружались, и текст достался не первому сообщению пачки.
  assert.equal(albumCaption(лента({}, { content: 'подпись' })), 'подпись')
  assert.equal(albumCaption(лента({}, {})), '')
})
