import { useQuery } from '@tanstack/react-query'
import { downloadBlob } from '@/services/apiClient'
import { readDocumentText, type DocumentText } from '@/services/docFileText'
import type { DocVersion } from '@/services/docsService'
import { QueryError } from '@/components/common/QueryError'

function useFileText(version: DocVersion) {
  return useQuery({
    queryKey: ['doc-file-text', version.file_id],
    queryFn: async () => {
      const blob = await downloadBlob(`/api/files/${version.file_id}`)
      return readDocumentText(new File([blob], version.file_name, { type: version.mime || blob.type }))
    }, staleTime: 5 * 60_000, gcTime: 5 * 60_000, retry: false,
  })
}

export function DocOfficePreview({ version }: { version: DocVersion }) {
  const query = useFileText(version)
  if (query.isPending) return <p role="status" className="text-sm text-muted-foreground">Читаем документ…</p>
  if (query.isError) return <QueryError message="Файл не прочитан" error={query.error} onRetry={() => void query.refetch()} />
  return <div className="w-full min-w-0 space-y-2">
    <p className="text-xs text-muted-foreground">Предпросмотр содержимого. Оформление оригинала может отличаться.</p>
    <OfficeContent data={query.data} />
  </div>
}

function OfficeContent({ data }: { data: DocumentText }) {
  return <>
    {data.truncated && <p role="status" className="text-xs text-muted-foreground">Показана часть большого файла. Полный документ доступен для скачивания.</p>}
    <div className="max-h-[31rem] overflow-auto rounded-md border bg-background p-3">
      {data.sheets ? data.sheets.map((sheet) => <table key={sheet.name} className="mb-4 text-left text-xs">
        <caption className="mb-2 text-left font-medium">{sheet.name}</caption>
        <tbody>{sheet.rows.map((row, i) => <tr key={i}>
          <th className="border bg-muted px-2 py-1 font-normal" scope="row">{i + 1}</th>
          {row.map((cell, j) => <td key={j} className="max-w-80 whitespace-pre-wrap border px-2 py-1">{cell}</td>)}
        </tr>)}</tbody>
      </table>) : <pre className="whitespace-pre-wrap break-words font-sans text-sm">{data.text || 'В файле нет текста.'}</pre>}
    </div>
  </>
}

export function DocVersionCompare({ before, after }: { before: DocVersion; after: DocVersion }) {
  const left = useFileText(before)
  const right = useFileText(after)
  if (left.isPending || right.isPending) return <p role="status" className="text-sm">Готовим сравнение…</p>
  if (left.isError || right.isError) return <QueryError message="Сравнение недоступно" error={left.error || right.error}
    onRetry={() => { void left.refetch(); void right.refetch() }} />
  const leftLines = new Set(left.data.text.split('\n'))
  const rightLines = new Set(right.data.text.split('\n'))
  return <div className="space-y-2">
    <p className="text-xs text-muted-foreground">Сравнивается извлечённый текст, без оформления. Выделены строки, которых нет в другой редакции.</p>
    {(left.data.truncated || right.data.truncated) && <p role="status" className="text-sm">Большой файл: сравнивается только показанная часть.</p>}
    <p className="text-sm font-medium">{left.data.text === right.data.text ? 'Извлечённый текст совпадает' : 'В тексте есть различия'}</p>
    <div className="grid min-w-0 gap-3 md:grid-cols-2">
      {[{ version: before, data: left.data, other: rightLines, label: 'Было' },
        { version: after, data: right.data, other: leftLines, label: 'Стало' }].map(({ version, data, other, label }) =>
        <section key={version.id} className="min-w-0 rounded-md border p-3">
          <h3 className="mb-2 break-words text-sm font-medium">{label} · редакция {version.revision} · {version.file_name}</h3>
          <div className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">
            {data.text.split('\n').map((line, index) => <div key={index}
              className={line && !other.has(line) ? 'border-l-2 border-primary bg-primary/10 px-1' : 'px-1'}>{line || '\u00a0'}</div>)}
          </div>
        </section>)}
    </div>
  </div>
}
