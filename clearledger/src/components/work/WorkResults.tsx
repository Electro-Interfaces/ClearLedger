import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { getWorkResults, retryWorkResult } from '@/services/workContextService'

export function WorkResults({ companyId, kind, id }: { companyId: string; kind: 'doc' | 'task'; id: string }) {
  const qc = useQueryClient()
  const key = ['work-results', companyId, kind, id]
  const results = useQuery({ queryKey: key, queryFn: () => getWorkResults(companyId, kind, id), refetchInterval: 30000 })
  const retry = useMutation({ mutationFn: (resultId: string) => retryWorkResult(companyId, resultId),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast.success('Результат поставлен на повторную доставку') }, onError: (e) => toast.error(e.message) })
  if (results.isError) return <div className="text-xs" role="alert">Не удалось проверить передачу результата. <button className="underline" onClick={() => void results.refetch()}>Повторить</button></div>
  if (!results.data?.items.length) return null
  return <details className="rounded-md border p-3 text-sm" open={results.data.items.some((r) => r.pending)}><summary className="cursor-pointer font-medium">Результаты для приложений</summary>
    <ul className="mt-2 space-y-3">{results.data.items.map((r) => <li key={r.id}>
      {r.url ? <Link className="text-primary underline" to={r.url}>{r.title}</Link> : <span>{r.title}</span>}
      <p className="mt-1 text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString('ru')} · {r.outcome === 'done' || r.outcome === 'approved' ? 'Принято' : 'Отклонено или отменено'} · {r.pending ? r.error ? 'Не удалось доставить' : 'Ожидает доставки' : 'Передано приложению'}</p>
      {r.pending && r.error && <Button className="mt-2" size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(r.id)}>Повторить доставку</Button>}
    </li>)}</ul>
  </details>
}
