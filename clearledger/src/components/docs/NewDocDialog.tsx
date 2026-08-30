/**
 * Заведение документа. Номера здесь не выдаём: регистрация — отдельное решение
 * человека, и черновик обязан отличаться от зарегистрированного документа.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import * as docsService from '@/services/docsService'
import type { DocKind } from '@/services/docsService'

export function NewDocDialog({ companyId, kinds, defaultFamily, initialTitle,
  summary, subjectRef, onClose, onCreated }: {
  companyId: string
  kinds: DocKind[]
  defaultFamily?: string
  /** Заготовка названия: документ, рождённый из записи, приходит с её текстом.
   *  Переписывать его человек вправе — это черновик, а не перенос. */
  initialTitle?: string
  summary?: string
  /** Откуда документ родился (`task:<uuid>`). Ссылка обратная: из карточки
   *  документа видно запись, из которой он вырос, — иначе связь односторонняя и
   *  через неделю никто не вспомнит, почему документ появился. */
  subjectRef?: string
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const { organizations, organizationId } = useCompany()
  // Вид подставляем по разделу, из которого пришли: в «Входящих» заводят входящее.
  const suited = defaultFamily ? kinds.filter((k) => k.family === defaultFamily) : kinds
  const [kindId, setKindId] = useState(suited[0]?.id ?? kinds[0]?.id ?? '')
  const [title, setTitle] = useState(initialTitle ?? '')
  const [counterparty, setCounterparty] = useState('')
  const [externalNumber, setExternalNumber] = useState('')
  const [externalDate, setExternalDate] = useState('')
  const [docOrganizationId, setDocOrganizationId] = useState(
    organizationId ?? (organizations.length === 1 ? organizations[0].id : ''),
  )

  const kind = kinds.find((k) => k.id === kindId)
  const incoming = kind?.direction === 'in'

  const create = useMutation({
    mutationFn: () => docsService.createDoc(companyId, {
      kind_id: kindId,
      title: title.trim(),
      summary: summary || undefined,
      subject_ref: subjectRef || undefined,
      organization_id: docOrganizationId || null,
      counterparty_name: counterparty.trim(),
      external_number: externalNumber.trim() || null,
      external_date: externalDate || null,
    }),
    onSuccess: (d) => onCreated(d.id),
    onError: (e) => toast.error(`Документ не заведён: ${(e as Error).message}`),
  })

  /** Чего ждёт форма, или `null` — можно заводить. Порядок сверху вниз, как
   *  в самой форме: человек ищет пропуск там, где на него укажут. */
  const чегоНеХватает = !kindId ? 'Выберите вид документа'
    : (organizations.length > 0 && !docOrganizationId) ? 'Выберите наше юрлицо — от него зависит журнал и номер'
      : !title.trim() ? 'Впишите заголовок'
        : null

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Новый документ</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="new-doc-kind" className="text-xs">Вид документа</Label>
            <select id="new-doc-kind" value={kindId} onChange={(e) => setKindId(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              {(suited.length ? suited : kinds).map((k) => (
                <option key={k.id} value={k.id}>{k.name}</option>
              ))}
            </select>
            {kind && (
              <p className="text-xs text-muted-foreground">
                Номер получит вид {kind.number_prefix || kind.code}-… при регистрации
              </p>
            )}
          </div>

          {organizations.length > 0 && (
            <div className="space-y-1.5">
              <Label htmlFor="new-doc-organization" className="text-xs">Наше юрлицо</Label>
              <select id="new-doc-organization" value={docOrganizationId}
                onChange={(event) => setDocOrganizationId(event.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                <option value="">выберите юрлицо</option>
                {organizations.map((organization) => (
                  <option key={organization.id} value={organization.id}>
                    {organization.name}{organization.inn ? ` · ИНН ${organization.inn}` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="new-doc-title" className="text-xs">Заголовок</Label>
            <Input id="new-doc-title" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="О чём документ" className="h-9" />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="new-doc-counterparty" className="text-xs">
              {incoming ? 'От кого' : 'Кому'}
            </Label>
            <Input id="new-doc-counterparty" value={counterparty} onChange={(e) => setCounterparty(e.target.value)}
              placeholder="Наименование организации" className="h-9" />
          </div>

          {incoming && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="new-doc-external-number" className="text-xs">Их исходящий номер</Label>
                <Input id="new-doc-external-number" value={externalNumber} onChange={(e) => setExternalNumber(e.target.value)}
                  placeholder="исх-2210" className="h-9" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="new-doc-external-date" className="text-xs">Дата их документа</Label>
                <Input id="new-doc-external-date" type="date" value={externalDate}
                  onChange={(e) => setExternalDate(e.target.value)} className="h-9" />
              </div>
            </div>
          )}
        </div>
        <DialogFooter className="items-center gap-3 sm:justify-between">
          {/* Чего не хватает — словами. Молча погасшая кнопка заставляет
              человека гадать, а условие программе известно заранее. */}
          <p className="text-xs text-muted-foreground" role="status">
            {чегоНеХватает ?? ''}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Отмена</Button>
            <Button onClick={() => create.mutate()}
              title={чегоНеХватает ?? undefined}
              disabled={!!чегоНеХватает || create.isPending}>
              Завести
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default NewDocDialog
