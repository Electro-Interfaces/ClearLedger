/**
 * Договоры станции — адресные (привязаны к этой точке) и общекомпанейские.
 * Источник: useLocationContracts (ось договор↔точка). Перенос из монолита.
 */
import { Building, FileSignature } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useLocationContracts } from '@/hooks/useReferences'
import type { ServiceLocation } from '@/types/location'
import { Placeholder, ScrollTab } from './shared'

export function ContractsTab({ location }: { location: ServiceLocation }) {
  const contractsQ = useLocationContracts(location.id)
  const contracts = contractsQ.data?.contracts ?? []

  return (
    <ScrollTab>
      {contractsQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
      {contracts.length === 0 && !contractsQ.isLoading && (
        <Placeholder
          icon={FileSignature}
          title="Нет связанных договоров"
          text="Договоры (адресные на эту станцию и общекомпанейские) появятся здесь после загрузки из 1С и привязки."
        />
      )}
      {contracts.map((c) => (
        <div key={c.id} className="flex items-start justify-between gap-3 rounded-md border border-border/50 p-3 text-sm">
          <div className="min-w-0">
            <div className="font-medium">{c.number}</div>
            <div className="text-xs text-muted-foreground">
              {c.counterpartyName || c.counterpartyId}{c.kind && <span> · {c.kind}</span>}
            </div>
          </div>
          {c.companyWide
            ? <Badge variant="secondary" className="shrink-0 gap-1 text-[10px]"><Building className="h-2.5 w-2.5" /> вся компания</Badge>
            : <Badge variant="outline" className="shrink-0 text-[10px]">адресный</Badge>}
        </div>
      ))}
    </ScrollTab>
  )
}
