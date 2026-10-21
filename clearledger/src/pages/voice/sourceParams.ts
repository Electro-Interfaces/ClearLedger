/** При смене источника сбрасываем фильтры Телефонии, сохраняя параметры оболочки. */
export function voiceSourceParams(previous: URLSearchParams, source: string) {
  const next = new URLSearchParams(previous)
  for (const key of ['period', 'from', 'to', 'operator', 'group', 'line', 'direction', 'missed',
    'search', 'page', 'call', 'voice_company', 'id', 'metric', 'servedBy', 'topic', 'back',
    'cc', 'number', 'flags', 'outcome', 'month', 'view']) next.delete(key)
  next.set('source', source)
  return next
}
