/**
 * Выгрузка документа в корпоративную систему головной компании.
 *
 * Пакет кладётся в папку, откуда его забирает СЭД. Если папка недоступна, рядом
 * кнопка «Скачать пакет»: обмен не должен вставать из-за сети, человек донесёт
 * файл руками. Журнал выгрузок отвечает на вопрос сверки «отдавали ли мы это».
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Download, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'

const STATUS_RU: Record<string, string> = {
  placed: 'в папке',
  downloaded: 'скачан файлом',
  failed: 'не удалось',
}

export function DocExchangeBlock({ doc, companyId }: {
  doc: DocDetails
  companyId: string
}) {
  const qc = useQueryClient()
  const [targetId, setTargetId] = useState('')

  const targetsQ = useQuery({
    queryKey: ['doc-exchange-targets', companyId],
    queryFn: () => docsService.exchangeTargets(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const exportsQ = useQuery({
    queryKey: ['doc-exports', doc.id, companyId],
    queryFn: () => docsService.listExports(companyId, doc.id),
  })

  const send = useMutation({
    mutationFn: () => docsService.exportDoc(companyId, doc.id, targetId),
    onSuccess: (r) => {
      toast.success(`Пакет положен в папку: файлов ${r.files}`)
      qc.invalidateQueries({ queryKey: ['doc-exports', doc.id, companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const targets = (targetsQ.data ?? []).filter((t) => t.is_active && t.outbox_path)
  const rows = exportsQ.data ?? []

  if (!doc.reg_number) return null

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Building2 className="h-4 w-4" />В головную компанию
      </div>

      {targets.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Точки обмена не заведены. Папку корпоративной системы указывают в
          «Настройке» → «Обмен с СЭД». Пакет можно забрать и файлом.
        </p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Куда</Label>
            <select value={targetId} onChange={(e) => setTargetId(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              <option value="">выберите систему</option>
              {targets.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <Button size="sm" onClick={() => send.mutate()}
              disabled={!targetId || send.isPending}>
              <Upload className="mr-1.5 h-4 w-4" />Выгрузить
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline"
          onClick={() => window.open(
            `/api/docs/${doc.id}/export/download?company_id=${companyId}`, '_blank')}>
          <Download className="mr-1.5 h-4 w-4" />Скачать пакет
        </Button>
        <span className="text-[11px] text-muted-foreground">
          Документ, опись с реквизитами и лист согласования одним архивом
        </span>
      </div>

      {rows.length > 0 && (
        <div className="space-y-1 border-t border-border pt-2">
          <div className="text-xs font-medium text-muted-foreground">Что уже уходило</div>
          {rows.slice(0, 6).map((r) => (
            <div key={r.id} className="text-[12px]">
              <span className="text-muted-foreground">
                {(r.created_at ?? '').slice(0, 16).replace('T', ' ')}
              </span>
              {' · '}{r.target}
              {' · '}{STATUS_RU[r.status] ?? r.status}
              {r.files ? ` · файлов ${r.files}` : ''}
              {r.error && <span className="text-destructive"> · {r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export default DocExchangeBlock
