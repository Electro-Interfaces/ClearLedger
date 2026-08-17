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

export function NewDocDialog({ companyId, kinds, defaultFamily, onClose, onCreated }: {
  companyId: string
  kinds: DocKind[]
  defaultFamily?: string
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const { organizations, organizationId } = useCompany()
  // Вид подставляем по разделу, из которого пришли: в «Входящих» заводят входящее.
  const suited = defaultFamily ? kinds.filter((k) => k.family === defaultFamily) : kinds
  const [kindId, setKindId] = useState(suited[0]?.id ?? kinds[0]?.id ?? '')
  const [title, setTitle] = useState('')
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
      organization_id: docOrganizationId || null,
      counterparty_name: counterparty.trim(),
      external_number: externalNumber.trim() || null,
      external_date: externalDate || null,
    }),
    onSuccess: (d) => onCreated(d.id),
    onError: (e) => toast.error(`Документ не заведён: ${(e as Error).message}`),
  })

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Новый документ</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs">Вид документа</Label>
            <select value={kindId} onChange={(e) => setKindId(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              {(suited.length ? suited : kinds).map((k) => (
                <option key={k.id} value={k.id}>{k.name}</option>
              ))}
            </select>
            {kind && (
              <p className="text-[11px] text-muted-foreground">
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
            <Label className="text-xs">Заголовок</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="О чём документ" className="h-9" />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">
              {incoming ? 'От кого' : 'Кому'}
            </Label>
            <Input value={counterparty} onChange={(e) => setCounterparty(e.target.value)}
              placeholder="Наименование организации" className="h-9" />
          </div>

          {incoming && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Их исходящий номер</Label>
                <Input value={externalNumber} onChange={(e) => setExternalNumber(e.target.value)}
                  placeholder="исх-2210" className="h-9" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Дата их документа</Label>
                <Input type="date" value={externalDate}
                  onChange={(e) => setExternalDate(e.target.value)} className="h-9" />
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={() => create.mutate()}
            disabled={!kindId || !title.trim() ||
              (organizations.length > 0 && !docOrganizationId) || create.isPending}>
            Завести
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default NewDocDialog
