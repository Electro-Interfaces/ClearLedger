/**
 * Раздел «Взаимодействия», запрошенный адресом: `…/?open=chat`.
 *
 * Дверь снаружи. У станционного агента своих чата и «Трека» нет и не будет —
 * шапка станции ведёт в пространство, и вести она должна в ОКНО чата, а не в
 * приложение «Чаты»: приложение — это управление каналами и составом, работа
 * администратора, а оператору нужна переписка.
 */
export type OpenSection = 'chat' | 'tasks' | 'calendar' | 'notes' | 'tickets' | 'help' | 'auditor'

const SECTIONS: OpenSection[] = ['chat', 'tasks', 'calendar', 'notes', 'tickets', 'help', 'auditor']

/** Какой раздел просит адрес. Неизвестное значение — не раздел, окна не будет. */
export function openSectionOf(search: string): OpenSection | null {
  const v = new URLSearchParams(search).get('open')
  return SECTIONS.includes(v as OpenSection) ? (v as OpenSection) : null
}

/** Тот же адрес без `open`: параметр одноразовый, иначе F5 снова открывает окно. */
export function searchWithoutOpen(search: string): string {
  const p = new URLSearchParams(search)
  p.delete('open')
  const q = p.toString()
  return q ? `?${q}` : ''
}
