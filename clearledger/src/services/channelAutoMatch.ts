/**
 * Автоподбор канала для файла при ручной загрузке с диска.
 *
 * Эвристика (без настройки): ключевые слова имени файла → тип документа в
 * потоках канала; иначе расширение → тип источника канала; иначе — единственный
 * канал. Пользователь всегда может переопределить выбор вручную.
 */

import type { Channel, Source } from '@/types/channel'
import { getChannelSourceIds } from '@/types/channel'

// Ключевые слова в имени файла → возможные docTypeId потоков канала.
const NAME_HINTS: { re: RegExp; docTypes: string[]; label: string }[] = [
  { re: /смен|shift|орп/i,                         docTypes: ['shift_report'],   label: 'сменный отчёт' },
  { re: /ттн|поставк|накладн|receipt|приход/i,     docTypes: ['receipt'],        label: 'ТТН/поступление' },
  { re: /цен|price|тариф/i,                        docTypes: ['price'],          label: 'цены' },
  { re: /выписк|bank|платеж|платёж/i,              docTypes: ['bank_statement'], label: 'банк. выписка' },
  { re: /сч[её]т|invoice|фактур|\bсф\b/i,          docTypes: ['invoice'],        label: 'счёт/СФ' },
  { re: /транзакц|transaction|отпуск/i,            docTypes: ['sts_transactions', 'msto_transactions', 'corp_transactions'], label: 'транзакции' },
]

// Расширение → предпочтительные типы источника канала.
const EXT_SOURCE_TYPES: Record<string, string[]> = {
  xml:  ['1c', 'edi', 'msto'],
  eml:  ['email'], msg: ['email'],
  xlsx: ['rest', 'tradecorp', 'watch-dir', 'ftp'],
  xls:  ['rest', 'tradecorp', 'watch-dir', 'ftp'],
  csv:  ['rest', 'tradecorp', 'watch-dir', 'ftp'],
  pdf:  ['watch-dir', 'email'],
  jpg:  ['watch-dir', 'email'], jpeg: ['watch-dir', 'email'],
  png:  ['watch-dir', 'email'], tiff: ['watch-dir', 'email'],
  json: ['rest', 'webhook'],
}

export interface ChannelSuggestion {
  channel: Channel
  reason: string
}

/** Подобрать канал для файла. null — не удалось однозначно. */
export function suggestChannelForFile(
  file: File,
  channels: Channel[],
  sources: Source[],
): ChannelSuggestion | null {
  const name = file.name.toLowerCase()
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1) : ''
  const active = channels.filter((c) => c.status === 'active')
  const pool = active.length ? active : channels.filter((c) => c.status !== 'draft')
  if (pool.length === 0) return null

  // 1) Ключевые слова имени → docType в enabled-потоках канала.
  for (const hint of NAME_HINTS) {
    if (!hint.re.test(name)) continue
    const ch = pool.find((c) => c.streams.some((s) => s.enabled && hint.docTypes.includes(s.docTypeId)))
    if (ch) return { channel: ch, reason: `тип «${hint.label}» по имени файла` }
  }

  // 2) Расширение → тип источника канала.
  const wantTypes = EXT_SOURCE_TYPES[ext]
  if (wantTypes?.length) {
    const srcById = new Map(sources.map((s) => [s.id, s]))
    const ch = pool.find((c) =>
      getChannelSourceIds(c).some((id) => {
        const s = srcById.get(id)
        return s && wantTypes.includes(s.type)
      }),
    )
    if (ch) return { channel: ch, reason: `формат .${ext}` }
  }

  // 3) Единственный подходящий канал.
  if (pool.length === 1) return { channel: pool[0], reason: 'единственный канал' }
  return null
}
