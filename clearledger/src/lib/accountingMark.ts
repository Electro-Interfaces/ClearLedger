/**
 * Отметка сверки с бухгалтерией — подписи и разбор состояния.
 *
 * Чистая часть общей отметки: словари подписей, выбор состояния и пояснение.
 * Вынесена из компонента, чтобы правила проверялись тестом и чтобы один и тот же
 * словарь читали «Разбор», «Объекты», реестр договоров и карточки — иначе одно
 * состояние называлось бы в разделах по-разному.
 *
 * Три оси канона сверки (28.10.2026) раздельны и в одну галочку не сводятся:
 *   сопряжение — опознана ли строка выгрузки;
 *   проверка   — какие именно реквизиты сверены, а какие нет;
 *   свежесть   — правили ли карточку после сверки.
 * Сводное состояние считает сервер; здесь только его подписи и пояснения.
 */
import type {
  AccountingComparedField, AccountingLinkSummary, AccountingRecheck, AccountingState,
  LinkStatus, VerificationStatus,
} from '@/services/accountingSpaceService'

/**
 * Ключи кеша отметок — их сбрасывают мутации справочников.
 *
 * Правка сверенного поля устаревляет проверку на сервере, и ждать `staleTime`
 * нельзя: человек сохранил карточку и должен увидеть новое состояние сразу.
 */
export const MARK_KEYS = ['acct-space-marks', 'acct-space-mark', 'acct-space-links'] as const

/** Состояния сервера плюс состояния запроса — последние не являются состоянием сверки. */
export type MarkState = AccountingState | 'loading' | 'error'

/**
 * Обязательные формулировки экрана. Сервер присылает и свой `state_label`, но
 * слова интерфейса заданы здесь, чтобы они не разъезжались между разделами.
 *
 * «Сверенные реквизиты совпадают» намеренно не «Проверено»: сверяются конкретные
 * поля (номер, дата, контрагент, вид), а не весь договор.
 */
export const MARK_LABEL: Record<MarkState, string> = {
  matched_checked: 'Сверенные реквизиты совпадают',
  contracts_checked: 'Сверенные реквизиты совпадают',
  differences: 'Есть расхождения',
  stale: 'Нужна повторная сверка',
  needs_check: 'Требует сверки',
  no_source: 'Нет данных для сравнения',
  loading: 'Сверка загружается',
  error: 'Сверка недоступна',
}

/** Подписи оси проверки — те же слова, что у отметки. */
export const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  verified: 'Сверенные реквизиты совпадают',
  partial: 'Часть реквизитов сверена',
  differences: 'Есть расхождения',
  not_checked: 'Требует сверки',
  stale: 'Нужна повторная сверка',
}

/** Подписи оси сопряжения — опознана ли строка выгрузки. */
export const MATCHING_LABEL: Record<LinkStatus, string> = {
  matched: 'Сопряжено', related: 'Связанные документы',
  unmatched: 'Не сопряжено', candidate: 'Нужна проверка',
}

export const ОТСУТСТВИЕ_ИСТОЧНИКА = 'Строки бухгалтерской выгрузки на эту карточку не легли. '
  + 'Выгрузка охватывает свой период: отсутствие строки не означает, что договора нет в учёте.'

/**
 * Состояние отметки.
 *
 * Четыре разные вещи, которые легко свести в одну: идёт загрузка, запрос упал,
 * сводки на карточку нет. Ошибка запроса не должна выглядеть как «нет данных для
 * сравнения»: в первом случае сведения, возможно, есть, и человек не узнает об этом.
 */
export const markState = (
  s: AccountingLinkSummary | undefined, loading: boolean, error: boolean,
): MarkState => loading ? 'loading' : error ? 'error' : s?.state ?? 'no_source'

/** Проверена ли сама карточка, а не её договоры. */
export const isDerived = (s: AccountingLinkSummary | undefined): boolean =>
  !!s && s.scope !== 'self'

export const дата = (iso: string | null | undefined, locale = 'ru-RU') => {
  if (!iso) return ''
  const d = new Date(iso.length <= 10 ? iso + 'T12:00:00Z' : iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(locale, { timeZone: 'Europe/Moscow' })
}

/** Русская подпись поля: сырой `field` человеку не показываем. */
export const полеRU = (f: { label?: string; field: string }) => f.label || f.field

/**
 * Исход сравнения одного поля словами.
 *
 * `unknown` — «сравнивать было нечего», а не конфликт: красить его как
 * расхождение значит выдумать проблему. Если прогон записал о поле своё
 * «совпадает», а пересчёт дал `unknown`, видно и то и другое: утверждение
 * прогона — свидетельство, а не отметка. Так читается и название стороны:
 * имена совместимы, но ИНН в выгрузке нет, и сверкой контрагента это не стало.
 */
export function сравнение(f: AccountingComparedField): { text: string; tone: 'ok' | 'bad' | 'none' } {
  const spor = f.claimed && f.claimed !== f.result
    ? ' Прогон записал «' + ИСХОД[f.claimed] + '»'
      + (f.claimed_basis ? ': ' + f.claimed_basis : '') + ' — это свидетельство, не отметка.'
    : ''
  if (f.result === 'difference') {
    return { tone: 'bad', text: 'расходится: в бухгалтерии «' + (f.source || '—')
      + '», здесь «' + (f.space || '—') + '».' + spor }
  }
  if (f.result === 'match') {
    return { tone: 'ok', text: 'совпадает'
      + (f.origin === 'recheck' ? ' (по повторной сверке)' : '') + '.' + spor }
  }
  return { tone: 'none', text: 'сравнивать нечего' + (f.basis ? ': ' + f.basis : '') + '.' + spor }
}

const ИСХОД: Record<string, string> = {
  match: 'совпадает', difference: 'расходится', unknown: 'сравнивать нечего',
}

const RECHECK_LABEL: Record<string, string> = {
  confirmed_fields: 'проверенные реквизиты совпали',
  needs_clarification: 'нужны уточнения',
  candidate_found: 'найдены похожие карточки, связь нужно проверить',
  no_links: 'строка пока не связана с договором',
}

/** Свидетельство повторной сверки, если оно вообще принято. */
export function recheckLine(r: AccountingRecheck | null | undefined): string | null {
  if (!r) return null
  if (!r.applicable) {
    return 'Повторная сверка не принята: ' + (r.not_applicable_reason
      || 'прогон шёл по другой редакции файла') + '. Отсутствием сверки это не является.'
  }
  const блок = (r.open_questions ?? []).filter((q) => q.blocking)
  return 'Повторная сверка' + (r.checked_at ? ' ' + дата(r.checked_at) : '')
    + (r.overall ? ': ' + (RECHECK_LABEL[r.overall] ?? r.overall) : '')
    + (блок.length ? '. Нерешённое: ' + блок.map((q) => q.label).join('; ') : '')
}

/**
 * Пояснение отметки строками — одно правило на подсказку и на раскрытие.
 *
 * Оси не сливаются: сопряжение, сверенные реквизиты с доказательством, несверенные
 * с причиной, расхождения, свежесть и источник идут отдельными строками. Свежесть
 * показывается и при расхождениях: иначе ось устаревания прячется за красным цветом.
 */
export function markLines(s: AccountingLinkSummary | undefined, state: MarkState): string[] {
  if (state === 'loading') return ['Сведения бухгалтерии загружаются']
  if (state === 'error') return ['Запрос сведений не удался — это ошибка получения, а не отсутствие строк']
  if (!s) return [ОТСУТСТВИЕ_ИСТОЧНИКА]
  const L: string[] = []
  if (s.state_note) L.push(s.state_note)

  if (state === 'no_source') {
    if (!s.state_note) L.push(ОТСУТСТВИЕ_ИСТОЧНИКА)
  } else {
    const сопр = Object.entries(s.matching.by_status).filter(([, n]) => n)
      .map(([k, n]) => (s.matching.labels?.[k as LinkStatus] ?? k) + ': ' + n)
    if (сопр.length) L.push('Сопряжение — ' + сопр.join(', ') + '; строк источника ' + s.records)

    // Доказательства, а не снимок: что сравнивали, с чем и чем кончилось.
    const ср = s.verification.compared_fields ?? []
    if (ср.length) {
      L.push('Сверено с выгрузкой: ' + ср.map((f) => полеRU(f) + ' — ' + сравнение(f).text).join(' '))
    } else {
      L.push('Сверено с выгрузкой: ничего — реквизиты не сверялись')
    }
    const пов = recheckLine(s.verification.recheck)
    if (пов) L.push(пов)

    const нет = s.verification.unchecked_fields ?? []
    if (нет.length) {
      L.push('Не сверялись: ' + нет.map((f) => полеRU(f) + (f.reason ? ' (' + f.reason + ')' : '')).join('; '))
    }
    if (s.verification.snapshot_basis) L.push(s.verification.snapshot_basis)

    const src = s.sources[0]
    if (src?.file) {
      L.push('Источник: ' + [src.file, src.sheet && 'лист ' + src.sheet, src.rows && 'строки ' + src.rows,
        src.period && 'период ' + src.period, src.as_of && 'данные на ' + дата(src.as_of)]
        .filter(Boolean).join(', '))
    }
  }

  // Свежесть — своя ось, видна и при расхождениях.
  if (s.freshness.stale) {
    L.push('Карточку правили после сверки — проверку нужно повторить'
      + (s.freshness.stale_records > 1 ? ' (устаревших строк: ' + s.freshness.stale_records + ')' : ''))
  }
  if (s.freshness.checked_at) {
    L.push('Сверено ' + дата(s.freshness.checked_at)
      + (s.freshness.checked_at_basis ? ' — ' + s.freshness.checked_at_basis : ''))
  }
  if (s.freshness.rechecked_at) L.push('Повторная сверка ' + дата(s.freshness.rechecked_at))

  if (isDerived(s) && s.aggregate) {
    L.push('Сводка по договорам: ' + s.aggregate.with_source + ' из ' + s.aggregate.contracts_total
      + ' со сведениями бухгалтерии; сама карточка отдельно не сверялась')
  }
  if (s.disclaimer) L.push(s.disclaimer)
  return L
}

/** То же одной строкой — для доступного имени и подсказки. */
export const markHint = (s: AccountingLinkSummary | undefined, state: MarkState): string =>
  markLines(s, state).join(' · ')

/**
 * Резка списка id под предел одного запроса сводок.
 *
 * Строка списка своего запроса не делает: иначе реестр из девятисот договоров
 * даёт девятьсот обращений. Длинный отбор уходит частями по пределу сервера.
 */
export function chunkIds(ids: string[], size: number): string[][] {
  if (size < 1) throw new Error('размер части должен быть положительным')
  const out: string[][] = []
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size))
  return out
}

/** Состав отбора без порядка и повторов: ключ кеша не должен зависеть от сортировки. */
export const markKey = (ids: string[]): string => [...new Set(ids)].sort().join(',')
