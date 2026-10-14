/**
 * Качество договоров — что мешает договору работать разрезом учёта.
 *
 * Плитка — вход в свой список (как «Разбор данных» оборудования): договор открывается
 * в «Договорах», станции без договора привязывается договор прямо отсюда, контрагент
 * без ИНН открывается карточкой. Исправленное уходит из списка при следующем открытии.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { get } from '@/services/apiClient'
import { LinkContractDialog } from '@/components/locations/cockpit/LinkContractDialog'
import type { ServiceLocation } from '@/types/location'

interface Item { id: string; number?: string; date?: string; valid_until?: string | null; type?: string; counterparty?: string; code?: string; name?: string; address?: string; contracts?: number }
interface Section { key: string; label: string; hint: string; count: number; kind: 'contract' | 'location' | 'counterparty'; items: Item[] }

export function ContractQualityPanel({ onContract, onCounterparty }: { onContract: (id: string) => void; onCounterparty: (id: string) => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['contract-quality', companyId], queryFn: () => get<{ sections: Section[] }>('/api/references/contract-quality', { company_id: companyId }) })
  const [focus, setFocus] = useState<string | null>(null)
  const [linkTo, setLinkTo] = useState<Item | null>(null)
  if (q.isLoading) return <p className="p-3 text-sm text-muted-foreground">Проверяю договоры…</p>
  if (!q.data) return null
  const sections = q.data.sections
  const open = sections.find((s) => s.key === focus)
  return (
    <div className="space-y-3 mb-4">
      <p className="text-sm font-medium">Качество договоров</p>
      <div className="grid gap-2 grid-cols-2 sm:grid-cols-4">
        {sections.map((s) => <button key={s.key} type="button" onClick={() => setFocus(focus === s.key ? null : s.key)}
          className={`rounded-md border p-2 text-left min-w-0 ${focus === s.key ? 'border-primary bg-primary/5' : ''} ${s.count ? '' : 'opacity-60'}`}>
          <div className={`text-lg font-semibold tabular-nums ${s.count ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}`}>{s.count}</div>
          <div className="text-xs leading-snug">{s.label}</div>
        </button>)}
      </div>
      {open && <div className="rounded-md border p-2 space-y-2">
        <p className="text-xs text-muted-foreground">{open.hint}{open.count > open.items.length ? ` Показаны первые ${open.items.length} из ${open.count}.` : ''}</p>
        {open.items.length === 0 ? <p className="text-sm text-muted-foreground">Всё в порядке.</p>
          : <ul className="divide-y max-h-[50vh] overflow-y-auto text-sm">{open.items.map((it) => <li key={it.id} className="flex items-center gap-2 py-1.5">
            <div className="flex-1 min-w-0">
              {open.kind === 'contract' && <><div className="truncate">№ {it.number} от {it.date || '—'} · {it.type}</div>
                <div className="text-xs text-muted-foreground truncate">{it.counterparty ?? '—'}{it.valid_until ? ` · срок до ${it.valid_until}` : ''}</div></>}
              {open.kind === 'location' && <><div className="truncate">{it.code} · {it.name}</div><div className="text-xs text-muted-foreground truncate">{it.address}</div></>}
              {open.kind === 'counterparty' && <div className="truncate">{it.name} <span className="text-xs text-muted-foreground">· договоров {it.contracts}</span></div>}
            </div>
            {open.kind === 'contract' && <Button size="sm" variant="ghost" onClick={() => onContract(it.id)}>открыть</Button>}
            {open.kind === 'location' && <Button size="sm" variant="ghost" onClick={() => setLinkTo(it)}>привязать договор</Button>}
            {open.kind === 'counterparty' && <Button size="sm" variant="ghost" onClick={() => onCounterparty(it.id)}>открыть</Button>}
          </li>)}</ul>}
      </div>}
      {linkTo && <LinkContractDialog location={{ id: linkTo.id, name: `${linkTo.code} · ${linkTo.name}` } as ServiceLocation} linkedIds={[]}
        onClose={() => { setLinkTo(null); qc.invalidateQueries({ queryKey: ['contract-quality', companyId] }) }} />}
    </div>
  )
}
