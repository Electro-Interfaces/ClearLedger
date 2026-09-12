// node --test --experimental-strip-types src/lib/safeBackTo.test.ts
import test from 'node:test'
import assert from 'node:assert/strict'
import { safeBackTo } from './safeBackTo.ts'

test('внутренний адрес сохраняется целиком', () => {
  assert.equal(safeBackTo('/t/TF-42'), '/t/TF-42')
  assert.equal(safeBackTo('/docs/company?view=errands&task=TF-42'),
    '/docs/company?view=errands&task=TF-42')
})

test('чужой сайт и мусор — на главную', () => {
  assert.equal(safeBackTo('//evil.example/phish'), '/')
  assert.equal(safeBackTo('https://evil.example'), '/')
  assert.equal(safeBackTo(undefined), '/')
  assert.equal(safeBackTo(42), '/')
})

test('обратно на логин не возвращаем — вход зациклится', () => {
  assert.equal(safeBackTo('/login'), '/')
  assert.equal(safeBackTo('/login?next=/t/TF-1'), '/')
})
