import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export interface DocRegisterValues {
  regDate: string
  regNumber?: string
  manualReason?: string
}

function localToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

export function DocRegisterDialog({ pending, allowManual, onClose, onConfirm }: {
  pending: boolean
  allowManual: boolean
  onClose: () => void
  onConfirm: (values: DocRegisterValues) => void
}) {
  const [regDate, setRegDate] = useState(localToday())
  const [manual, setManual] = useState(false)
  const [regNumber, setRegNumber] = useState('')
  const [manualReason, setManualReason] = useState('')
  const manualReady = !manual || (regNumber.trim().length > 0 && manualReason.trim().length >= 3)

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Регистрация документа</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="doc-register-date">Дата регистрации</Label>
            <Input id="doc-register-date" type="date" value={regDate} max={localToday()}
              onChange={(event) => setRegDate(event.target.value)} />
          </div>

          {allowManual ? (
            <label className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
              <input type="checkbox" checked={manual}
                onChange={(event) => setManual(event.target.checked)} className="mt-0.5" />
              <span>
                <span className="block font-medium">Перенести номер из нашего прежнего журнала</span>
                <span className="block pt-0.5 text-xs text-muted-foreground">
                  В обычной регистрации номер выдаёт непрерывный счётчик автоматически.
                </span>
              </span>
            </label>
          ) : (
            <p className="rounded-md border border-border p-3 text-sm text-muted-foreground">
              Регистрационный номер выдаст непрерывный счётчик автоматически.
            </p>
          )}

          {manual && (
            <div className="space-y-3 rounded-md bg-muted/30 p-3">
              <div className="space-y-1.5">
                <Label htmlFor="doc-register-number">Наш прежний регистрационный номер</Label>
                <Input id="doc-register-number" value={regNumber} maxLength={60}
                  onChange={(event) => setRegNumber(event.target.value)} autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="doc-register-reason">Основание переноса</Label>
                <Textarea id="doc-register-reason" value={manualReason} rows={2} maxLength={500}
                  onChange={(event) => setManualReason(event.target.value)}
                  placeholder="Например: перенос бумажного журнала за 2025 год" />
              </div>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Номер корреспондента не переносится в наш журнал — для него в карточке есть поле «Их номер».
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>Отмена</Button>
          <Button onClick={() => onConfirm({
            regDate,
            regNumber: manual ? regNumber.trim() : undefined,
            manualReason: manual ? manualReason.trim() : undefined,
          })} disabled={!regDate || !manualReady || pending}>
            {pending ? 'Регистрируем…' : 'Зарегистрировать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
