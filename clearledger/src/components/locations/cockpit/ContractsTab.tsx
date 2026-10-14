/**
 * Договоры станции — адресные (привязаны к этой точке) и общекомпанейские.
 * Для energy-профиля сверху — платёжная дисциплина (энергоснабжение/аренда):
 * статус оплаты «оплачено по», основание (договор/разрешение) и проблемные
 * комментарии из реестра «Договоры и оплаты ЭЗС» (StationContractSettlement).
 * Источники: useLocationContracts (ось договор↔точка) + useLocationSettlements (L2).
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, Building, FileSignature, KeyRound, Link2, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { unlinkContractLocation } from '@/services/referenceService'
import { contractStatus } from '@/components/reference/ContractStationsField'
import { LinkContractDialog } from './LinkContractDialog'
import { useLocationContracts, useLocationSettlements } from '@/hooks/useReferences'
import { useCompany } from '@/contexts/CompanyContext'
import type { ServiceLocation } from '@/types/location'
import { PAYMENT_META, ROLE_LABEL, paidThroughLabel, type SettlementRole } from '@/types/settlement'
import { OpsTermsBlock } from '@/components/balance/OpsTermDialog'
import { Placeholder, ScrollTab } from './shared'

/** Вид договора 1С кодом («СПоставщиком») → по-русски. */
const KIND_RU: Record<string, string> = { СПоставщиком: 'с поставщиком', СПокупателем: 'с покупателем', Прочее: 'прочее' }

export function ContractsTab({ location }: { location: ServiceLocation }) {
  const { company } = useCompany()
  const isEnergy = company?.profileId === 'energy'

  const contractsQ = useLocationContracts(location.id)
  const contracts = contractsQ.data?.contracts ?? []
  // Станция видит прежде всего СВОИ договоры (адресные). Общие договоры компании
  // действуют на все станции сразу — их показываем свёрнуто, а клиентские договоры
  // сети (корпоративная зарядка: мы продаём, а не платим) — одной строкой: на
  // проверке 05.10 они составляли 22 из 34 «договоров станции» и прятали её 5 своих.
  const own = contracts.filter((c) => !c.companyWide)
  const common = contracts.filter((c) => c.companyWide && c.kind !== 'СПокупателем')
  const clients = contracts.filter((c) => c.companyWide && c.kind === 'СПокупателем')
  const cpByRef = new Map(
    (contractsQ.data?.counterparties ?? []).map((c) => [c.externalRef, c]),
  )

  const settleQ = useLocationSettlements(isEnergy ? location.id : null)
  const settlements = settleQ.data ?? []

  const empty = contracts.length === 0 && settlements.length === 0
    && !contractsQ.isLoading && !settleQ.isLoading
  const qc = useQueryClient()
  const [linking, setLinking] = useState(false)
  const [unlinkAsk, setUnlinkAsk] = useState<string | null>(null)
  const unlink = async (contractId: string) => {
    try {
      await unlinkContractLocation(contractId, location.id)
      await qc.invalidateQueries({ queryKey: ['axis', 'location', location.id, 'contracts'] })
      await qc.invalidateQueries({ queryKey: ['contracts', company?.id] })
      toast.success('Договор отвязан от станции'); setUnlinkAsk(null)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось отвязать договор') }
  }

  return (
    <ScrollTab>
      {/* Договор привязывается со стороны станции, а не только из «Контрагентов». */}
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => setLinking(true)}><Link2 className="h-3.5 w-3.5 mr-1" />Привязать договор</Button>
      </div>
      {linking && <LinkContractDialog location={location} linkedIds={contracts.map((c) => c.id)} onClose={() => setLinking(false)} />}
      {/* ── Платёжная дисциплина (energy) ── */}
      {isEnergy && settlements.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Платёжная дисциплина
          </div>
          {(['energy', 'rent'] as SettlementRole[]).map((role) => {
            const s = settlements.find((x) => x.role === role)
            if (!s) return null
            // Имя — из записи (сервер кладёт его сам): по внешнему коду 1С среди
            // контрагентов договоров оно не находилось никогда, код пуст у всех.
            const cpName = s.counterpartyName ?? (s.counterpartyId ? cpByRef.get(s.counterpartyId)?.name : null)
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
          text="Привяжите договор кнопкой «Привязать договор»: аренда, энергоснабжение, обслуживание — адресные на эту станцию; общие договоры компании появятся здесь сами."
        />
      )}
      {contracts.length > 0 && (
        <div className="space-y-2">
          {isEnergy && settlements.length > 0 && (
            <div className="pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Договоры
            </div>
          )}
          {own.length === 0 && <p className="text-xs text-muted-foreground">Адресных договоров у станции нет — только общие договоры компании ниже.</p>}
          {own.map((c) => (
            <div key={c.id} className="space-y-2 rounded-md border border-border/50 p-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link to={`/contractors?sub=contracts&contract=${c.id}`} className="font-medium text-primary hover:underline">{c.number}</Link>
                  <div className="text-xs text-muted-foreground">
                    {c.counterpartyName || c.counterpartyId}{c.kind && <span> · {KIND_RU[c.kind] ?? c.kind}</span>}
                    <span className={contractStatus(c).cls}> · {contractStatus(c).label}</span>
                  </div>
                </div>
                {c.companyWide
                  ? <Badge variant="secondary" className="shrink-0 gap-1 text-[10px]"><Building className="h-2.5 w-2.5" /> вся компания</Badge>
                  : <div className="flex shrink-0 items-center gap-1">
                      <Badge variant="outline" className="text-[10px]">адресный</Badge>
                      {unlinkAsk === c.id
                        ? <><Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => void unlink(c.id)}>Отвязать</Button>
                            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setUnlinkAsk(null)}>Нет</Button></>
                        : <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setUnlinkAsk(c.id)} title="Отвязать договор от станции">отвязать</Button>}
                    </div>}
              </div>
              {/* Условия начисления — тот же блок, что в карточке контрагента.
                  Их спрашивали именно здесь: «в „Объектах“ нет условий договоров»
                  (Мартынова, 25.08.2026) — ходить за ними в другое приложение
                  человеку неоткуда знать. */}
              {isEnergy && <OpsTermsBlock contractId={c.id} />}
            </div>
          ))}
          {common.length > 0 && (
            <details className="rounded-md border border-border/50 p-3 text-sm">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Общие договоры компании ({common.length}) — действуют на все станции
              </summary>
              <ul className="mt-2 divide-y">{common.map((c) => (
                <li key={c.id} className="py-1.5">
                  <Link to={`/contractors?sub=contracts&contract=${c.id}`} className="text-primary hover:underline">{c.number}</Link>
                  <span className="text-xs text-muted-foreground"> · {c.counterpartyName || c.counterpartyId}
                    <span className={contractStatus(c).cls}> · {contractStatus(c).label}</span></span>
                </li>))}</ul>
            </details>
          )}
          {clients.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Клиентские договоры сети: {clients.length} (корпоративная зарядка) — действуют на всех станциях,
              ведутся в <Link to="/contractors?sub=corp" className="underline">«Корпоративных клиентах»</Link>.
            </p>
          )}
        </div>
      )}
    </ScrollTab>
  )
}
