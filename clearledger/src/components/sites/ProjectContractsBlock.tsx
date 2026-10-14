/**
 * Договоры проекта — те же договоры пространства, увиденные из «Проектов».
 *
 * Своих договоров у проекта нет: договор заводится у контрагента, а здесь видны
 * привязанные к проекту и используемые им (договор на землю, договоры интеграции).
 * Привязать — найти договор пространства; снять — только явную привязку: фактическое
 * использование снимается там, где договор использован.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useContracts, useCounterparties } from '@/hooks/useReferences'
import { addContractLink, deleteContractLink, getContractBindings, getContractLinks } from '@/services/referenceService'
import { contractStatus } from '@/components/reference/ContractStationsField'

export function ProjectContractsBlock({ siteId, companyId }: { siteId: string; companyId: string }) {
  const ref = `site:${siteId}`
  const qc = useQueryClient()
  const contracts = useContracts()
  const cps = useCounterparties()
  const bindings = useQuery({ queryKey: ['contract-bindings', companyId], queryFn: () => getContractBindings(companyId), staleTime: 60_000 })
  const [adding, setAdding] = useState(false)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const cpName = useMemo(() => new Map((cps.data ?? []).flatMap((c) => [[c.id, c.name], [c.externalRef ?? c.id, c.name]] as [string, string][])), [cps.data])
  const mine = (contracts.data ?? []).filter((c) => bindings.data?.contracts[c.id]?.projects.includes(ref))
  const linked = (id: string) => bindings.data?.contracts[id]?.linked.includes(`projects|${ref}`) ?? false
  const found = useMemo(() => {
    const n = q.trim().toLocaleLowerCase('ru')
    if (!n) return []
    return (contracts.data ?? []).filter((c) => !mine.includes(c) && `${c.number} ${c.type} ${cpName.get(c.counterpartyId) ?? ''}`.toLocaleLowerCase('ru').includes(n)).slice(0, 30)
  }, [q, contracts.data, mine, cpName])

  const refresh = () => qc.invalidateQueries({ queryKey: ['contract-bindings', companyId] })
  const link = async (id: string) => {
    setBusy(true)
    try { await addContractLink(id, 'projects', ref); await refresh(); toast.success('Договор привязан к проекту'); setQ(''); setAdding(false) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось привязать') } finally { setBusy(false) }
  }
  const unlink = async (id: string) => {
    setBusy(true)
    try {
      const ln = (await getContractLinks(id)).find((l) => l.app === 'projects' && l.projectRef === ref)
      if (ln) await deleteContractLink(id, ln.id)
      await refresh(); toast.success('Привязка снята')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось снять привязку') } finally { setBusy(false) }
  }

  return <section className="space-y-2 rounded-md border p-3">
    <div className="flex flex-wrap items-center gap-2">
      <h3 className="text-sm font-medium flex-1">Договоры проекта</h3>
      <Link className="text-xs underline" to={`/projects/contractors?sub=contracts&project=${encodeURIComponent(ref)}`}>в «Договорах»</Link>
      <Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)}>Привязать договор</Button>
    </div>
    {adding && <div className="space-y-1">
      <Input aria-label="Поиск договора" className="h-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, вид, контрагент" />
      {found.length > 0 && <div className="max-h-48 overflow-y-auto rounded-md border divide-y">{found.map((c) =>
        <div key={c.id} className="flex items-center gap-2 px-2 py-1 text-sm">
          <span className="flex-1 min-w-0 truncate">№ {c.number} от {c.date || '—'} · {c.type} · {cpName.get(c.counterpartyId) ?? '—'}</span>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => void link(c.id)}>Привязать</Button>
        </div>)}</div>}
      <p className="text-xs text-muted-foreground">Нового договора здесь нет: его заводят у контрагента («Контрагенты» → «Договоры»), а в форме договора указывают этот проект.</p>
    </div>}
    {bindings.isLoading || contracts.isLoading ? <p className="text-xs text-muted-foreground">Загрузка…</p>
      : mine.length === 0 ? <p className="text-xs text-muted-foreground">Договоров у проекта нет.</p>
      : <ul className="divide-y text-sm">{mine.map((c) => <li key={c.id} className="flex items-center gap-2 py-1.5">
          <div className="flex-1 min-w-0">
            <div className="truncate">№ {c.number} от {c.date || '—'} · {c.type}</div>
            <div className="text-xs text-muted-foreground truncate">{cpName.get(c.counterpartyId) ?? '—'} · <span className={contractStatus(c).cls}>{contractStatus(c).label}</span>
              {linked(c.id) ? '' : ' · используется в проекте'}</div>
          </div>
          {linked(c.id) && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void unlink(c.id)}>отвязать</Button>}
        </li>)}</ul>}
  </section>
}
