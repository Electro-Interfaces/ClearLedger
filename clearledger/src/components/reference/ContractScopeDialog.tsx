/**
 * Управление охватом договора по торговым точкам (ось договор↔точки, Фаза 2).
 * Режимы: «Вся компания» / «Выбранные точки» (мультиселект) / «Не распределён».
 */
import { useState, useEffect, type ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { ContractStationsField, type ContractStationsValue } from './ContractStationsField'
import {
  useContractLocations, useSetContractScope, useNomenclature,
} from '@/hooks/useReferences'
import { useChannels } from '@/hooks/useChannels'
import { ContractDimensionEditor } from './ContractDimensionEditor'
import type { Contract, ContractScopeType } from '@/types'

export function ContractScopeDialog({
  contract,
  children,
  onSaved,
}: {
  contract: Contract
  children: ReactNode
  onSaved?: () => void
}) {
  const [open, setOpen] = useState(false)
  // Без значения по умолчанию в зависимостях: `= []` создавал новый массив на
  // каждой отрисовке, и эффект ниже зацикливался.
  const { data: current } = useContractLocations(open ? contract.id : null)
  const saveMut = useSetContractScope()
  const { data: nomenclature = [] } = useNomenclature()
  const { data: channels = [] } = useChannels()

  const [scope, setScope] = useState<ContractStationsValue>({ scopeType: contract.scopeType ?? 'unassigned', locationIds: [] })

  useEffect(() => {
    if (open) setScope({ scopeType: contract.scopeType ?? 'unassigned', locationIds: (current ?? []).map((l) => l.id) })
  }, [open, contract.scopeType, current])

  async function handleSave() {
    if (scope.scopeType === 'locations' && scope.locationIds.length === 0) {
      toast.error('Выберите хотя бы одну станцию или смените охват')
      return
    }
    try {
      await saveMut.mutateAsync({
        contractId: contract.id,
        scopeType: scope.scopeType,
        locationIds: scope.scopeType === 'locations' ? scope.locationIds : [],
      })
      toast.success('Охват договора сохранён')
      setOpen(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить охват')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Охват договора {contract.number}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <ContractStationsField value={scope} onChange={setScope} />

          {/* Грани по другим разрезам (Фаза 3) — независимо от охвата точек */}
          <div className="space-y-4 border-t border-border/50 pt-3">
            <div className="text-xs font-medium text-muted-foreground">
              Ограничения по разрезам (необязательно)
            </div>
            <ContractDimensionEditor
              contractId={contract.id} dimType="nomenclature" title="Номенклатура"
              hint="Пусто = договор охватывает всю номенклатуру"
              items={nomenclature.map((n) => ({ id: n.id, label: n.name, sub: n.code }))}
            />
            <ContractDimensionEditor
              contractId={contract.id} dimType="channel" title="Каналы"
              hint="Пусто = все каналы"
              items={channels.map((c) => ({ id: c.id, label: c.name }))}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={saveMut.isPending}>
            Отмена
          </Button>
          <Button onClick={handleSave} disabled={saveMut.isPending}>
            {saveMut.isPending && <Loader2 className="size-4 mr-2 animate-spin" />}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Бейдж охвата для строки договора: число станций вместо «Выбранные точки». */
export function ContractScopeBadgeLabel(scopeType?: ContractScopeType, count?: number | null): string {
  switch (scopeType) {
    case 'company': return 'Вся компания'
    case 'locations':
      if (count == null) return 'Выбранные станции'
      if (count === 0) return 'Станции не выбраны'
      return `${count} ${count % 10 === 1 && count % 100 !== 11 ? 'станция' : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100) ? 'станции' : 'станций'}`
    default: return 'Не распределён'
  }
}
