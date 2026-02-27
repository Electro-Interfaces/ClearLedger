/**
 * QuickAddCounterpartyDialog — быстрое добавление контрагента из верификации.
 *
 * Открывается из check-строки new_counterparty. Предзаполняет поля из metadata.
 * После создания → перезапускает верификацию.
 */

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCreateCounterparty } from '@/hooks/useReferences'
import { toast } from 'sonner'
import type { CounterpartyType } from '@/types'

interface QuickAddCounterpartyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  prefill: {
    name: string
    inn: string
    kpp: string
  }
  onCreated: () => void
}

export function QuickAddCounterpartyDialog({
  open,
  onOpenChange,
  prefill,
  onCreated,
}: QuickAddCounterpartyDialogProps) {
  const createCounterparty = useCreateCounterparty()
  const [name, setName] = useState(prefill.name)
  const [inn, setInn] = useState(prefill.inn)
  const [kpp, setKpp] = useState(prefill.kpp)
  const [type, setType] = useState<CounterpartyType>('ЮЛ')
  const [shortName, setShortName] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !inn.trim()) {
      toast.error('Название и ИНН обязательны')
      return
    }
    createCounterparty.mutate(
      {
        name: name.trim(),
        inn: inn.trim(),
        kpp: kpp.trim() || undefined,
        shortName: shortName.trim() || undefined,
        type,
        aliases: [],
      },
      {
        onSuccess: () => {
          toast.success(`Контрагент «${name.trim()}» добавлен`)
          onOpenChange(false)
          onCreated()
        },
        onError: () => toast.error('Ошибка при добавлении'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Добавить контрагента</DialogTitle>
          <DialogDescription>
            Контрагент будет добавлен в справочник и верификация перезапустится.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid gap-1.5">
            <Label htmlFor="cp-name">Название *</Label>
            <Input id="cp-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="cp-inn">ИНН *</Label>
            <Input id="cp-inn" value={inn} onChange={(e) => setInn(e.target.value)} maxLength={12} />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="cp-kpp">КПП</Label>
            <Input id="cp-kpp" value={kpp} onChange={(e) => setKpp(e.target.value)} maxLength={9} />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="cp-short">Краткое название</Label>
            <Input id="cp-short" value={shortName} onChange={(e) => setShortName(e.target.value)} />
          </div>

          <div className="grid gap-1.5">
            <Label>Тип</Label>
            <Select value={type} onValueChange={(v) => setType(v as CounterpartyType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ЮЛ">ЮЛ</SelectItem>
                <SelectItem value="ФЛ">ФЛ</SelectItem>
                <SelectItem value="ИП">ИП</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={createCounterparty.isPending}>
              Добавить
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
