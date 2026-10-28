/**
 * Вымышленные данные для браузерной проверки отметки сверки.
 *
 * Это проверка ИНТЕРФЕЙСА на синтетике, а не приёмка на рабочем API: настоящая
 * интеграция проверяется отдельно, на 901 договоре и 477 контрагентах. Задача
 * фикстур — показать состояния, которые на живых данных приходится ждать или
 * ловить: расхождение, устаревшую сверку, несравнимое поле, пустой ответ,
 * неполный ответ сервера и ошибку запроса.
 *
 * Форма ответов повторяет контракт сервера от 28.10.2026.
 */
export const COMPANY = '11111111-1111-1111-1111-111111111111'

export const AUTH = {
  id: 'u1', email: 'admin@elsyplus.ru', name: 'Тест · Проверка сверки',
  role: 'admin', is_superadmin: true,
  companies: [{
    id: COMPANY, name: 'ООО «Тестовая сеть ЭЗС»', slug: 'test-ezs',
    short_name: 'ТЕСТ ЭЗС', profile_id: 'energy', color: '#2563eb', inn: '7800000000',
  }],
}

export const COUNTERPARTIES = [
  { id: 'cp-1', name: 'АО «Тестэнергосбыт»', fullName: 'АО «Тестэнергосбыт»', type: 'ЮрЛицо',
    inn: '7811111111', kpp: '781101001', aliases: [], raw: {} },
  { id: 'cp-2', name: 'ООО «Тестарендодатель»', fullName: 'ООО «Тестарендодатель»', type: 'ЮрЛицо',
    inn: '7822222222', kpp: '782201001', aliases: [], raw: {} },
]

/** По одному договору на каждое состояние отметки — все видны на одном экране. */
export const CONTRACTS = [
  { id: 'c-ok', number: 'ЭС-001', date: '2026-01-15', type: 'Энергоснабжение', kind: 'СПоставщиком',
    counterpartyId: 'cp-1', currency: 'RUB', amountLimit: 1200000, isClosed: false, scopeType: 'locations', locationsCount: 3, raw: {} },
  { id: 'c-diff', number: 'ЭС-002', date: '2026-02-20', type: 'Энергоснабжение', kind: 'СПоставщиком',
    counterpartyId: 'cp-1', currency: 'RUB', amountLimit: 450000, isClosed: false, scopeType: 'locations', locationsCount: 1, raw: {} },
  { id: 'c-stale', number: 'АР-003', date: '2026-03-10', type: 'Аренда', kind: 'СПоставщиком',
    counterpartyId: 'cp-2', currency: 'RUB', amountLimit: 60000, isClosed: false, scopeType: 'locations', locationsCount: 1, raw: {} },
  { id: 'c-need', number: 'АР-004', date: '2026-04-01', type: 'Аренда', kind: 'СПоставщиком',
    counterpartyId: 'cp-2', currency: 'RUB', amountLimit: 72000, isClosed: false, scopeType: 'company', locationsCount: 0, raw: {} },
  { id: 'c-none', number: 'СЕРВ-005', date: '2026-05-05', type: 'Обслуживание', kind: 'СПоставщиком',
    counterpartyId: 'cp-2', currency: 'RUB', amountLimit: null, isClosed: false, scopeType: 'unassigned', locationsCount: 0, raw: {} },
]

const источник = (rows) => ([{
  record_id: 'r-' + rows, file: 'Расчёты_2026-09.xlsx', sheet: 'База', rows,
  period: '2026-09', as_of: '2026-09-30', batch_id: 'b-2026-09',
  counterparty: 'АО «Тестэнергосбыт»', contract: 'договор', status: 'matched',
}])

const ОГОВОРКА = 'Признака проведения в 1С выгрузка не содержит; первичные документы не предоставлены.'
const СНИМОК = 'Снимок полей карточки (контрагент, дата, номер, вид) отвечает за устаревание, сверкой не является.'

/** Несверяемое всегда: источник этих значений не подтверждал. */
const ПОСТОЯННО_НЕ_СВЕРЕНО = [
  { field: 'counterparty_id', label: 'Контрагент', reason: 'источник подтверждает только название строкой' },
  { field: 'type_code', label: 'Вид договора', reason: 'в выгрузке вида нет' },
  { field: 'inn_kpp', label: 'ИНН / КПП', reason: 'в выгрузке не передаются' },
  { field: 'original_document', label: 'Оригинал документа', reason: 'не предоставлен' },
  { field: 'posted_in_1c', label: 'Проведение в 1С', reason: 'выгрузка не содержит признака' },
]

const свежесть = (p = {}) => ({
  stale: false, stale_records: 0, checked_at: '2026-10-28',
  checked_at_basis: 'дата применения сверки', rechecked_at: null,
  baseline: 'База устаревания — снимок полей карточки.',
  checked_hash: 'aaaa1111', current_hash: 'aaaa1111', ...p,
})

/** Сводки: по одной на каждое состояние, которое человек должен различать. */
export const SUMMARIES = {
  'c-ok': {
    entity_type: 'contract', entity_id: 'c-ok', exists: true, scope: 'self', scope_label: '',
    state: 'matched_checked', state_label: 'Совпадает по сверенным реквизитам', entity_verified: false,
    state_note: 'Сошлись номер и дата. Это не проверка всего договора: остальных значений выгрузка не даёт.',
    matching: { by_status: { matched: 2 }, labels: { matched: 'Сопряжено' } },
    verification: {
      status: 'verified', label: 'Сверено',
      compared_fields: [
        { field: 'number', label: 'Номер', source: 'ЭС-001', space: 'ЭС-001', equal: true, basis: '', recheck: false },
        { field: 'date', label: 'Дата', source: '15.01.2026', space: '15.01.2026', equal: true, basis: '', recheck: false },
      ],
      checked_fields: ['number', 'date'],
      snapshot_fields: ['counterparty_id', 'date', 'number', 'type_code'],
      snapshot_basis: СНИМОК,
      unchecked_fields: ПОСТОЯННО_НЕ_СВЕРЕНО, recheck: null,
    },
    freshness: свежесть(),
    differences: [], sources: источник('12-13'), records: 2, aggregate: null, disclaimer: ОГОВОРКА,
  },
  'c-diff': {
    entity_type: 'contract', entity_id: 'c-diff', exists: true, scope: 'self', scope_label: '',
    state: 'differences', state_label: 'Расхождения с бухгалтерией', entity_verified: false,
    state_note: 'Номер и дата источника отличаются от карточки.',
    matching: { by_status: { matched: 1 }, labels: { matched: 'Сопряжено' } },
    verification: {
      status: 'differences', label: 'Расхождения',
      compared_fields: [
        { field: 'number', label: 'Номер', source: 'ЭС-2/26', space: 'ЭС-002', equal: false, basis: '', recheck: false },
        { field: 'date', label: 'Дата', source: '19.02.2026', space: '20.02.2026', equal: false, basis: '', recheck: false },
      ],
      checked_fields: [], snapshot_fields: ['counterparty_id', 'date', 'number', 'type_code'],
      snapshot_basis: СНИМОК, unchecked_fields: ПОСТОЯННО_НЕ_СВЕРЕНО, recheck: null,
    },
    // Свежесть параллельна расхождению: красный цвет не должен её прятать.
    freshness: свежесть({ stale: true, stale_records: 1, checked_at: '2026-10-20',
      rechecked_at: '2026-10-27', current_hash: 'bbbb2222' }),
    differences: [
      { field: 'number', label: 'Номер', source: 'ЭС-2/26', space: 'ЭС-002' },
      { field: 'date', label: 'Дата', source: '19.02.2026', space: '20.02.2026' },
    ],
    sources: источник('41'), records: 1, aggregate: null, disclaimer: ОГОВОРКА,
  },
  'c-stale': {
    entity_type: 'contract', entity_id: 'c-stale', exists: true, scope: 'self', scope_label: '',
    state: 'stale', state_label: 'Устарело, нужна повторная сверка', entity_verified: false,
    state_note: 'Карточку правили после сверки: изменилось сверенное поле «номер».',
    matching: { by_status: { matched: 1 }, labels: { matched: 'Сопряжено' } },
    verification: {
      status: 'stale', label: 'Устарела',
      compared_fields: [
        { field: 'number', label: 'Номер', source: 'АР-3/26', space: 'АР-003', equal: true, basis: '', recheck: false },
        { field: 'date', label: 'Дата', source: '', space: '10.03.2026', equal: null,
          basis: 'в выгрузке значения нет', recheck: false },
      ],
      checked_fields: ['number'], snapshot_fields: ['counterparty_id', 'date', 'number', 'type_code'],
      snapshot_basis: СНИМОК,
      unchecked_fields: [...ПОСТОЯННО_НЕ_СВЕРЕНО,
        { field: 'date', label: 'Дата', reason: 'выгрузка значения не дала' }],
      recheck: null,
    },
    freshness: свежесть({ stale: true, stale_records: 1, checked_at: '2026-10-20', current_hash: 'dddd4444' }),
    differences: [], sources: источник('77'), records: 1, aggregate: null, disclaimer: ОГОВОРКА,
  },
  'c-need': {
    entity_type: 'contract', entity_id: 'c-need', exists: true, scope: 'self', scope_label: '',
    state: 'needs_check', state_label: 'Требует сверки', entity_verified: false,
    state_note: 'Строка источника опознана как кандидат: совпадение неоднозначно.',
    matching: { by_status: { candidate: 1 }, labels: { candidate: 'Нужна проверка' } },
    verification: {
      status: 'not_checked', label: 'Не проверено', compared_fields: [],
      checked_fields: [], snapshot_fields: [], snapshot_basis: '',
      unchecked_fields: [...ПОСТОЯННО_НЕ_СВЕРЕНО,
        { field: 'number', label: 'Номер', reason: 'сверка не проводилась' },
        { field: 'date', label: 'Дата', reason: 'сверка не проводилась' }],
      recheck: null,
    },
    freshness: свежесть({ checked_at: null, checked_at_basis: '', checked_hash: null, current_hash: null }),
    differences: [], sources: источник('103'), records: 1, aggregate: null, disclaimer: ОГОВОРКА,
  },
  'c-none': {
    entity_type: 'contract', entity_id: 'c-none', exists: true, scope: 'self', scope_label: '',
    state: 'no_source', state_label: 'Нет данных для сравнения', entity_verified: false,
    state_note: '', matching: { by_status: {}, labels: {} },
    verification: {
      status: 'not_checked', label: 'Не проверено', compared_fields: [], checked_fields: [],
      snapshot_fields: [], snapshot_basis: '', unchecked_fields: [], recheck: null,
    },
    freshness: свежесть({ checked_at: null, checked_at_basis: '', baseline: '', checked_hash: null, current_hash: null }),
    differences: [], sources: [], records: 0, aggregate: null, disclaimer: ОГОВОРКА,
  },
  // Контрагент: сводка по договорам, а не проверка самой карточки.
  'cp-1': {
    entity_type: 'counterparty', entity_id: 'cp-1', exists: true,
    scope: 'contracts_of_counterparty',
    scope_label: 'Отметка собрана из договоров контрагента; сама карточка отдельно не сверялась.',
    state: 'differences', state_label: 'Расхождения с бухгалтерией', entity_verified: false,
    state_note: 'Сводка по договорам контрагента.',
    matching: { by_status: { matched: 3 }, labels: { matched: 'Сопряжено' } },
    verification: {
      status: 'differences', label: 'Расхождения',
      compared_fields: [{ field: 'number', label: 'Номер', source: 'ЭС-2/26', space: 'ЭС-002', equal: false, basis: '', recheck: false }],
      checked_fields: [], snapshot_fields: [], snapshot_basis: '',
      unchecked_fields: ПОСТОЯННО_НЕ_СВЕРЕНО, recheck: null,
    },
    freshness: свежесть({ checked_hash: null, current_hash: null }),
    differences: [{ field: 'number', label: 'Номер', source: 'ЭС-2/26', space: 'ЭС-002' }],
    sources: источник('12-41'), records: 3,
    aggregate: {
      contracts_total: 2, with_source: 2, without_source: 0,
      by_state: { matched_checked: 1, differences: 1 },
      contracts: [
        { id: 'c-ok', number: 'ЭС-001', date: '2026-01-15', type_code: 'Энергоснабжение', state: 'matched_checked', state_label: 'Совпадает по сверенным реквизитам', records: 2 },
        { id: 'c-diff', number: 'ЭС-002', date: '2026-02-20', type_code: 'Энергоснабжение', state: 'differences', state_label: 'Расхождения с бухгалтерией', records: 1 },
      ],
    },
    disclaimer: ОГОВОРКА,
  },
  'cp-2': {
    entity_type: 'counterparty', entity_id: 'cp-2', exists: true,
    scope: 'contracts_of_counterparty',
    scope_label: 'Отметка собрана из договоров контрагента; сама карточка отдельно не сверялась.',
    state: 'stale', state_label: 'Устарело, нужна повторная сверка', entity_verified: false,
    state_note: 'Сводка по договорам контрагента.',
    matching: { by_status: { matched: 1, candidate: 1 }, labels: { matched: 'Сопряжено', candidate: 'Нужна проверка' } },
    verification: {
      status: 'stale', label: 'Устарела', compared_fields: [], checked_fields: [],
      snapshot_fields: [], snapshot_basis: '', unchecked_fields: ПОСТОЯННО_НЕ_СВЕРЕНО, recheck: null,
    },
    freshness: свежесть({ stale: true, stale_records: 1, checked_at: '2026-10-20', checked_hash: null, current_hash: null }),
    differences: [], sources: источник('77-103'), records: 2,
    aggregate: {
      contracts_total: 3, with_source: 2, without_source: 1,
      by_state: { stale: 1, needs_check: 1, no_source: 1 },
      contracts: [
        { id: 'c-stale', number: 'АР-003', date: '2026-03-10', type_code: 'Аренда', state: 'stale', state_label: 'Устарело', records: 1 },
        { id: 'c-need', number: 'АР-004', date: '2026-04-01', type_code: 'Аренда', state: 'needs_check', state_label: 'Требует сверки', records: 1 },
        { id: 'c-none', number: 'СЕРВ-005', date: '2026-05-05', type_code: 'Обслуживание', state: 'no_source', state_label: 'Нет данных для сравнения', records: 0 },
      ],
    },
    disclaimer: ОГОВОРКА,
  },
}

/** Правка сверенного поля устаревляет проверку, правка постороннего — нет. */
export function afterEdit(id, field) {
  const s = JSON.parse(JSON.stringify(SUMMARIES[id]))
  if (!s.verification.compared_fields.some((f) => f.label.toLowerCase() === field)) return s
  s.state = 'stale'
  s.state_label = 'Устарело, нужна повторная сверка'
  s.state_note = 'Карточку правили после сверки: изменилось сверенное поле «' + field + '».'
  s.verification.status = 'stale'
  s.freshness = { ...s.freshness, stale: true, stale_records: 1, current_hash: 'edited-9999' }
  return s
}
