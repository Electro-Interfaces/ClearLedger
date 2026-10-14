/**
 * Приложения и проекты договора — сквозной разрез учёта.
 *
 * Договор один на пространство; приложение видит «свои» договоры по привязке (её ставят
 * здесь) и по фактическому использованию (расчёты станций, документы — считает сервер).
 * Энергоснабжение относится к «Эксплуатации» и к проекту строительства станции, аренда
 * площадки — к «Эксплуатации», договор подряда — к проекту в «Проектах».
 *
 * Поле работает с черновиком: в форме нового договора привязки сохраняются после
 * создания договора (`saveContractLinks`), в форме правки — разницей с сохранёнными.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { useSpaceApps } from '@/hooks/useSpaceApps'
import { SPACE_PRODUCTS, productLabel } from '@/config/spaceProducts'
import { addContractLink, deleteContractLink, searchContractProjects, type ContractLinkRef } from '@/services/referenceService'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-muted/60 px-2 text-sm'
/** Инструменты пространства договорами не владеют — их в выборе нет. */
const TOOL_APPS = new Set(['chat', 'conf', 'admin', 'info', 'pulse', 'auditor', 'plan'])
const EXTRA_LABEL: Record<string, string> = { docs: 'Трек', mail: 'Почта', support: 'Поддержка', books: 'Бухгалтерия' }
/** Приложения, внутри которых договор привязывается к проекту. */
const WITH_PROJECTS = new Set(['projects'])

export type ContractLinkDraft = Omit<ContractLinkRef, 'id'> & { id?: string }

export function useAppLabel(): (code: string) => string {
  const { company } = useCompany()
  const { apps } = useSpaceApps()
  return (code) => {
    const p = SPACE_PRODUCTS.find((x) => x.code === code)
    return (p && productLabel(p, company.profileId)) || apps.find((a) => a.code === code)?.name || EXTRA_LABEL[code] || code
  }
}

export function ContractAppsField({ value, onChange }: { value: ContractLinkDraft[]; onChange: (v: ContractLinkDraft[]) => void }) {
  const { companyId } = useCompany()
  const { apps } = useSpaceApps()
  const label = useAppLabel()
  const [app, setApp] = useState('')
  const [q, setQ] = useState('')
  const [project, setProject] = useState<{ ref: string; label: string } | null>(null)
  const options = useQuery({
    queryKey: ['contract-projects', companyId, q], queryFn: () => searchContractProjects(companyId, q),
    enabled: WITH_PROJECTS.has(app), staleTime: 60_000,
  })
  const choices = apps.filter((a) => !TOOL_APPS.has(a.code))
  const add = () => {
    if (!app) return
    const ref = project?.ref ?? null
    if (!value.some((l) => l.app === app && (l.projectRef ?? null) === ref))
      onChange([...value, { app, projectRef: ref, projectLabel: project?.label ?? null }])
    setProject(null); setQ('')
  }
  return <div className="space-y-2">
    {value.length > 0 ? <div className="flex flex-wrap gap-1">{value.map((l) =>
      <span key={`${l.app}|${l.projectRef ?? ''}`} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs">
        {label(l.app)}{l.projectRef ? ` → ${l.projectLabel ?? 'проект'}` : ''}
        <button type="button" aria-label={`Снять привязку ${label(l.app)}`} onClick={() => onChange(value.filter((x) => x !== l))}><X className="size-3" /></button>
      </span>)}</div>
      : <p className="text-xs text-muted-foreground">Не привязан. Приложения, где договор уже используется (расчёты, документы), видят его и без привязки.</p>}
    <div className="grid gap-2 sm:grid-cols-[180px_1fr_auto] items-start">
      <select aria-label="Приложение договора" className={selectClass} value={app} onChange={(e) => { setApp(e.target.value); setProject(null) }}>
        <option value="">Приложение…</option>
        {choices.map((a) => <option key={a.code} value={a.code}>{label(a.code)}</option>)}
      </select>
      {WITH_PROJECTS.has(app) ? <div className="space-y-1 min-w-0">
        <Input aria-label="Поиск проекта" className="h-9" value={project ? project.label : q} placeholder="Проект: название, номер, адрес (необязательно)"
          onChange={(e) => { setProject(null); setQ(e.target.value) }} />
        {!project && q && <div className="max-h-40 overflow-y-auto rounded-md border divide-y">
          {(options.data ?? []).map((o) => <button type="button" key={o.ref} className="block w-full text-left px-2 py-1 text-sm hover:bg-muted"
            onClick={() => setProject({ ref: o.ref, label: o.label })}>{o.label}{o.kind === 'integration' ? ' · интеграция' : ''}</button>)}
          {options.data?.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">Не найдено</p>}
        </div>}
      </div> : <div />}
      <Button type="button" size="sm" variant="outline" disabled={!app} onClick={add}>Привязать</Button>
    </div>
  </div>
}

/** Сохранить черновик привязок: добавить новые, снять убранные. */
export async function saveContractLinks(contractId: string, before: ContractLinkDraft[], after: ContractLinkDraft[]) {
  const key = (l: ContractLinkDraft) => `${l.app}|${l.projectRef ?? ''}`
  const keep = new Set(after.map(key))
  for (const l of before) if (l.id && !keep.has(key(l))) await deleteContractLink(contractId, l.id)
  const had = new Set(before.map(key))
  for (const l of after) if (!had.has(key(l))) await addContractLink(contractId, l.app, l.projectRef)
}
