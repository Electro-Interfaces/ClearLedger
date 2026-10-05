/**
 * Поиск «всё по локации»: по названию станции, коду, № БУ, адресу или номеру проекта —
 * какие договоры и контрагенты к ней относятся.
 *
 * Связь станции с договором приходит из трёх мест, и все три нужны: охват договора
 * (`contract_locations`), расчёт станции из реестра (`station_contract_settlements` —
 * договор и контрагент её строки) и проект («Проекты» → площадка, привязанная к договору).
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocations } from '@/hooks/useLocations'
import { useSettlementsDetail } from '@/hooks/useReferences'
import { getContractBindings } from '@/services/referenceService'
import type { ServiceLocation } from '@/types/location'

export interface StationHit {
  stations: ServiceLocation[]
  projects: string[]                 // подписи найденных проектов
  contractIds: Set<string>
  counterpartyIds: Set<string>       // из расчётов станций (договор ищется по contractIds)
}

export function useStationContracts(): (q: string) => StationHit | null {
  const { companyId } = useCompany()
  const locations = useLocations()
  const { data: settlements = [] } = useSettlementsDetail()
  const bindings = useQuery({ queryKey: ['contract-bindings', companyId], queryFn: () => getContractBindings(companyId), staleTime: 60_000 })

  const index = useMemo(() => {
    const byLoc = new Map<string, Set<string>>()   // станция → договоры
    for (const [cid, locs] of Object.entries(bindings.data?.locations ?? {}))
      for (const l of locs) byLoc.set(l, (byLoc.get(l) ?? new Set()).add(cid))
    const cpByLoc = new Map<string, Set<string>>()
    const buByLoc = new Map<string, string>()   // № БУ надёжнее всего приходит в строке реестра станции
    for (const s of settlements) {
      if (s.buNumber) buByLoc.set(s.locationId, s.buNumber)
      if (s.contractId) byLoc.set(s.locationId, (byLoc.get(s.locationId) ?? new Set()).add(s.contractId))
      if (s.counterpartyId) cpByLoc.set(s.locationId, (cpByLoc.get(s.locationId) ?? new Set()).add(s.counterpartyId))
    }
    const byProject = new Map<string, string[]>()   // проект → договоры
    for (const [cid, b] of Object.entries(bindings.data?.contracts ?? {}))
      for (const p of b.projects) byProject.set(p, [...(byProject.get(p) ?? []), cid])
    return { byLoc, cpByLoc, byProject, buByLoc }
  }, [bindings.data, settlements])

  return (raw: string) => {
    const q = raw.trim().toLocaleLowerCase('ru')
    if (q.length < 2) return null
    const stations = locations.filter((l) => {
      const bu = (l.metadata as Record<string, unknown> | undefined)?.buNumber ?? index.buByLoc.get(l.id)
      return `${l.name} ${l.code} ${l.address ?? ''} ${bu ?? ''}`.toLocaleLowerCase('ru').includes(q)
    })
    const projectRefs = Object.entries(bindings.data?.projects ?? {}).filter(([, label]) => label.toLocaleLowerCase('ru').includes(q))
    if (!stations.length && !projectRefs.length) return null
    const contractIds = new Set<string>()
    const counterpartyIds = new Set<string>()
    for (const l of stations) {
      index.byLoc.get(l.id)?.forEach((c) => contractIds.add(c))
      index.cpByLoc.get(l.id)?.forEach((c) => counterpartyIds.add(c))
    }
    for (const [ref] of projectRefs) index.byProject.get(ref)?.forEach((c) => contractIds.add(c))
    return { stations, projects: projectRefs.map(([, label]) => label), contractIds, counterpartyIds }
  }
}

/** Подпись под поиском: какие локации нашлись — чтобы было видно, почему показаны эти договоры. */
export function stationHitLabel(hit: StationHit): string {
  const names = [...hit.stations.slice(0, 3).map((s) => `${s.name} (${s.code})`), ...hit.projects.slice(0, 2)]
  const more = hit.stations.length + hit.projects.length - names.length
  return `${hit.stations.length ? `станции: ${hit.stations.length}` : ''}${hit.stations.length && hit.projects.length ? ', ' : ''}${hit.projects.length ? `проекты: ${hit.projects.length}` : ''} — ${names.join(', ')}${more > 0 ? ` и ещё ${more}` : ''}`
}
