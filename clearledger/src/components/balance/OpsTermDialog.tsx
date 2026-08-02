/**
 * Условие начисления по договору — форма и список версий.
 *
 * Условие это договор, прочитанный учётом: «аренда, 5000 ₽ в месяц, документ до
 * 10-го числа». Из него разворачиваются ожидания всех месяцев, поэтому пока
 * условия нет, договор для учёта немой — он есть, но система о нём молчит.
 *
 * ВЕРСИИ, А НЕ ПРАВКА НА МЕСТЕ. Ставка выросла с июля — заводится новая версия,
 * старая закрывается днём раньше. Правка на месте переписала бы суммы уже
 * закрытых месяцев, и отчёт, отданный бухгалтерии, поехал бы молча.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import {
  createOpsTerm, deleteOpsTerm, getOpsTerms, updateOpsTerm, type OpsTerm,
} from '@/services/opsService'

const PERIODICITY: Array<{ v: string; label: string; hint: string }> = [
  { v: 'monthly', label: 'Ежемесячно', hint: 'документ ждём каждый месяц' },
  { v: 'quarterly', label: 'Ежеквартально', hint: 'одно ожидание в квартал, а не три' },
  { v: 'annual', label: 'Раз в год', hint: 'в месяц начала действия условия' },
  { v: 'one_time', label: 'Разово', hint: 'только в месяц начала' },
]

const BASIS: Array<{ v: string; label: string; hint: string }> = [
  { v: '', label: 'По умолчанию для статьи', hint: 'как настроено в справочнике статей' },
  { v: 'contract', label: 'Сумма по договору', hint: 'постоянная величина из условия' },
  { v: 'prev_period', label: 'По прошлому месяцу', hint: 'сумма предыдущего периода' },
  { v: 'average', label: 'По среднему за 3 месяца', hint: 'среднее закрытых периодов' },
]

const isMetered = (t: { variableKind?: string | null }) => t.variableKind === 'metered_kwh'

type FormState = {
  costItem: string
  scopeType: 'location' | 'company'
  periodicity: string
  amountGross: string
  vatPct: string
  variableKind: string
  tariffRub: string
  docDueDay: string
  estimateBasis: string
  counterpartyEmail: string
  validFrom: string
  validTo: string
  note: string
}

const empty = (): FormState => ({
  costItem: '', scopeType: 'location', periodicity: 'monthly',
  amountGross: '', vatPct: '', variableKind: '', tariffRub: '',
  docDueDay: '10', estimateBasis: '', counterpartyEmail: '',
  validFrom: '', validTo: '', note: '',
})

const fromTerm = (t: OpsTerm): FormState => ({
  costItem: t.costItem, scopeType: t.scopeType, periodicity: t.periodicity,
  amountGross: t.amountGross != null ? String(t.amountGross) : '',
  vatPct: t.vatPct != null ? String(t.vatPct) : '',
  variableKind: t.variableKind ?? '',
  tariffRub: t.tariffRub != null ? String(t.tariffRub) : '',
  docDueDay: t.docDueDay != null ? String(t.docDueDay) : '',
  estimateBasis: t.estimateBasis ?? '', counterpartyEmail: t.counterpartyEmail ?? '',
  validFrom: t.validFrom, validTo: t.validTo ?? '', note: t.note ?? '',
})

/** Список условий договора с кнопками правки — встраивается в карточку договора. */
export function OpsTermsBlock({ contractId }: { contractId: string }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['ops-terms', companyId, contractId],
    queryFn: () => getOpsTerms(companyId!, contractId),
    enabled: !!companyId && !!contractId,
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteOpsTerm(companyId!, id),
    onSuccess: (r) => {
      toast.success(r.removedCharges
        ? `Условие удалено, снято ${r.removedCharges} незакрытых ожиданий`
        : 'Условие удалено')
      qc.invalidateQueries({ queryKey: ['ops-terms', companyId] })
      qc.invalidateQueries({ queryKey: ['ops-closing', companyId] })
    },
    onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  if (q.isLoading) {
    return <div className="flex justify-center py-4">
      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
    </div>
  }

  const terms = q.data?.terms ?? []
  const items = q.data?.costItems ?? []
  const label = (code: string) => items.find((i) => i.code === code)?.label ?? code

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">Условия начисления</span>
        <span className="text-xs text-muted-foreground">
          из них разворачиваются ожидания месяцев
        </span>
        <div className="ml-auto">
          <OpsTermDialog contractId={contractId} costItems={items}>
            <Button size="sm" variant="outline" className="h-7 gap-1 text-xs">
              <Plus className="h-3.5 w-3.5" />Добавить
            </Button>
          </OpsTermDialog>
        </div>
      </div>

      {terms.length === 0 ? (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
          Условий нет — по этому договору система ничего не ждёт и о недостающих
          документах молчит. Добавьте условие: статья, сумма и срок предоставления.
        </p>
      ) : (
        <div className="space-y-1">
          {terms.map((t) => (
            <div key={t.id}
              className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm ${
                t.current ? 'border-border' : 'border-border/50 opacity-60'}`}>
              <span className="font-medium">{label(t.costItem)}</span>
              <span className="text-muted-foreground">
                {PERIODICITY.find((p) => p.v === t.periodicity)?.label ?? t.periodicity}
              </span>
              <span className="tabular-nums">
                {isMetered(t) ? `по счётчику${t.tariffRub ? `, ${t.tariffRub} ₽/кВт·ч` : ''}`
                  : t.amountGross != null ? `${t.amountGross} ₽`
                  : <span className="text-amber-600 dark:text-amber-400">сумма не задана</span>}
              </span>
              {t.docDueDay && (
                <span className="text-xs text-muted-foreground">документ до {t.docDueDay}-го</span>
              )}
              <span className="text-xs text-muted-foreground">
                с {t.validFrom}{t.validTo ? ` по ${t.validTo}` : ''}
                {!t.current && ' · не действует'}
              </span>
              <div className="ml-auto flex items-center gap-1">
                <OpsTermDialog contractId={contractId} costItems={items} edit={t}>
                  <Button size="sm" variant="ghost" className="h-7 text-xs">Изменить</Button>
                </OpsTermDialog>
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0"
                  title="Удалить условие" disabled={remove.isPending}
                  onClick={() => remove.mutate(t.id)}>
                  <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function OpsTermDialog({ contractId, costItems, edit, children }: {
  contractId: string
  costItems: Array<{ code: string; label: string; measure: string | null }>
  edit?: OpsTerm
  children: React.ReactNode
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState<FormState>(edit ? fromTerm(edit) : empty())
  // Новая версия вместо правки: по умолчанию включена там, где условие уже
  // отработало хотя бы один период — тогда правка на месте меняет прошлое.
  const [asVersion, setAsVersion] = useState(false)

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        contractId,
        costItem: f.costItem,
        scopeType: f.scopeType,
        periodicity: f.periodicity,
        amountGross: f.amountGross === '' ? null : Number(f.amountGross),
        vatPct: f.vatPct === '' ? null : Number(f.vatPct),
        variableKind: f.variableKind || null,
        tariffRub: f.tariffRub === '' ? null : Number(f.tariffRub),
        docDueDay: f.docDueDay === '' ? null : Number(f.docDueDay),
        estimateBasis: f.estimateBasis || null,
        counterpartyEmail: f.counterpartyEmail.trim() || null,
        note: f.note.trim() || null,
      }
      if (f.validFrom) payload.validFrom = f.validFrom
      if (f.validTo) payload.validTo = f.validTo
      return edit
        ? updateOpsTerm(companyId!, edit.id, payload, asVersion)
        : createOpsTerm(companyId!, payload)
    },
    onSuccess: () => {
      toast.success(edit ? (asVersion ? 'Новая версия условия заведена' : 'Условие изменено')
        : 'Условие добавлено — ожидания появятся при открытии реестра')
      qc.invalidateQueries({ queryKey: ['ops-terms', companyId] })
      qc.invalidateQueries({ queryKey: ['ops-closing', companyId] })
      qc.invalidateQueries({ queryKey: ['ops-periods', companyId] })
      setOpen(false)
    },
    onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const metered = f.variableKind === 'metered_kwh'
  const canSave = f.costItem !== '' && (metered || f.amountGross !== '' || f.estimateBasis !== '')

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{edit ? 'Условие начисления' : 'Новое условие начисления'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Статья затрат <span className="text-destructive">*</span></Label>
            <Select value={f.costItem} onValueChange={(v) => setF((s) => ({ ...s, costItem: v }))}>
              <SelectTrigger><SelectValue placeholder="Выберите статью" /></SelectTrigger>
              <SelectContent>
                {costItems.map((i) => <SelectItem key={i.code} value={i.code}>{i.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Периодичность</Label>
              <Select value={f.periodicity}
                onValueChange={(v) => setF((s) => ({ ...s, periodicity: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PERIODICITY.map((p) => (
                    <SelectItem key={p.v} value={p.v} title={p.hint}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Охват</Label>
              <Select value={f.scopeType}
                onValueChange={(v) => setF((s) => ({ ...s, scopeType: v as 'location' | 'company' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="location" title="по всем объектам договора">
                    По объектам договора
                  </SelectItem>
                  <SelectItem value="company" title="затрата не привязана к объекту">
                    Общая затрата компании
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Чем считаем</Label>
            <Select value={f.variableKind || 'fixed'}
              onValueChange={(v) => setF((s) => ({
                ...s, variableKind: v === 'fixed' ? '' : v,
                amountGross: v === 'fixed' ? s.amountGross : '',
              }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">Постоянная сумма</SelectItem>
                <SelectItem value="metered_kwh">По счётчику — объём × тариф</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {metered ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Тариф, ₽/кВт·ч</Label>
                <Input inputMode="decimal" value={f.tariffRub}
                  onChange={(e) => setF((s) => ({ ...s, tariffRub: e.target.value }))}
                  placeholder="пусто — берём из данных станции" />
              </div>
              <div className="space-y-1.5">
                <Label>Ставка НДС, %</Label>
                <Input inputMode="decimal" value={f.vatPct}
                  onChange={(e) => setF((s) => ({ ...s, vatPct: e.target.value }))} />
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Сумма в период, ₽ с НДС</Label>
                <Input inputMode="decimal" value={f.amountGross}
                  onChange={(e) => setF((s) => ({ ...s, amountGross: e.target.value }))} />
              </div>
              <div className="space-y-1.5">
                <Label>Ставка НДС, %</Label>
                <Input inputMode="decimal" value={f.vatPct}
                  onChange={(e) => setF((s) => ({ ...s, vatPct: e.target.value }))}
                  placeholder="20" />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Документ до какого числа</Label>
              <Input inputMode="numeric" value={f.docDueDay}
                onChange={(e) => setF((s) => ({ ...s, docDueDay: e.target.value }))}
                placeholder="10" />
              <p className="text-xs text-muted-foreground">
                число СЛЕДУЮЩЕГО месяца — по нему считается просрочка
              </p>
            </div>
            <div className="space-y-1.5">
              <Label>Чем закрывать без документа</Label>
              <Select value={f.estimateBasis || 'default'}
                onValueChange={(v) => setF((s) => ({ ...s, estimateBasis: v === 'default' ? '' : v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {BASIS.map((b) => (
                    <SelectItem key={b.v || 'default'} value={b.v || 'default'} title={b.hint}>
                      {b.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Почта для документов и напоминаний</Label>
            <Input type="email" value={f.counterpartyEmail}
              onChange={(e) => setF((s) => ({ ...s, counterpartyEmail: e.target.value }))}
              placeholder="если отличается от адреса в карточке контрагента" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Действует с</Label>
              <Input type="date" value={f.validFrom}
                onChange={(e) => setF((s) => ({ ...s, validFrom: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <Label>по</Label>
              <Input type="date" value={f.validTo}
                onChange={(e) => setF((s) => ({ ...s, validTo: e.target.value }))} />
            </div>
          </div>

          {edit && (
            <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-sm">
              <input type="checkbox" checked={asVersion} className="mt-0.5 h-4 w-4"
                onChange={(e) => setAsVersion(e.target.checked)} />
              <span>
                Завести новой версией
                <span className="block text-xs text-muted-foreground">
                  правильный способ поднять ставку: старая версия закроется датой,
                  а суммы уже закрытых месяцев останутся как были
                </span>
              </span>
            </label>
          )}

          <div className="space-y-1.5">
            <Label>Примечание</Label>
            <Input value={f.note}
              onChange={(e) => setF((s) => ({ ...s, note: e.target.value }))} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
