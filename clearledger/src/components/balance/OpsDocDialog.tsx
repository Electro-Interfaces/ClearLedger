/**
 * Документ контрагента: завести руками и сразу закрыть им ожидание.
 *
 * Пока приём почтой и ЭДО не подключены, это единственный вход первички — и он
 * остаётся нужным после: бумажный оригинал, привезённый курьером, ниоткуда сам
 * не появится.
 *
 * Форма открывается ИЗ СТРОКИ реестра, поэтому контрагент, договор, период и
 * ожидаемая сумма уже известны — человеку остаются номер, дата и фактическая
 * сумма. Просить его выбирать контрагента заново значит просить подтвердить то,
 * что система и так знает.
 */
import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Paperclip, Upload, X } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import {
  attachOpsDoc, createOpsDoc, uploadOpsDoc, type OpsCharge,
} from '@/services/opsService'

const DOC_TYPES = [
  { v: 'act', label: 'Акт' },
  { v: 'upd', label: 'УПД' },
  { v: 'invoice', label: 'Счёт' },
  { v: 'sf', label: 'Счёт-фактура' },
  { v: 'report', label: 'Расчёт / расшифровка' },
  { v: 'other', label: 'Иное' },
]

export function OpsDocDialog({ charge, period, children }: {
  charge: OpsCharge
  period: string
  children: React.ReactNode
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // Скан прикладывается тем же действием, что и заведение документа: человек,
  // держащий в руках акт, не должен делать два шага там, где смысл один.
  const [file, setFile] = useState<File | null>(null)
  const [f, setF] = useState({
    docType: 'act',
    number: '',
    docDate: '',
    // Ожидаемая сумма как отправная точка: чаще всего документ приходит именно
    // на неё, и переписывать цифру руками незачем. Расхождение посчитается само.
    amountGross: charge.expectedGross != null ? String(charge.expectedGross) : '',
    qty: charge.expectedQty != null ? String(charge.expectedQty) : '',
    note: '',
  })

  const save = useMutation({
    mutationFn: async () => {
      // Со сканом — одной операцией: файл, карточка и привязка. Без скана —
      // прежним путём, чтобы «вбить сумму с телефона» осталось быстрым.
      if (file) {
        const res = await uploadOpsDoc(companyId!, file, {
          doc_type: f.docType,
          number: f.number.trim() || undefined,
          doc_date: f.docDate || undefined,
          period,
          amount_gross: Number(f.amountGross),
          counterparty_id: charge.counterpartyId ?? undefined,
          contract_id: charge.contractId ?? undefined,
          charge_id: charge.id,
          note: f.note.trim() || undefined,
        })
        return res.attach ?? { variance: 0, varianceClass: 'none' as const,
                               periodClosed: false, correctionOffered: false }
      }
      const doc = await createOpsDoc(companyId!, {
        docType: f.docType,
        number: f.number.trim() || null,
        docDate: f.docDate || null,
        counterpartyId: charge.counterpartyId,
        contractId: charge.contractId,
        period,
        amountGross: Number(f.amountGross),
        qty: f.qty === '' ? null : Number(f.qty),
        channel: 'manual',
        note: f.note.trim() || null,
      })
      return attachOpsDoc(companyId!, charge.id, doc.id, {
        amountGross: Number(f.amountGross),
        qty: f.qty === '' ? undefined : Number(f.qty),
      })
    },
    onSuccess: (r) => {
      if (r.correctionOffered) {
        toast.warning(
          `Документ привязан. Расхождение ${Math.round(r.variance)} ₽ в закрытом периоде — ` +
          'проведите корректировкой в текущем месяце')
      } else if (r.varianceClass === 'material' || r.varianceClass === 'minor') {
        toast.warning(`Документ привязан, расхождение ${Math.round(r.variance)} ₽`)
      } else {
        toast.success('Документ привязан, ожидание закрыто')
      }
      for (const key of ['ops-closing', 'ops-periods', 'ops-charges',
                         'ops-counterparties', 'ops-docs']) {
        qc.invalidateQueries({ queryKey: [key, companyId] })
      }
      setOpen(false)
    },
    onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const amount = Number(f.amountGross)
  const expected = charge.expectedGross ?? 0
  const variance = Number.isFinite(amount) ? Math.round(amount - expected) : 0
  const canSave = f.amountGross !== '' && Number.isFinite(amount)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Документ контрагента</DialogTitle>
        </DialogHeader>

        <div className="space-y-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
          <div className="font-medium">
            {charge.locationName ?? 'Общая затрата компании'} · {charge.costItemLabel}
          </div>
          <div className="text-xs text-muted-foreground">
            {charge.counterpartyName ?? 'контрагент не сопоставлен'} · период {period.slice(0, 7)}
            {charge.expectedGross != null && ` · ожидали ${Math.round(charge.expectedGross)} ₽`}
          </div>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Вид документа</Label>
              <Select value={f.docType} onValueChange={(v) => setF((s) => ({ ...s, docType: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DOC_TYPES.map((d) => <SelectItem key={d.v} value={d.v}>{d.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Номер</Label>
              <Input value={f.number}
                onChange={(e) => setF((s) => ({ ...s, number: e.target.value }))} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Дата документа</Label>
              <Input type="date" value={f.docDate}
                onChange={(e) => setF((s) => ({ ...s, docDate: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <Label>Сумма, ₽ с НДС <span className="text-destructive">*</span></Label>
              <Input inputMode="decimal" value={f.amountGross}
                onChange={(e) => setF((s) => ({ ...s, amountGross: e.target.value }))} />
            </div>
          </div>

          {charge.expectedQty != null && (
            <div className="space-y-1.5">
              <Label>Объём, кВт·ч</Label>
              <Input inputMode="decimal" value={f.qty}
                onChange={(e) => setF((s) => ({ ...s, qty: e.target.value }))} />
            </div>
          )}

          {/* Расхождение показываем до сохранения: человек должен видеть, что
              сумма разошлась с ожиданием, ДО того как нажал кнопку. */}
          {canSave && variance !== 0 && (
            <p className={`text-sm ${Math.abs(variance) > expected * 0.02
              ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'}`}>
              Расхождение с ожиданием: {variance > 0 ? '+' : ''}{variance} ₽
              {Math.abs(variance) > expected * 0.02 && ' — существенное'}
            </p>
          )}

          <div className="space-y-1.5">
            <Label>Скан документа</Label>
            <input ref={inputRef} type="file" className="hidden"
              accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.doc,.docx"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); e.target.value = '' }} />
            {file ? (
              <div className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-sm">
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate">{file.name}</span>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                  {Math.round(file.size / 1024)} КБ
                </span>
                <button type="button" onClick={() => setFile(null)}
                  className="shrink-0 text-muted-foreground hover:text-foreground"
                  title="Убрать файл">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <Button type="button" variant="outline" className="w-full gap-2"
                onClick={() => inputRef.current?.click()}>
                <Upload className="h-4 w-4" />Приложить скан
              </Button>
            )}
            <p className="text-xs text-muted-foreground">
              необязательно — скан можно приложить позже на экране «Документы»
            </p>
          </div>

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
            Привязать к ожиданию
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
