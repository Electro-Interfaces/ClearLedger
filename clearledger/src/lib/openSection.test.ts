import { describe, expect, it } from 'vitest'
import { openSectionOf, searchWithoutOpen } from './openSection'

describe('раздел из адреса', () => {
  it('узнаёт свой раздел и не пускает чужое', () => {
    expect(openSectionOf('?open=chat')).toBe('chat')
    expect(openSectionOf('?open=tasks&x=1')).toBe('tasks')
    expect(openSectionOf('?open=workspace')).toBeNull()
    expect(openSectionOf('')).toBeNull()
  })
  it('гасит параметр, сохраняя соседей', () => {
    expect(searchWithoutOpen('?open=chat')).toBe('')
    expect(searchWithoutOpen('?open=chat&mode=demo')).toBe('?mode=demo')
  })
})
