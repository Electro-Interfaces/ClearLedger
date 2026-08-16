/**
 * Настройка «Дела»: виды документов и нумераторы.
 *
 * Вид несёт правило нумерации, поэтому правит его администратор пространства:
 * номер стоит в документе и потом не переписывается.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY } from '@/services/docsService'
import { useDocsView } from './DocsLayout'

const SCOPE_LABEL: Record<string, string> = {
  kind: 'сквозная по виду',
  kind_year: 'по виду и году',
  kind_org: 'по виду и юрлицу',
  kind_org_year: 'по виду, юрлицу и году',
}

export function DocsSetupPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const view = useDocsView('/docs/setup')
  const companyId = company?.id ?? ''

  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: !!companyId,
  })

  const starter = useMutation({
    mutationFn: () => docsService.starterKinds(companyId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      toast.success(r.added ? `Заведено видов: ${r.added}` : 'Всё уже заведено')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const kinds = kindsQ.data ?? []

  if (view === 'counters') {
    return (
      <div className="space-y-3 px-4 py-4">
        <div>
          <h1 className="text-base font-semibold">Нумераторы</h1>
          <p className="text-xs text-muted-foreground">
            Область нумерации задаётся видом документа. Счётчик транзакционный:
            отменённая регистрация возвращает номер, поэтому пропусков в журнале нет.
          </p>
        </div>
        <Card className="divide-y divide-border/60">
          {kinds.map((k) => (
            <div key={k.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div>
                <div className="text-sm font-medium">{k.name}</div>
                <div className="text-[11px] text-muted-foreground">
                  {k.number_template.replace('{prefix}', k.number_prefix || k.code)}
                  {' · '}{SCOPE_LABEL[k.number_scope] ?? k.number_scope}
                </div>
              </div>
              <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">
                {k.number_prefix || '—'}
              </span>
            </div>
          ))}
          {kinds.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              Видов документов пока нет
            </div>
          )}
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-3 px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">Виды документов</h1>
          <p className="text-xs text-muted-foreground">
            Вид задаёт поток, правило нумерации и то, каким типом ставится поручение
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => starter.mutate()}
          disabled={starter.isPending}>
          Завести обычный набор
        </Button>
      </div>

      <Card className="divide-y divide-border/60">
        {kinds.map((k) => (
          <div key={k.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-sm font-medium">{k.name}</div>
              <div className="text-[11px] text-muted-foreground">
                {DOC_FAMILY[k.family] ?? k.family}
                {' · номер '}
                {k.number_template.replace('{prefix}', k.number_prefix || k.code)}
                {' · '}{SCOPE_LABEL[k.number_scope] ?? k.number_scope}
              </div>
              {k.description && (
                <div className="pt-0.5 text-[11px] text-muted-foreground">{k.description}</div>
              )}
            </div>
            <span className="font-mono text-xs text-muted-foreground">{k.code}</span>
          </div>
        ))}
        {kinds.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            Видов пока нет. Обычный набор — входящее и исходящее письмо, приказ,
            служебная записка.
          </div>
        )}
      </Card>
    </div>
  )
}

export default DocsSetupPage
