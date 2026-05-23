/**
 * Email Parser — извлечение данных из .eml файлов через postal-mime.
 * Возвращает: тело письма (text/html), заголовки, список вложений.
 */

import type { ExtractResult } from '../extract'

interface EmailAttachment {
  filename: string
  mimeType: string
  size: number
  content: Uint8Array
}

export interface EmailParseResult extends ExtractResult {
  /** Вложения из письма (для рекурсивной обработки pipeline) */
  attachments: EmailAttachment[]
}

export async function parseEmail(file: File): Promise<EmailParseResult> {
  try {
    const PostalMime = (await import('postal-mime')).default
    const arrayBuffer = await file.arrayBuffer()
    const parser = new PostalMime()
    const email = await parser.parse(arrayBuffer)

    // Собираем текст: предпочитаем text, fallback на html (без тегов)
    let bodyText = ''
    if (email.text) {
      bodyText = email.text
    } else if (email.html) {
      bodyText = stripHtml(email.html)
    }

    // Заголовки → metadata
    const metadata: Record<string, string> = {}

    if (email.from?.address) {
      metadata['_email.from'] = email.from.name
        ? `${email.from.name} <${email.from.address}>`
        : email.from.address
    }

    if (email.to?.length) {
      metadata['_email.to'] = email.to
        .map((r) => r.name ? `${r.name} <${r.address}>` : r.address)
        .join(', ')
    }

    if (email.subject) {
      metadata['_email.subject'] = email.subject
    }

    if (email.date) {
      metadata['_email.date'] = email.date
    }

    if (email.messageId) {
      metadata['_email.messageId'] = email.messageId
    }

    // Вложения
    const attachments: EmailAttachment[] = (email.attachments ?? [])
      .filter((att) => att.filename && att.content)
      .map((att) => {
        const buf = typeof att.content === 'string'
          ? new TextEncoder().encode(att.content)
          : new Uint8Array(att.content as ArrayBuffer)
        return {
          filename: att.filename ?? 'attachment',
          mimeType: att.mimeType ?? 'application/octet-stream',
          size: buf.byteLength,
          content: buf,
        }
      })

    if (attachments.length > 0) {
      metadata['_email.attachments'] = String(attachments.length)
      metadata['_email.attachmentNames'] = attachments
        .map((a) => a.filename)
        .join(', ')
    }

    // Собираем полный текст для classify
    const parts: string[] = []
    if (email.subject) parts.push(`Тема: ${email.subject}`)
    if (metadata['_email.from']) parts.push(`От: ${metadata['_email.from']}`)
    if (metadata['_email.date']) parts.push(`Дата: ${metadata['_email.date']}`)
    if (bodyText) parts.push('', bodyText)

    return {
      text: parts.join('\n').trim(),
      metadata,
      attachments,
    }
  } catch (err) {
    console.error('Email parse error:', err)
    // Fallback: пробуем как plain text
    try {
      const text = await file.text()
      return {
        text,
        metadata: { _extractError: `Email парсер: ${String(err)}` },
        attachments: [],
      }
    } catch {
      return {
        text: '',
        metadata: { _extractError: `Email парсер: ${String(err)}` },
        attachments: [],
      }
    }
  }
}

/** Именованные HTML-сущности (частые в русских email) */
const HTML_ENTITIES: Record<string, string> = {
  '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
  '&apos;': "'", '&ndash;': '–', '&mdash;': '—', '&laquo;': '«', '&raquo;': '»',
  '&lsquo;': '\u2018', '&rsquo;': '\u2019', '&ldquo;': '\u201C', '&rdquo;': '\u201D',
  '&bull;': '•', '&hellip;': '…', '&trade;': '™', '&copy;': '©', '&reg;': '®',
  '&minus;': '−', '&times;': '×', '&divide;': '÷', '&plusmn;': '±',
  '&euro;': '€', '&pound;': '£', '&yen;': '¥',
}

/** Убрать HTML-теги, оставить текст */
function stripHtml(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<\/tr>/gi, '\n')
    .replace(/<\/li>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&[a-z]+;/gi, (m) => HTML_ENTITIES[m.toLowerCase()] ?? m)
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
