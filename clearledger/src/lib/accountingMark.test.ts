// node --test --experimental-strip-types src/lib/accountingMark.test.ts
// Импортируются только типы приложения, а они стираются при запуске: сборка и
// окружение браузера не нужны.
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MARK_LABEL, MATCHING_LABEL, VERIFICATION_LABEL, chunkIds, isDerived, markHint,
  markKey, markLines, markState, полеRU, ОТСУТСТВИЕ_ИСТОЧНИКА,
} from './accountingMark.ts'

const сводка = (p: Record<string, unknown> = {}) => ({
  entity_type: 'contract', entity_id: 'c1', exists: true, scope: 'self', scope_label: '',
  state: 'matched_checked', state_label: 'Совпадает по сверенным реквизитам',
  state_note: '', entity_verified: false,
  matching: { by_status: { matched: 1 }, labels: { matched: 'Сопряжено' } },
  verification: {
    status: 'verified', label: 'Сверено',
    compared_fields: [
      { field: 'number', label: 'Номер', source: 'ЭС-001', space: 'ЭС-001', equal: true, basis: '', recheck: false },
      { field: 'date', label: 'Дата', source: '15.01.2026', space: '15.01.2026', equal: true, basis: '', recheck: false },
    ],
    checked_fields: ['number', 'date'],
    snapshot_fields: ['counterparty_id', 'date', 'number', 'type_code'],
    snapshot_basis: 'Снимок полей карточки отвечает за устаревание, сверкой не является.',
    unchecked_fields: [{ field: 'inn_kpp', label: 'ИНН / КПП', reason: 'источник значения не дал' }],
    recheck: null,
  },
  freshness: {
    stale: false, stale_records: 0, checked_at: '2026-10-28',
    checked_at_basis: 'дата применения сверки', rechecked_at: null,
    baseline: 'База устаревания — снимок карточки.', checked_hash: 'a1', current_hash: 'a1',
  },
  differences: [], sources: [], records: 1, aggregate: null, disclaimer: '', ...p,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any

test('подписи канона сверки названы словами задачи, а не «проверено»', () => {
  // «Сверено» в интерфейсе означает конкретные поля, а не все реквизиты договора:
  // короткое «Проверено» люди читали как проверку всего документа.
  assert.equal(MARK_LABEL.matched_checked, 'Сверенные реквизиты совпадают')
  assert.equal(MARK_LABEL.contracts_checked, 'Сверенные реквизиты совпадают')
  assert.equal(MARK_LABEL.differences, 'Есть расхождения')
  assert.equal(MARK_LABEL.stale, 'Нужна повторная сверка')
  assert.equal(MARK_LABEL.needs_check, 'Требует сверки')
  assert.equal(MARK_LABEL.no_source, 'Нет данных для сравнения')
  // Ось проверки в «Разборе» и отметка в карточках говорят одними словами.
  assert.equal(VERIFICATION_LABEL.verified, MARK_LABEL.matched_checked)
  assert.equal(VERIFICATION_LABEL.not_checked, MARK_LABEL.needs_check)
  assert.equal(VERIFICATION_LABEL.stale, MARK_LABEL.stale)
  // Ось сопряжения — свои слова: «сопряжено» не значит «реквизиты сверены».
  assert.equal(MATCHING_LABEL.matched, 'Сопряжено')
  assert.notEqual(MATCHING_LABEL.matched, MARK_LABEL.matched_checked)
})

test('загрузка, ошибка запроса и отсутствие строки — три разных состояния', () => {
  // Ошибка запроса, показанная как «нет данных для сравнения», врёт: сведения,
  // возможно, есть, и человек об этом не узнает.
  assert.equal(markState(undefined, true, false), 'loading')
  assert.equal(markState(undefined, false, true), 'error')
  assert.equal(markState(undefined, false, false), 'no_source')
  // Загрузка важнее ошибки: повторный запрос не должен мигать «недоступно».
  assert.equal(markState(undefined, true, true), 'loading')
  // Состояние приходит с сервера, экран его не пересчитывает.
  assert.equal(markState(сводка({ state: 'differences' }), false, false), 'differences')
  assert.equal(markState(сводка({ state: 'contracts_checked' }), false, false), 'contracts_checked')
})

test('отсутствие строки не выдаётся за отсутствие договора в учёте', () => {
  assert.equal(markHint(undefined, 'no_source'), ОТСУТСТВИЕ_ИСТОЧНИКА)
  assert.match(markHint(undefined, 'no_source'), /не означает, что договора нет в учёте/)
  assert.match(markHint(сводка({ state: 'no_source', records: 0 }), 'no_source'),
    /не означает, что договора нет в учёте/)
})

test('показываются доказательства сверки, а не снимок наших полей', () => {
  // Снимок (counterparty_id, type_code) отвечает за устаревание и сам по себе
  // ничего не подтверждает: выдать его за «сверено» значит соврать.
  const L = markLines(сводка(), 'matched_checked')
  const h = L.join(' · ')
  assert.match(h, /Сверено с выгрузкой: Номер — совпадает; Дата — совпадает/)
  assert.doesNotMatch(h, /counterparty_id|type_code/)
  assert.match(h, /Не сверялись: ИНН \/ КПП \(источник значения не дал\)/)
  assert.match(h, /Снимок полей карточки отвечает за устаревание/)
})

test('сырые имена полей человеку не показываются', () => {
  assert.equal(полеRU({ field: 'inn_kpp', label: 'ИНН / КПП' }), 'ИНН / КПП')
  // Подписи нет — показываем хотя бы имя поля, но не «[object Object]».
  assert.equal(полеRU({ field: 'number' }), 'number')
  const h = markHint(сводка({
    verification: {
      status: 'not_checked', label: '', compared_fields: [], checked_fields: [],
      snapshot_fields: [], snapshot_basis: '',
      unchecked_fields: [{ field: 'posted_in_1c', label: 'Проведение в 1С', reason: 'выгрузка не содержит признака' }],
      recheck: null,
    },
  }), 'needs_check')
  assert.doesNotMatch(h, /\[object Object\]/)
  assert.match(h, /Проведение в 1С \(выгрузка не содержит признака\)/)
})

test('несравнимое поле не выдаётся за совпадение', () => {
  // equal=null значит «сравнивать было нечего»: в выгрузке значения нет.
  const h = markHint(сводка({
    verification: {
      status: 'partial', label: '', checked_fields: [], snapshot_fields: [], snapshot_basis: '',
      compared_fields: [{ field: 'date', label: 'Дата', source: '', space: '15.01.2026',
        equal: null, basis: 'в выгрузке значения нет', recheck: false }],
      unchecked_fields: [], recheck: null,
    },
  }), 'needs_check')
  assert.match(h, /Дата — сравнивать нечего: в выгрузке значения нет/)
  assert.doesNotMatch(h, /Дата — совпадает/)
})

test('ось свежести видна и при расхождениях, а не прячется за цветом', () => {
  // Сервер выставляет stale параллельно состоянию: красное «расхождения» не
  // должно скрывать, что сверку вдобавок пора повторить.
  const h = markHint(сводка({
    state: 'differences',
    differences: [{ field: 'number', label: 'Номер', source: 'ЭС-2/26', space: 'ЭС-002' }],
    freshness: { stale: true, stale_records: 2, checked_at: '2026-10-20',
      checked_at_basis: '', rechecked_at: '2026-10-27', baseline: '', checked_hash: 'a', current_hash: 'b' },
  }), 'differences')
  assert.match(h, /Карточку правили после сверки/)
  assert.match(h, /устаревших строк: 2/)
  assert.match(h, /Повторная сверка 27\.10\.2026/)
})

test('отметка контрагента и площадки не выдаётся за их полную проверку', () => {
  const cp = сводка({
    entity_type: 'counterparty', scope: 'contracts_of_counterparty', state: 'contracts_checked',
    aggregate: { contracts_total: 7, with_source: 4, without_source: 3, by_state: {}, contracts: [] },
  })
  assert.ok(isDerived(cp))
  const h = markHint(cp, 'contracts_checked')
  assert.match(h, /Сводка по договорам: 4 из 7/)
  assert.match(h, /сама карточка отдельно не сверялась/)
  // У самого договора такой оговорки быть не должно — это его собственная сверка.
  assert.ok(!isDerived(сводка()))
  assert.doesNotMatch(markHint(сводка(), 'matched_checked'), /сама карточка отдельно не сверялась/)
})

test('источник назван файлом, строками и датой данных', () => {
  const h = markHint(сводка({
    sources: [{ record_id: 'r1', file: 'Свод.xlsx', sheet: 'База', rows: '12-14',
      period: '2026-09', as_of: '2026-09-30', batch_id: 'b1', counterparty: '', contract: '', status: 'matched' }],
  }), 'matched_checked')
  assert.match(h, /Источник: Свод\.xlsx, лист База, строки 12-14, период 2026-09, данные на 30\.09\.2026/)
})

test('длинный отбор режется под предел сервера, а не уходит одним запросом', () => {
  // Реестр из девятисот договоров: запрос на строку был бы девятьюстами
  // обращениями, а один запрос целиком сервер отклонит по своему пределу.
  const ids = Array.from({ length: 901 }, (_, i) => 'c' + i)
  const parts = chunkIds(ids, 300)
  assert.equal(parts.length, 4)
  assert.ok(parts.every((p) => p.length <= 300))
  assert.deepEqual(parts.flat(), ids)
  assert.deepEqual(chunkIds([], 300), [])
  assert.throws(() => chunkIds(ids, 0))
})

test('ключ кеша зависит от состава отбора, а не от его сортировки', () => {
  // Смена сортировки переставляет строки, но данные те же: иначе каждый щелчок
  // по столбцу заново грузил бы сверку всего экрана.
  assert.equal(markKey(['b', 'a', 'c']), markKey(['c', 'b', 'a']))
  assert.equal(markKey(['a', 'a', 'b']), 'a,b')
  assert.notEqual(markKey(['a', 'b']), markKey(['a', 'b', 'c']))
})
