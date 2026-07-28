/**
 * Рендер markdown для «Инфо» — без внешней зависимости.
 *
 * В TradeFrame для этого стоит react-markdown + remark-gfm; тащить их в Ядро ради
 * первой версии рано: тексты знания — заголовки, списки, ссылки, таблицы и цитаты,
 * а не произвольный markdown из интернета. Сырой HTML не вставляем вообще (никакого
 * dangerouslySetInnerHTML), поэтому XSS закрыт по построению.
 *
 * Когда понадобятся сноски, вложенные списки и прочая типографика — заменить
 * целиком на react-markdown, интерфейс компонента тот же.
 */
import { Fragment, type ReactNode } from 'react'

/** Жирный, курсив, `код` и ссылки внутри строки. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|_[^_]+_)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    const key = `${keyBase}-${i++}`
    if (t.startsWith('**')) out.push(<strong key={key}>{t.slice(2, -2)}</strong>)
    else if (t.startsWith('`')) {
      out.push(<code key={key} className="rounded bg-muted px-1 py-0.5 text-[0.9em]">{t.slice(1, -1)}</code>)
    } else if (t.startsWith('[')) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)
      out.push(mm
        ? <a key={key} href={mm[2]} target="_blank" rel="noopener noreferrer"
            className="text-primary hover:underline">{mm[1]}</a>
        : t)
    } else out.push(<em key={key}>{t.slice(1, -1)}</em>)
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ content }: { content: string }) {
  const lines = (content || '').split(/\r?\n/)
  const blocks: ReactNode[] = []
  let list: string[] = []
  let table: string[] = []
  let code: string[] | null = null

  const flushList = (key: string) => {
    if (!list.length) return
    blocks.push(
      <ul key={key} className="my-2 ml-4 list-disc space-y-1">
        {list.map((li, i) => <li key={i}>{inline(li, `${key}-${i}`)}</li>)}
      </ul>,
    )
    list = []
  }
  const flushTable = (key: string) => {
    if (table.length < 2) { table = []; return }
    const cells = (row: string) => row.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
    const head = cells(table[0])
    const body = table.slice(2).map(cells)   // вторая строка — разделитель
    blocks.push(
      <div key={key} className="my-3 overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b text-muted-foreground">
              {head.map((h, i) => <th key={i} className="text-left px-2 py-1 font-medium">{inline(h, `${key}-h-${i}`)}</th>)}
            </tr>
          </thead>
          <tbody>
            {body.map((r, ri) => (
              <tr key={ri} className="border-b border-border/30">
                {r.map((c, ci) => <td key={ci} className="px-2 py-1 align-top">{inline(c, `${key}-${ri}-${ci}`)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    )
    table = []
  }

  lines.forEach((raw, idx) => {
    const key = `b${idx}`
    if (raw.trim().startsWith('```')) {
      if (code === null) { flushList(`${key}-l`); flushTable(`${key}-t`); code = [] }
      else {
        blocks.push(
          <pre key={key} className="my-2 overflow-x-auto rounded-md bg-muted p-2 text-[11px]">
            <code>{code.join('\n')}</code>
          </pre>,
        )
        code = null
      }
      return
    }
    if (code !== null) { code.push(raw); return }

    const line = raw.trimEnd()
    if (line.trim().startsWith('|')) { flushList(`${key}-l`); table.push(line.trim()); return }
    flushTable(`${key}-t`)

    if (!line.trim()) { flushList(`${key}-l`); return }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      flushList(`${key}-l`)
      const level = h[1].length
      const cls = level === 1 ? 'text-base font-semibold mt-4 mb-1'
        : level === 2 ? 'text-sm font-semibold mt-3 mb-1'
        : 'text-xs font-semibold mt-2 mb-0.5'
      blocks.push(<div key={key} className={cls}>{inline(h[2], key)}</div>)
      return
    }
    // Иллюстрация отдельной строкой: скриншот экрана с выносками — обычный приём
    // инструкций, и он не должен превращаться в ссылку посреди абзаца.
    const img = /^!\[([^\]]*)\]\(([^)]+)\)\s*$/.exec(line.trim())
    if (img) {
      flushList(`${key}-l`)
      blocks.push(
        <figure key={key} className="my-3">
          <img src={img[2]} alt={img[1]} loading="lazy" referrerPolicy="no-referrer"
            className="w-full rounded-lg border border-border/60" />
          {img[1] && <figcaption className="mt-1 text-[11px] text-muted-foreground">{img[1]}</figcaption>}
        </figure>,
      )
      return
    }
    if (/^\s*[-*]\s+/.test(line)) { list.push(line.replace(/^\s*[-*]\s+/, '')); return }
    if (/^>\s?/.test(line)) {
      flushList(`${key}-l`)
      blocks.push(
        <blockquote key={key} className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
          {inline(line.replace(/^>\s?/, ''), key)}
        </blockquote>,
      )
      return
    }
    const num = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (num) { list.push(num[1]); return }
    flushList(`${key}-l`)
    blocks.push(<p key={key} className="my-1.5 leading-relaxed">{inline(line, key)}</p>)
  })
  flushList('tail-l')
  flushTable('tail-t')

  return <div className="text-sm">{blocks.map((b, i) => <Fragment key={i}>{b}</Fragment>)}</div>
}
