/**
 * Разметка-лайт для описаний и реплик.
 *
 * Своя, а не библиотека: нужно ровно пять вещей — **жирный**, *курсив*, `код`,
 * списки и ссылки. Полноценный markdown тянет парсер и санитайзер ради того,
 * что человек в описании задачи всё равно не пишет.
 *
 * Главное — рендерим React-элементами, без `dangerouslySetInnerHTML`: описание
 * приходит от людей, в том числе внешних (письмом), и вставлять его в DOM как
 * HTML нельзя ни при каких обстоятельствах.
 */
import { cn } from '@/lib/utils'

/** Разбор строки на куски: **жирный**, *курсив*, `код`, ссылка. */
function inline(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  // Один проход одним выражением: порядок альтернатив задаёт приоритет —
  // код раньше жирного, иначе `**` внутри кода съест разметка.
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(https?:\/\/\S+)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const piece = m[0]
    const key = `${keyBase}-${i++}`
    if (piece.startsWith('`')) {
      out.push(
        <code key={key} className="rounded bg-muted px-1 py-px font-mono text-[0.9em]">
          {piece.slice(1, -1)}
        </code>,
      )
    } else if (piece.startsWith('**')) {
      out.push(<strong key={key}>{piece.slice(2, -2)}</strong>)
    } else if (piece.startsWith('*')) {
      out.push(<em key={key}>{piece.slice(1, -1)}</em>)
    } else {
      out.push(
        // Внешняя ссылка открывается в новой вкладке и без передачи реферера:
        // адрес пространства не должен утекать на чужой сайт.
        <a key={key} href={piece} target="_blank" rel="noreferrer noopener"
          className="text-primary hover:underline">{piece}</a>,
      )
    }
    last = m.index + piece.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function RichText({ text, className }: { text: string; className?: string }) {
  const lines = text.split('\n')
  const blocks: React.ReactNode[] = []
  let list: React.ReactNode[] = []

  const flush = () => {
    if (!list.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-1 list-disc space-y-0.5 pl-5">
        {list}
      </ul>,
    )
    list = []
  }

  lines.forEach((line, i) => {
    const item = line.match(/^\s*[-*•]\s+(.*)$/)
    if (item) {
      list.push(<li key={`li-${i}`}>{inline(item[1], `i${i}`)}</li>)
      return
    }
    flush()
    if (!line.trim()) {
      blocks.push(<div key={`sp-${i}`} className="h-2" />)
      return
    }
    blocks.push(<p key={`p-${i}`}>{inline(line, `p${i}`)}</p>)
  })
  flush()

  return <div className={cn('space-y-0.5 whitespace-pre-wrap', className)}>{blocks}</div>
}

export default RichText
