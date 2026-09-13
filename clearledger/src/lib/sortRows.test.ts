/**
 * Правило сортировки таблиц: пустое значение всегда внизу, в обе стороны.
 *
 * «Нет данных» — это не ноль и не «самое маленькое». Если пустые всплывут наверх при
 * сортировке по возрастанию, первый экран займут строки, про которые ничего не
 * известно: в «Компаниях» это компании без цены, в «Обеспеченности» — регионы без
 * парка машин. Менеджер решит, что таблица сломалась, и будет прав.
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { sortRows } from './sortRows.ts'

type Строка = { n: number | null; s?: string | null }

describe('сортировка таблиц', () => {
  const rows: Строка[] = [{ n: 5 }, { n: null }, { n: 12 }, { n: 0 }]
  const по = (r: Строка) => r.n

  it('по убыванию: пустое внизу', () => {
    assert.deepEqual(sortRows(rows, по, 'desc').map((r) => r.n), [12, 5, 0, null])
  })

  it('по возрастанию: пустое всё равно внизу, а не первым', () => {
    assert.deepEqual(sortRows(rows, по, 'asc').map((r) => r.n), [0, 5, 12, null])
  })

  it('ноль не считается пустым', () => {
    const only = sortRows([{ n: 0 }, { n: null }], по, 'asc').map((r) => r.n)
    assert.deepEqual(only, [0, null])
  })

  it('строки сравниваются по-русски, пустая строка — внизу', () => {
    const words: Строка[] = [{ n: 1, s: 'Ярославль' }, { n: 2, s: '' },
                             { n: 3, s: 'Астрахань' }, { n: 4, s: 'Брянск' }]
    assert.deepEqual(
      sortRows(words, (r) => r.s, 'asc').map((r) => r.s),
      ['Астрахань', 'Брянск', 'Ярославль', ''])
  })

  it('исходный список не меняется', () => {
    const src: Строка[] = [{ n: 2 }, { n: 1 }]
    sortRows(src, по, 'asc')
    assert.deepEqual(src.map((r) => r.n), [2, 1])
  })
})
