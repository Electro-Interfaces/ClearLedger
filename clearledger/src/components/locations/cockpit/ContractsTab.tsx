/**
 * Договоры станции — адресные (привязаны к этой точке) и общекомпанейские.
 * Для energy-профиля сверху — платёжная дисциплина (энергоснабжение/аренда):
 * статус оплаты «оплачено по», основание (договор/разрешение) и проблемные
 * комментарии из реестра «Договоры и оплаты ЭЗС» (StationContractSettlement).
 * Источники: useLocationContracts (ось договор↔точка) + useLocationSettlements (L2).
 */
import { AlertTriangle, Building, FileSignature, KeyRound, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useLocationContracts, useLocationSettlements } from '@/hooks/useReferences'
import { useCompany } from '@/contexts/CompanyContext'
import type { ServiceLocation } from '@/types/location'
import { PAYMENT_META, ROLE_LABEL, paidThroughLabel, type SettlementRole } from '@/types/settlement'
import { Placeholder, ScrollTab } from './shared'

export function ContractsTab({ location }: { location: ServiceLocation }) {
  const { company } = useCompany()
  const isEnergy = company?.profileId === 'energy'

  const contractsQ = useLocationContracts(location.id)
  const contracts = contractsQ.data?.contracts ?? []
  const cpByRef = new Map(
    (contractsQ.data?.counterparties ?? []).map((c) => [c.externalRef, c]),
  )

  const settleQ = useLocationSettlements(isEnergy ? location.id : null)
  const settlements = settleQ.data ?? []

  const empty = contracts.length === 0 && settlements.length === 0
    && !contractsQ.isLoading && !settleQ.isLoading

  return (
    <ScrollTab>
      {/* ── Платёжная дисциплина (energy) ── */}
      {isEnergy && settlements.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Платёжная дисциплина
          </div>
          {(['energy', 'rent'] as SettlementRole[]).map((role) => {
            const s = settlements.find((x) => x.role === role)
            if (!s) return null
            const cpName = s.counterpartyId ? cpByRef.get(s.counterpartyId)?.name : null
            const Icon = role === 'energy' ? Zap : KeyRound
            const meta = PAYMENT_META[s.paymentStatus]
            return (
              <div key={role} className="space-y-1.5 rounded-md border border-border/50 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 font-medium">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground" /> {ROLE_LABEL[role]}
                  </div>
                  <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}>
                    {paidThroughLabel(s)}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {cpName || s.counterpartyId || '—'}
                  {s.basis && s.basis !== 'договор' && <span> · основание: {s.basis}</span>}
                </div>
                {s.comment && (
                  <div className="flex items-start gap-1.5 rounded bg-amber-500/10 p-1.5 text-[11px] text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>{s.comment}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ── Договоры станции ── */}
      {(contractsQ.isLoading || settleQ.isLoading) && (
        <p className="text-sm text-muted-foreground">Загрузка…</p>
      )}
      {empty && (
        <Placeholder
          icon={FileSignature}
          title="Нет связанных договоров"
          text="Договоры (адресные на эту станцию и общекомпанейские) и платёжная дисциплина появятся здесь после загрузки реестра/синхронизации."
        />
      )}
      {contracts.length > 0 && (
        <div className="space-y-2">
          {isEnergy && settlements.length > 0 && (
            <div className="pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Договоры
            </div>
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
        </div>
      )}
    </ScrollTab>
  )
}
