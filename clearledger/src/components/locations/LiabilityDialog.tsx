/**
 * Условия ответственности по договору: срок устранения, санкция, гарантия.
 *
 * Претензия стоит ровно столько, сколько стоит ссылка в ней. «Станция не
 * работает 19 дней» — жалоба; «нарушен п. 7.3 договора № ПС-2024/231, срок
 * устранения 30 календарных дней, пеня 0,1 % за день просрочки, на 19.09.2026
 * это 47 500 ₽» — требование. Поэтому здесь заполняются не просто числа, а
 * числа с пунктом договора, из которого они взяты.
 *
 * Разбор из текста — помощник, а не источник истины: формулировки в договорах
 * разные, и «30 дней» бывает сроком поставки, а не устранения. Поэтому разбор
 * только ПРЕДЛАГАЕТ, показывая цитату рядом с каждым полем, а сохранение —
 * всегда действие человека.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { FileSearch, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  parseContractLiability, putContractLiability,
  type ContractLiability, type ObligationContract,
} from '@/services/opsService'

const ДЕЙСТВИЕ_ИМЯ: Record<string, string> = {
  repeat_claim: 'повторная претензия',
  pretrial: 'досудебная претензия с требованием неустойки',
  replace: 'требование замены станции',
  dismantle: 'требование демонтажа и возврата стоимости',
  court: 'исковое заявление',
}

export function LiabilityDialog({ contract, open, onClose }: {
  contract: ObligationContract
  open: boolean
  onClose: () => void
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const начальные = contract.liability ?? {}
  const [ф, setФ] = useState<ContractLiability>(начальные)
  const [текст, setТекст] = useState('')
  const [цитаты, setЦитаты] = useState<{ field: string; code: string; text: string }[]>(
    начальные.clauses ?? [])

  const поле = (k: keyof ContractLiability, v: unknown) =>
    setФ((было) => ({ ...было, [k]: v === '' ? null : v }))

  const разбор = useMutation({
    mutationFn: (данные: { file?: File; text?: string }) =>
      parseContractLiability(companyId, contract.id, данные),
    onSuccess: (r) => {
      if (!Object.keys(r.found).length) {
        toast.error(r.reason || 'В тексте не нашлось условий — заполните руками')
        return
      }
      setФ((было) => ({ ...было, ...r.found }))
      setЦитаты(r.found.clauses ?? [])
      toast.success('Разобрал — проверьте найденное и сохраните')
      if (r.reason) toast.warning(r.reason)
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось разобрать файл'),
  })

  const сохранить = useMutation({
    mutationFn: () => putContractLiability(companyId, contract.id, { ...ф, clauses: цитаты }),
    onSuccess: () => {
      toast.success('Условия сохранены')
      void qc.invalidateQueries({ queryKey: ['station-obligations'] })
      onClose()
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось сохранить'),
  })

  const цитатаДля = (k: string) => цитаты.find((c) => c.field === k)

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !сохранить.isPending) onClose() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Ответственность по договору {contract.number}</DialogTitle>
          <DialogDescription>
            {contract.counterparty ?? 'контрагент не указан'} · условия действуют на все
            станции договора ({contract.locationsCount || 1}). Из них берутся срок и
            сумма требования в претензии.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* ── помощник: разбор из текста договора ── */}
          <div className="space-y-2 rounded-md border border-border/60 p-3">
            <div className="flex items-center gap-1.5 text-xs font-medium">
              <FileSearch className="size-3.5" />Взять из текста договора
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Input type="file" accept=".pdf,.docx,.txt" className="h-8 w-64 text-xs"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) разбор.mutate({ file: f })
                }} />
              {разбор.isPending && <Loader2 className="size-4 animate-spin" />}
            </div>
            <Textarea rows={3} value={текст} onChange={(e) => setТекст(e.target.value)}
              placeholder="…или вставьте сюда раздел «Ответственность сторон» и нажмите «Разобрать»"
              className="text-xs" />
            <Button size="sm" variant="outline" className="h-7 text-xs"
              disabled={текст.trim().length < 40 || разбор.isPending}
              onClick={() => разбор.mutate({ text: текст })}>
              Разобрать текст
            </Button>
            <p className="text-xs text-muted-foreground">
              Сканы без текстового слоя не читаются — распознавания в системе нет.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="fix">Срок устранения, дней</Label>
              <Input id="fix" type="number" value={ф.fixDays ?? ''}
                onChange={(e) => поле('fixDays', e.target.value ? Number(e.target.value) : null)} />
              {цитатаДля('fixDays') && (
                <p className="text-[11px] text-muted-foreground">
                  п. {цитатаДля('fixDays')?.code || '—'}: {цитатаДля('fixDays')?.text}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cal">Дни считаются</Label>
              <Select value={ф.calendar ?? 'calendar'}
                onValueChange={(v) => поле('calendar', v)}>
                <SelectTrigger id="cal"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="calendar">календарные</SelectItem>
                  <SelectItem value="business">рабочие</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="resp">Срок реакции, часов</Label>
              <Input id="resp" type="number" value={ф.responseHours ?? ''}
                onChange={(e) => поле('responseHours', e.target.value ? Number(e.target.value) : null)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="warr">Гарантия, месяцев</Label>
              <Input id="warr" type="number" value={ф.warrantyMonths ?? ''}
                onChange={(e) => поле('warrantyMonths', e.target.value ? Number(e.target.value) : null)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pk">Санкция за просрочку</Label>
              <Select value={ф.penaltyKind ?? 'none'} onValueChange={(v) => поле('penaltyKind', v)}>
                <SelectTrigger id="pk"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">не предусмотрена</SelectItem>
                  <SelectItem value="per_day_pct">% от стоимости за день</SelectItem>
                  <SelectItem value="per_day_fixed">рублей за день</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pv">Размер санкции</Label>
              <Input id="pv" type="number" step="0.01" value={ф.penaltyValue ?? ''}
                onChange={(e) => поле('penaltyValue', e.target.value ? Number(e.target.value) : null)} />
              {цитатаДля('penaltyValue') && (
                <p className="text-[11px] text-muted-foreground">
                  п. {цитатаДля('penaltyValue')?.code || '—'}: {цитатаДля('penaltyValue')?.text}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cap">Предел неустойки, % от стоимости</Label>
              <Input id="cap" type="number" step="0.01" value={ф.penaltyCap ?? ''}
                onChange={(e) => поле('penaltyCap', e.target.value ? Number(e.target.value) : null)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="wu">Гарантия действует до</Label>
              <Input id="wu" type="date" value={ф.warrantyUntil ?? ''}
                onChange={(e) => поле('warrantyUntil', e.target.value || null)} />
            </div>
          </div>

          {/* Лестница эскалации: наш порядок работы, а не условие договора —
              поэтому показывается отдельно и по умолчанию 30/60/90. */}
          <div className="rounded-md border border-border/60 p-3 text-xs">
            <div className="mb-1 font-medium">Порядок эскалации</div>
            {(ф.escalation ?? [
              { afterDays: 30, action: 'repeat_claim' },
              { afterDays: 60, action: 'pretrial' },
              { afterDays: 90, action: 'replace' },
            ]).map((s, i) => (
              <div key={i} className="text-muted-foreground">
                через {s.afterDays} дн после претензии — {ДЕЙСТВИЕ_ИМЯ[s.action] ?? s.action}
              </div>
            ))}
            <p className="mt-1 text-muted-foreground">
              Отсчёт идёт от даты отправки предыдущей претензии.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={сохранить.isPending}>Отмена</Button>
          <Button onClick={() => сохранить.mutate()} disabled={сохранить.isPending}>
            {сохранить.isPending && <Loader2 className="mr-1.5 size-4 animate-spin" />}
            Сохранить условия
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
