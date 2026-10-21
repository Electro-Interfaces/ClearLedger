import assert from 'node:assert/strict'
import test from 'node:test'
import { voiceHelpContext } from '../pages/voice/helpContext.ts'
import { voiceSourceParams } from '../pages/voice/sourceParams.ts'

test('помощь различает источник, вкладку истории и карточку звонка', () => {
  for (const [path, query, source, expected] of [
    ['/voice/calls', '', 'megafon', 'calls:megafon:calls'],
    ['/voice/calls', '', 'node', 'calls:node'],
    ['/voice/calls', 'id=contact-1', 'node', 'calls:node:card'],
    ['/voice/stats', '', 'megafon', 'stats:megafon:operators'],
    ['/voice/stats', 'view=groups', 'megafon', 'stats:megafon:groups'],
    ['/voice/megafon', 'call=history-1', 'megafon', 'megafon:card'],
    ['/voice/megafon', 'view=invalid', 'megafon', 'megafon:calls'],
    ['/voice/report', '', 'node', 'report:node'],
    ['/voice/report', '', 'megafon', 'report:megafon'],
  ]) {
    assert.equal(voiceHelpContext(path, new URLSearchParams(query), source).sectionKey, expected)
  }
})

test('помощь использует настоящие вкладки настроек и их умолчания', () => {
  for (const [path, query, expected] of [
    ['/voice', '', 'now'], ['/voice/cc', '', 'cc'],
    ['/voice/reception', '', 'reception:hours'],
    ['/voice/reception', 'tab=callback', 'reception:callback'],
    ['/voice/passport', 'tab=privacy', 'passport:privacy'],
    ['/voice/passport', 'tab=invalid', 'passport:presentation'],
    ['/voice/webhooks', 'tab=keys', 'webhooks:keys'],
    ['/voice/versions', 'tab=log', 'versions:log'],
  ]) assert.equal(voiceHelpContext(path, new URLSearchParams(query), 'node').sectionKey, expected)
})

test('период и таблица не сбрасывают статью, источник и вкладка меняют контекст', () => {
  const original = voiceHelpContext('/voice/calls', new URLSearchParams('source=node'), 'node')
  const filtered = voiceHelpContext('/voice/calls', new URLSearchParams('source=node&from=2026-10-01&search=0101&page=2'), 'node')
  assert.deepEqual(filtered, original)
  assert.notEqual(voiceHelpContext('/voice/calls', new URLSearchParams('source=megafon'), 'megafon').sectionKey, original.sectionKey)
})

test('смена источника сохраняет контур оболочки и убирает несовместимые фильтры', () => {
  const old = new URLSearchParams('f=common-scope&source=megafon&period=7d&from=2026-10-01&view=groups&line=12345678&call=old-call&voice_company=old-company')
  const next = voiceSourceParams(old, 'node')
  assert.equal(next.toString(), 'f=common-scope&source=node')
  assert.equal(old.get('call'), 'old-call', 'Исходный снимок URL не меняется')
  const node = new URLSearchParams('f=common-scope&source=node&id=old-contact&metric=missed&cc=1&month=2026-09')
  assert.equal(voiceSourceParams(node, 'megafon').toString(), 'f=common-scope&source=megafon')
})
