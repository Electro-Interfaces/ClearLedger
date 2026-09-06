import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { openSectionOf, searchWithoutOpen } from './openSection.ts'

describe('раздел из адреса', () => {
  it('узнаёт свой раздел и не пускает чужое', () => {
    assert.equal(openSectionOf('?open=chat'), 'chat')
    assert.equal(openSectionOf('?open=tasks&x=1'), 'tasks')
    assert.equal(openSectionOf('?open=workspace'), null)
    assert.equal(openSectionOf(''), null)
  })
  it('гасит параметр, сохраняя соседей', () => {
    assert.equal(searchWithoutOpen('?open=chat'), '')
    assert.equal(searchWithoutOpen('?open=chat&mode=demo'), '?mode=demo')
  })
})
