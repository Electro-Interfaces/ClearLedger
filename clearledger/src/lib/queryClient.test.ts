import test from 'node:test'
import assert from 'node:assert/strict'
import { QueryObserver } from '@tanstack/react-query'
import { queryClient } from './queryClient.ts'

const settled = () => new Promise<void>((resolve) => setImmediate(resolve))

test('canonical source changes refresh an observed catalogue in their own company', async () => {
  for (const source of [['docs', 'a'], ['doc', 'paper-id', 'a'], ['references', 'a', 'contracts'], ['site-docs', 'a', 'site-id']]) {
    queryClient.clear()
    queryClient.setQueryData(source, [])
    queryClient.setQueryData(['raw-docs-space', 'a'], ['before'])
    queryClient.setQueryData(['raw-docs-space', 'b'], ['other-company'])
    queryClient.setQueryData(['raw-docs-books', 'a'], ['accounting'])
    let requests = 0
    const observer = new QueryObserver(queryClient, { queryKey: ['raw-docs-space', 'a'],
      staleTime: Infinity, queryFn: async () => { requests++; return ['after'] } })
    const unsubscribe = observer.subscribe(() => {})
    try {
      await queryClient.invalidateQueries({ queryKey: source })
      await settled()
      assert.equal(requests, 1, String(source))
      assert.deepEqual(queryClient.getQueryData(['raw-docs-space', 'a']), ['after'])
      assert.equal(queryClient.getQueryState(['raw-docs-space', 'b'])?.isInvalidated, false)
      assert.equal(queryClient.getQueryState(['raw-docs-books', 'a'])?.isInvalidated, false)
    } finally { unsubscribe() }
  }
  queryClient.clear()
})

test('one mutation invalidating several canonical views schedules one catalogue refresh', async () => {
  queryClient.clear()
  for (const key of [['docs', 'a'], ['doc', 'paper-id', 'a'], ['references', 'a']]) queryClient.setQueryData(key, [])
  queryClient.setQueryData(['raw-docs-space', 'a'], [])
  let requests = 0
  const observer = new QueryObserver(queryClient, { queryKey: ['raw-docs-space', 'a'],
    staleTime: Infinity, queryFn: async () => { requests++; return ['created'] } })
  const unsubscribe = observer.subscribe(() => {})
  try {
    await Promise.all([['docs', 'a'], ['doc', 'paper-id', 'a'], ['references', 'a']]
      .map((queryKey) => queryClient.invalidateQueries({ queryKey })))
    await settled()
    assert.equal(requests, 1)
  } finally { unsubscribe(); queryClient.clear() }
})

test('read results and unrelated tasks do not invalidate catalogue; an inactive company cache becomes stale without a request', async () => {
  queryClient.clear()
  queryClient.setQueryData(['raw-docs-space', 'a'], ['cached'])
  queryClient.setQueryData(['tasks', 'a'], [])
  queryClient.setQueryData(['docs', 'a'], ['read-result'])
  await queryClient.invalidateQueries({ queryKey: ['tasks', 'a'] })
  await settled()
  assert.equal(queryClient.getQueryState(['raw-docs-space', 'a'])?.isInvalidated, false)
  await queryClient.invalidateQueries({ queryKey: ['docs', 'a'] })
  await settled()
  assert.equal(queryClient.getQueryState(['raw-docs-space', 'a'])?.isInvalidated, true)
  assert.equal(queryClient.getQueryState(['raw-docs-space', 'a'])?.fetchStatus, 'idle')
  assert.deepEqual(queryClient.getQueryData(['raw-docs-space', 'a']), ['cached'])
  queryClient.clear()
})
