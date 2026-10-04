/**
 * Привязать договор к станции — из её карточки: найти договор пространства или
 * завести новый с контрагентом. Раньше вкладка «Право» договоры только показывала,
 * а привязка жила в другом приложении («Контрагенты» → «Охват договора»).
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import { getContracts, getCounterparties, linkContractLocation } from '@/services/referenceService'
import { contractStatus } from '@/components/reference/ContractStationsField'
import { CounterpartyContractPicker } from '@/components/equipment/CounterpartyContractPicker'
import type { ServiceLocation } from '@/types/location'

export function LinkContractDialog({ location, linkedIds, onClose }: { location: ServiceLocation; linkedIds: string[]; onClose: () => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const contracts = useQuery({ queryKey: ['contracts', companyId], queryFn: () => getContracts(companyId) })
  const cps = useQuery({ queryKey: ['counterparties', companyId], queryFn: () => getCounterparties(companyId), staleTime: 60_000 })
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [party, setParty] = useState({ counterpartyId: '', contractId: '' })
  const cpName = useMemo(() => new Map((cps.data ?? []).map((c) => [c.id, c.shortName || c.name])), [cps.data])
  const found = useMemo(() => {
    const n = q.trim().toLocaleLowerCase('ru')
    return (contracts.data ?? []).filter((c) => !linkedIds.includes(c.id) && c.scopeType !== 'company' && !c.isClosed)
      .filter((c) => !n || `${c.number} ${c.type ?? ''} ${cpName.get(c.counterpartyId) ?? ''}`.toLocaleLowerCase('ru').includes(n))
      .slice(0, 100)
  }, [contracts.data, q, linkedIds, cpName])

  const link = async (contractId: string) => {
    setBusy(contractId)
    try {
      await linkContractLocation(contractId, location.id)
      for (const k of [['axis', 'location', location.id, 'contracts'], ['contracts', companyId], ['references', companyId]]) await qc.invalidateQueries({ queryKey: k })
      toast.success('Договор привязан к станции'); onClose()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось привязать договор') }
    finally { setBusy(null) }
  }

  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-2xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>Договор для станции «{location.name}»</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div className="space-y-2">
          <div className="text-sm font-medium">Найти договор пространства</div>
          <Input aria-label="Поиск договора" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, вид, контрагент" className="h-9" />
          <div className="max-h-64 overflow-y-auto divide-y rounded-md border">
            {contracts.isLoading ? <p className="p-2 text-xs text-muted-foreground">Загрузка…</p>
              : found.length === 0 ? <p className="p-2 text-xs text-muted-foreground">Не найдено — заведите договор ниже.</p>
              : found.map((c) => <div key={c.id} className="flex items-center gap-2 p-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div><span className="font-mono">№ {c.number}</span> <span className="text-muted-foreground">от {c.date || '—'} · {c.type || '—'}</span></div>
                  <div className="text-xs text-muted-foreground truncate">{cpName.get(c.counterpartyId) ?? '—'} · <span className={contractStatus(c).cls}>{contractStatus(c).label}</span>
                    {c.scopeType === 'locations' && c.locationsCount ? ` · станций: ${c.locationsCount}` : ''}</div>
                </div>
                <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void link(c.id)}>
                  {busy === c.id && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Привязать</Button>
              </div>)}
          </div>
          <p className="text-xs text-muted-foreground">Общие договоры компании здесь не показаны: они и так действуют на все станции.</p>
        </div>
        <div className="space-y-2 border-t pt-3">
          <div className="text-sm font-medium">Или новый договор</div>
          <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty} preferredTypes={['Аренда', 'Энергоснабжение']} />
          <Button size="sm" disabled={!party.contractId || !!busy} onClick={() => void link(party.contractId)}>Привязать выбранный договор</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
}
