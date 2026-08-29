/**
 * Записная книжка: превращение текста в список и обратно, быстрые сроки.
 *
 * Вынесено из экрана, потому что обе стороны превращения обязаны быть
 * обратимыми. Человек превратил запись в список, передумал — и должен получить
 * СВОЙ текст назад, а не пустое поле и не строки с чужими дефисами. Ошибка тут
 * не падает: она молча съедает написанное.
 */

/** Строки текста как пункты списка.
 *
 *  Маркер в начале строки снимаем: человек, писавший список руками, ставил
 *  дефисы — оставь их, и в готовом списке у каждого пункта будет второй маркер.
 *  Пустые строки выбрасываем: абзацный отступ не пункт. */
export function toItems(text: string): string[] {
  return text
    .split('\n')
    .map((s) => s.replace(/^[-–—•*•]+\s*/, '').trim())
    .filter(Boolean)
}

/** Пункты обратно в текст. Прежний текст, если он был, идёт первым: список
 *  обычно вырастает ПОД записью, и склеивать наоборот значит перевернуть её. */
export function toText(items: { text: string }[], rest = ''): string {
  return [rest.trim(), items.map((i) => i.text).join('\n')]
    .filter(Boolean)
    .join('\n')
    .trim()
}

/** Местное «сегодня вечером» в виде значения для `datetime-local`.
 *
 *  Если вечер уже наступил — завтрашний: напоминание в прошлое сервер молча не
 *  ставит, и кнопка оказалась бы мёртвой без единого признака. */
export function nextEvening(now: Date = new Date(), hour = 18): string {
  const d = new Date(now)
  if (d.getHours() >= hour) d.setDate(d.getDate() + 1)
  d.setHours(hour, 0, 0, 0)
  return localInput(d)
}

/** Местное «завтра утром». */
export function nextMorning(now: Date = new Date(), hour = 9): string {
  const d = new Date(now)
  d.setDate(d.getDate() + 1)
  d.setHours(hour, 0, 0, 0)
  return localInput(d)
}

/** `YYYY-MM-DDTHH:mm` в МЕСТНОМ времени: `toISOString` здесь врёт на величину
 *  часового пояса, и «вечером» у Владивостока приходилось бы на утро. */
function localInput(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16)
}
