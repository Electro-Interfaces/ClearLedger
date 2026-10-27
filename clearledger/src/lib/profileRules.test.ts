import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ПОЯСА, ВИДЫ_ПИСЕМ, МИН_ДЛИНА_ПАРОЛЯ, ПРЕДЕЛ_ФОТО_МБ,
  поясаПоСмещению, подписьПояса, порядокВидовПисем,
  рабочийДеньВерен, ошибкаПароля, ошибкаФото, телефонНеРаспознан,
  ошибкаОтсутствия, периодСловами,
} from './profileRules.ts'

test('пояса покрывают все смещения России и не повторяются', () => {
  const смещения = [...new Set(ПОЯСА.map((z) => z.offset))].sort((a, b) => a - b)
  assert.deepEqual(смещения, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
  assert.equal(new Set(ПОЯСА.map((z) => z.id)).size, ПОЯСА.length)
  // Города, из-за отсутствия которых список и переделывали.
  for (const id of ['Asia/Novosibirsk', 'Asia/Chita', 'Asia/Sakhalin', 'Asia/Anadyr']) {
    assert.ok(ПОЯСА.some((z) => z.id === id), `нет ${id}`)
  }
})

test('имена поясов — настоящие зоны IANA с заявленным смещением', () => {
  for (const z of ПОЯСА) {
    const части = new Intl.DateTimeFormat('ru-RU', {
      timeZone: z.id, timeZoneName: 'longOffset',
    }).formatToParts(new Date('2026-07-01T12:00:00Z'))
    const подпись = части.find((p) => p.type === 'timeZoneName')?.value ?? ''
    assert.equal(подпись, `GMT+0${z.offset}:00`.replace('+0', z.offset > 9 ? '+' : '+0'),
      `${z.id}: ${подпись}`)
  }
})

test('подпись пояса называет город и смещение', () => {
  assert.equal(подписьПояса({ id: 'Asia/Novosibirsk', label: 'Новосибирск', offset: 7 }),
    'Новосибирск (UTC+7)')
})

test('группировка по смещению идёт по возрастанию и ничего не теряет', () => {
  const группы = поясаПоСмещению()
  assert.deepEqual(группы.map((g) => g.offset), [...группы.map((g) => g.offset)].sort((a, b) => a - b))
  assert.equal(группы.reduce((n, g) => n + g.зоны.length, 0), ПОЯСА.length)
})

test('рабочий день: конец позже начала', () => {
  assert.equal(рабочийДеньВерен('09:00', '18:00'), true)
  assert.equal(рабочийДеньВерен('09:00', '09:00'), false)
  assert.equal(рабочийДеньВерен('19:00', '09:00'), false)
  assert.equal(рабочийДеньВерен('', '18:00'), false)
})

test('пароль: пустой текущий, короткий новый, совпадение и повтор', () => {
  assert.equal(ошибкаПароля('', 'ТихийВечер-2026', 'ТихийВечер-2026'), 'Введите текущий пароль')
  assert.match(ошибкаПароля('старый', 'корот', 'корот') ?? '', new RegExp(String(МИН_ДЛИНА_ПАРОЛЯ)))
  assert.match(ошибкаПароля('ТихийВечер-2026', 'ТихийВечер-2026', 'ТихийВечер-2026') ?? '', /отличаться/)
  assert.match(ошибкаПароля('старый', 'ТихийВечер-2026', 'ТихийВечер-2025') ?? '', /не совпадают/)
  assert.equal(ошибкаПароля('старый', 'ТихийВечер-2026', 'ТихийВечер-2026'), null)
})

test('фото: тип и предел размера', () => {
  const файл = (type: string, mb: number) =>
    ({ type, size: Math.round(mb * 1024 * 1024) }) as File
  assert.equal(ошибкаФото(файл('application/pdf', 1)), 'Нужна картинка')
  assert.match(ошибкаФото(файл('image/jpeg', ПРЕДЕЛ_ФОТО_МБ + 1)) ?? '', /больше/)
  assert.equal(ошибкаФото(файл('image/jpeg', 1)), null)
})

test('виды писем совпадают с серверным каталогом и не повторяются', () => {
  // Порядок и состав — как в notify.EMAIL_KINDS: по ним сравнивается черновик.
  assert.deepEqual(ВИДЫ_ПИСЕМ.map((k) => k.id),
    ['task_assigned', 'task_mention', 'task_reply', 'task_status', 'digest', 'meeting'])
  assert.equal(new Set(ВИДЫ_ПИСЕМ.map((k) => k.id)).size, ВИДЫ_ПИСЕМ.length)
  for (const k of ВИДЫ_ПИСЕМ) {
    assert.ok(k.label.length > 3 && k.hint.length > 3, k.id)
  }
})

test('порядок видов писем — каталожный, лишнее отбрасывается', () => {
  assert.deepEqual(порядокВидовПисем(['digest', 'task_assigned']), ['task_assigned', 'digest'])
  assert.deepEqual(порядокВидовПисем(['чужое', 'task_reply']), ['task_reply'])
  assert.deepEqual(порядокВидовПисем([]), [])
})

test('подсказка о номере: ловит то, что сервер не распознает', () => {
  assert.equal(телефонНеРаспознан(''), false)            // пустое — не ошибка
  assert.equal(телефонНеРаспознан('89001234567'), false)
  assert.equal(телефонНеРаспознан('+7 (900) 123-45-67'), false)
  assert.equal(телефонНеРаспознан('8 812 000-00-00 доб 123'), false)
  assert.equal(телефонНеРаспознан('123-45-67'), true)     // городской без кода
  assert.equal(телефонНеРаспознан('внутренний 1234'), true)
})

test('период отсутствия: возвращение не раньше ухода', () => {
  assert.equal(ошибкаОтсутствия('2026-11-03', '2026-11-17'), null)
  assert.equal(ошибкаОтсутствия('2026-11-03', ''), null)      // ушёл без даты возвращения
  assert.equal(ошибкаОтсутствия('', '2026-11-17'), null)      // вернётся 18-го
  assert.equal(ошибкаОтсутствия('', ''), null)
  assert.match(ошибкаОтсутствия('2026-11-17', '2026-11-03') ?? '', /раньше/)
})

test('период словами читается человеком', () => {
  // Один месяц — не повторяем его дважды.
  assert.equal(периодСловами('2026-11-03', '2026-11-17'), '3 — 17 ноября 2026')
  assert.equal(периодСловами('2026-10-28', '2026-11-05'), '28 октября 2026 — 5 ноября 2026')
  assert.equal(периодСловами('2026-11-03', ''), 'с 3 ноября 2026')
  assert.equal(периодСловами('', '2026-11-17'), 'по 17 ноября 2026')
  assert.equal(периодСловами('', ''), '')
})
