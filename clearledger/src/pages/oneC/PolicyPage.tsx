/**
 * Страница «1С → Учётная политика».
 *
 * Показывает последний срез УчетнаяПолитика по каждой организации:
 * - МПЗ (СпособОценкиМПЗ — обычно ФИФО или СредняяСтоимость)
 * - Система налогообложения (ОСН/УСН)
 * - ПБУ 18/02
 * - Раздельный учёт НДС
 * - Полный JSONB настроек (collapsible)
 *
 * Источник — POST /api/onec/connections/{id}/sync/policy →
 * сохраняется в таблице OneCPolicy, читается GET /api/policy.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RefreshCw, Loader2, ChevronDown, ChevronRight, Landmark, ScrollText } from 'lucide-react'
import { toast } from 'sonner'

import { useCompany } from '@/contexts/CompanyContext'
import { get, post } from '@/services/apiClient'

interface PolicyRow {
  id: string
  company_id: string
  organization_external_ref: string | null
  organization_name: string | null
  period: string | null
  mpz_method: string | null
  tax_system: string | null
  vat_rate: string | null
  pbu_18_02: boolean
  separate_vat_accounting: boolean
  settings: Record<string, unknown>
  created_at: string
  updated_at: string
}

interface Connection {
  id: string
  company_id: string
  name: string
  status: string
}

async function fetchPolicies(companyId: string): Promise<PolicyRow[]> {
  return get<PolicyRow[]>('/api/policy', { company_id: companyId })
}

async function fetchConnections(companyId: string): Promise<Connection[]> {
  return get<Connection[]>('/api/onec/connections', { company_id: companyId })
}

async function syncPolicy(connectionId: string): Promise<{ status: string; stats: { processed: number }; details: Record<string, unknown> }> {
  return post(`/api/onec/connections/${connectionId}/sync/policy`)
}

export function PolicyPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  // collapsed = свёрнутые карточки. По умолчанию ВСЕ развёрнуты.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const { data: policies, isLoading, error } = useQuery({
    queryKey: ['onec-policies', companyId],
    queryFn: () => fetchPolicies(companyId),
  })

  const { data: connections } = useQuery({
    queryKey: ['onec-connections', companyId],
    queryFn: () => fetchConnections(companyId),
  })

  const activeConn = connections?.find((c) => c.status === 'active') ?? connections?.[0]

  const sync = useMutation({
    mutationFn: () => {
      if (!activeConn) throw new Error('Нет активного подключения к 1С')
      return syncPolicy(activeConn.id)
    },
    onSuccess: (r) => {
      const d = r.details ?? {}
      const errorMsg = d.error as string | undefined
      if (r.status === 'error' || errorMsg) {
        toast.error(`Ошибка sync: ${errorMsg ?? r.status}`, { duration: 10000 })
      } else {
        toast.success(`Учётная политика обновлена: ${r.stats.processed} орг.`, {
          description: `Регистр: ${d.policy_entity ?? '—'} · полей: ${(d.available_fields as string[] | undefined)?.length ?? 0}`,
        })
      }
      qc.invalidateQueries({ queryKey: ['onec-policies', companyId] })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка sync', { duration: 10000 }),
  })

  function toggle(id: string) {
    setCollapsed((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Landmark className="h-6 w-6" />
            Учётная политика
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Срез РегС.УчетнаяПолитика по каждой организации из БП ГИГ.
            Используется для проверки соответствия алгоритмов сверки фактической политике.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => sync.mutate()}
          disabled={!activeConn || sync.isPending}
        >
          {sync.isPending ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1.5" />}
          Обновить из 1С
        </Button>
      </div>

      {error && (
        <Card className="border-red-500/40">
          <CardContent className="pt-6 text-sm text-red-400">
            Ошибка загрузки: {error instanceof Error ? error.message : String(error)}
          </CardContent>
        </Card>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Загрузка...
        </div>
      )}

      {!isLoading && policies && policies.length === 0 && (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground text-center">
            Учётная политика пока не загружена. Нажмите «Обновить из 1С».
          </CardContent>
        </Card>
      )}

      {policies?.map((p) => {
        const isExp = !collapsed.has(p.id)
        return (
          <Card key={p.id}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base flex items-center gap-2">
                    <ScrollText className="h-4 w-4 text-muted-foreground" />
                    {p.organization_name ?? p.organization_external_ref ?? '—'}
                  </CardTitle>
                  <CardDescription className="text-xs mt-0.5">
                    Период с {p.period ? new Date(p.period).toLocaleDateString('ru-RU') : '—'}
                  </CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => toggle(p.id)}>
                  {isExp ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  Все настройки
                </Button>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
                <Field label="МПЗ" value={p.mpz_method} />
                <Field label="Налогообложение" value={p.tax_system} highlight={p.tax_system === 'ОСН'} />
                <Field label="Ставки налогов" value={p.vat_rate} />
                <Field label="ПБУ 18/02" value={p.pbu_18_02 ? 'Применяется' : 'Не применяется'} />
                <Field label="Раздельный НДС" value={p.separate_vat_accounting ? 'Да' : 'Нет'} />
              </div>
              {isExp && <PolicyRegistersBlock settings={p.settings} />}
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function PolicyRegistersBlock({ settings }: { settings: Record<string, unknown> }) {
  const perReg = (settings?._per_register as Record<string, Record<string, unknown>> | undefined) ?? {}
  const regNames = Object.keys(perReg).sort()
  if (regNames.length === 0) {
    return (
      <pre className="mt-3 text-[11px] bg-muted/40 rounded p-3 overflow-x-auto max-h-80">
        {JSON.stringify(settings, null, 2)}
      </pre>
    )
  }
  function fmtVal(v: unknown): string {
    if (v === null || v === undefined || v === '') return '—'
    if (typeof v === 'boolean') return v ? 'Да' : 'Нет'
    if (typeof v === 'string') {
      // 36-символьный GUID — обрезаем
      if (/^[0-9a-f]{8}-[0-9a-f]{4}/i.test(v)) return v.slice(0, 8) + '…'
      return v
    }
    return String(v)
  }
  return (
    <div className="mt-3 space-y-3">
      <div className="text-[10px] uppercase text-muted-foreground tracking-wider">
        Содержимое регистров ({regNames.length})
      </div>
      {regNames.map((reg) => {
        const data = perReg[reg] ?? {}
        const keys = Object.keys(data).filter((k) => k !== 'Period' && !k.endsWith('_Key') && k !== '_per_register')
        // Сначала измерения (Organization), потом всё остальное
        return (
          <div key={reg} className="border rounded-md bg-muted/20">
            <div className="px-3 py-1.5 text-[11px] font-semibold border-b bg-muted/30 flex items-center justify-between">
              <span>{reg}</span>
              <span className="text-muted-foreground font-mono text-[10px]">{keys.length} полей</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-1 p-3 text-[11px]">
              {keys.map((k) => (
                <div key={k} className="flex items-start gap-1.5">
                  <span className="text-muted-foreground truncate min-w-0">{k}:</span>
                  <span className="font-mono truncate min-w-0">{fmtVal(data[k])}</span>
                </div>
              ))}
              {keys.length === 0 && (
                <span className="text-muted-foreground italic col-span-3">только Period + Организация</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Field({ label, value, highlight }: { label: string; value: string | null; highlight?: boolean }) {
  return (
    <div>
      <div className="text-muted-foreground text-[10px] uppercase tracking-wider">{label}</div>
      <div className="mt-0.5">
        {value ? (
          <Badge variant="outline" className={highlight ? 'border-emerald-400/40 text-emerald-300' : ''}>
            {value}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </div>
    </div>
  )
}
