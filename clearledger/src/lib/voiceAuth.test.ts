/**
 * Кэш пропуска в API узла не должен смешивать компании и пользователей.
 *
 * Это чистая state machine без браузера: HTTP-слой проверяется отдельно. Здесь
 * фиксируем самые опасные границы — single-flight, обновление до истечения и
 * сброс во время уже начавшейся выдачи токена.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { createVoiceAuth, type VoiceAccessToken } from './voiceAuth.ts'

const token = (value: string, exp: number): VoiceAccessToken => ({ token: value, exp })

test('параллельные запросы одной компании делят одну выдачу токена', async () => {
  let finish!: (value: VoiceAccessToken) => void
  let issues = 0
  const pending = new Promise<VoiceAccessToken>((resolve) => { finish = resolve })
  const auth = createVoiceAuth({
    issue: async () => { issues += 1; return pending },
    now: () => 0,
  })

  const first = auth.get('company-a')
  const second = auth.get('company-a')
  assert.equal(issues, 1, 'одновременные экраны не должны выпускать по токену каждый')

  finish(token('shared', 300_000))
  assert.deepEqual(await Promise.all([first, second]), [token('shared', 300_000), token('shared', 300_000)])
  assert.equal(issues, 1)
})

test('кэш разделён по компаниям и повторно использует ещё годный токен', async () => {
  let issues = 0
  const auth = createVoiceAuth({
    issue: async (companyId) => token(`${companyId}-${++issues}`, 300_000),
    now: () => 0,
  })

  assert.equal((await auth.get('company-a')).token, 'company-a-1')
  assert.equal((await auth.get('company-b')).token, 'company-b-2')
  assert.equal((await auth.get('company-a')).token, 'company-a-1')
  assert.equal(issues, 2)
})

test('токен обновляется заранее на границе refreshSkewMs', async () => {
  let now = 0
  let issues = 0
  const auth = createVoiceAuth({
    issue: async () => token(`token-${++issues}`, 120_000),
    now: () => now,
    refreshSkewMs: 60_000,
  })

  assert.equal((await auth.get('company-a')).token, 'token-1')
  now = 59_999
  assert.equal((await auth.get('company-a')).token, 'token-1', 'до границы используем прежний токен')
  now = 60_000
  assert.equal((await auth.get('company-a')).token, 'token-2', 'на границе нужен новый токен')
})

test('точечный и полный invalidate не оставляют чужой пропуск', async () => {
  const issues = new Map<string, number>()
  const auth = createVoiceAuth({
    issue: async (companyId) => {
      const n = (issues.get(companyId) ?? 0) + 1
      issues.set(companyId, n)
      return token(`${companyId}-${n}`, 300_000)
    },
    now: () => 0,
  })

  await Promise.all([auth.get('company-a'), auth.get('company-b')])
  auth.invalidate('company-a')
  assert.equal((await auth.get('company-a')).token, 'company-a-2')
  assert.equal((await auth.get('company-b')).token, 'company-b-1')

  auth.invalidate()
  assert.equal((await auth.get('company-a')).token, 'company-a-3')
  assert.equal((await auth.get('company-b')).token, 'company-b-2')
})

test('поздний ответ после invalidate возвращается вызвавшему, но не попадает в кэш', async () => {
  let finish!: (value: VoiceAccessToken) => void
  let issues = 0
  const auth = createVoiceAuth({
    issue: async () => {
      issues += 1
      if (issues === 1) return new Promise<VoiceAccessToken>((resolve) => { finish = resolve })
      return token('fresh', 300_000)
    },
    now: () => 0,
  })

  const staleRequest = auth.get('company-a')
  auth.invalidate('company-a')
  finish(token('stale', 300_000))
  assert.equal((await staleRequest).token, 'stale')
  assert.equal((await auth.get('company-a')).token, 'fresh', 'сброшенный in-flight ответ нельзя кешировать')
  assert.equal(issues, 2)
})
