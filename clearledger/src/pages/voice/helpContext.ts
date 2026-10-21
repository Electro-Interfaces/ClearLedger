import { voiceViewFor, VOICE_MEGAFON_TABS, VOICE_PASSPORT_TABS, VOICE_RECEPTION_TABS } from './views.ts'

/** Источник уже выбран тем же механизмом, что рисует содержимое VoiceLayout. */
export function voiceHelpContext(pathname: string, params: URLSearchParams, source: string) {
  const view = voiceViewFor(pathname)
  let sectionKey = view.key
  let title = view.label
  const provider = view.key === 'megafon' || (['calls', 'stats', 'report'].includes(view.key) && source === 'megafon')
  if (['calls', 'stats', 'report'].includes(view.key)) {
    sectionKey += provider ? ':megafon' : ':node'
    title += provider ? ' · МегаФон ВАТС' : ' · Узел ContactHub'
  }
  if (provider && view.key !== 'report') {
    const tab = VOICE_MEGAFON_TABS.find(t => t.k === params.get('view'))
      ?? VOICE_MEGAFON_TABS.find(t => t.k === (view.key === 'stats' ? 'operators' : 'calls'))!
    sectionKey += ':' + (params.has('call') ? 'card' : tab.k)
    title += ' · ' + (params.has('call') ? 'Карточка звонка' : tab.label)
  } else if (view.key === 'calls' && params.has('id')) {
    sectionKey += ':card'
    title += ' · Карточка звонка'
  } else if (view.key === 'passport' || view.key === 'reception') {
    const tabs = view.key === 'passport' ? VOICE_PASSPORT_TABS : VOICE_RECEPTION_TABS
    const tab = tabs.find(t => t.key === params.get('tab')) ?? tabs[0]
    sectionKey += ':' + tab.key
    title += ' · ' + tab.name
  } else if (view.key === 'webhooks') {
    const keys = params.get('tab') === 'keys'
    sectionKey += keys ? ':keys' : ':hooks'
    title = keys ? 'Ключи систем' : 'Получатели событий'
  } else if (view.key === 'versions') {
    const log = params.get('tab') === 'log'
    sectionKey += log ? ':log' : ':rev'
    title = log ? 'Журнал изменений' : 'Версии настроек'
  }
  return { appCode: 'voice', sectionKey, title }
}
