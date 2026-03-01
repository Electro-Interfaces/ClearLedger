/**
 * AuditTab — полный отчёт аудитора TSupport с возможностью применить результаты.
 *
 * 5 collapsible-секций:
 * 1. Проверенные записи (read-only)
 * 2. Предложения обогащения (принять/пропустить)
 * 3. Соответствия CL↔1С (read-only)
 * 4. Не найдены в CL (создать/пропустить)
 * 5. Находки (решения: принять/исправить/пропустить)
 */

import { useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import {
  Bot, Loader2, ExternalLink, CheckCircle, ChevronDown,
  AlertOctagon, AlertTriangle, Info, Check, Pencil, X,
  Sparkles, Link2, FilePlus, ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import type {
  AuditorNormResult, AuditorNormFinding,
  AuditFindingResolution, AuditProposalStatus,
  AuditEnrichmentProposal, AuditMissingEntry,
} from '@/types'
import { useApplyAuditEnrichment, useCreateEntryFromAudit } from '@/hooks/useNormalization'

// ---- Демо-данные ----

const now = new Date().toISOString()

export const DEMO_AUDIT_RESULT: AuditorNormResult = {
  companyId: '',
  status: 'done',
  period: { from: '2025-10-01', to: '2025-12-31' },
  totalChecked: 247,
  matchedCount: 231,

  verifiedEntries: [
    { entryId: 'v-1', entryTitle: 'Счёт-фактура №102 от 03.10.2025', accDocNumber: 'СФ-102', accDocDate: '2025-10-03' },
    { entryId: 'v-2', entryTitle: 'ТТН №345 от 15.10.2025', accDocNumber: 'ТТН-345', accDocDate: '2025-10-15' },
    { entryId: 'v-3', entryTitle: 'Акт №67 от 28.10.2025', accDocNumber: 'АКТ-67', accDocDate: '2025-10-28' },
    { entryId: 'v-4', entryTitle: 'Накладная №201 от 12.11.2025', accDocNumber: 'ТОРГ12-201', accDocDate: '2025-11-12' },
    { entryId: 'v-5', entryTitle: 'Платёжное поручение №88 от 30.11.2025', accDocNumber: 'ПП-88', accDocDate: '2025-11-30' },
  ],

  enrichmentProposals: [
    {
      id: 'ep-1', entryId: 'e-demo-1', entryTitle: 'Акт №89 от 05.12.2025',
      field: 'Сумма', currentValue: '98 500', proposedValue: '98 050',
      source: '1С: Поступление №456 от 12.11.2025', metadataKey: 'amount',
    },
    {
      id: 'ep-2', entryId: 'e-demo-2', entryTitle: 'Накладная №77 от 20.11.2025',
      field: 'Номер договора', currentValue: undefined, proposedValue: 'Д-2025/114',
      source: '1С: Реализация №77 от 20.11.2025', metadataKey: '_ref.contractNumber',
    },
    {
      id: 'ep-3', entryId: 'e-demo-3', entryTitle: 'Поступление №123 от 01.12.2025',
      field: 'КПП контрагента', currentValue: '770101001', proposedValue: '770102001',
      source: '1С: Контрагент ООО «Альфа»', metadataKey: '_ref.counterpartyKpp',
    },
    {
      id: 'ep-4', entryId: 'e-demo-4', entryTitle: 'Счёт №55 от 10.12.2025',
      field: 'НДС', currentValue: undefined, proposedValue: '15 833.33',
      source: '1С: Счёт-фактура №55 от 10.12.2025', metadataKey: 'vatAmount',
    },
  ],

  correspondences: [
    { entryId: 'c-1', entryTitle: 'Счёт-фактура №102', accDocNumber: 'СФ-102', accDocType: 'Счёт-фактура', accDocDate: '2025-10-03', accDocAmount: 245000, entryAmount: 245000, matchScore: 100 },
    { entryId: 'c-2', entryTitle: 'ТТН №345', accDocNumber: 'ТТН-345', accDocType: 'Накладная', accDocDate: '2025-10-15', accDocAmount: 89700, entryAmount: 89700, matchScore: 100 },
    { entryId: 'c-3', entryTitle: 'Акт №67', accDocNumber: 'АКТ-67', accDocType: 'Акт', accDocDate: '2025-10-28', accDocAmount: 156300, entryAmount: 156300, matchScore: 98 },
    { entryId: 'c-4', entryTitle: 'Накладная №201', accDocNumber: 'ТОРГ12-201', accDocType: 'Накладная', accDocDate: '2025-11-12', accDocAmount: 312500, entryAmount: 312000, matchScore: 95 },
    { entryId: 'c-5', entryTitle: 'ПП №88', accDocNumber: 'ПП-88', accDocType: 'Оплата', accDocDate: '2025-11-30', accDocAmount: 425000, entryAmount: 425000, matchScore: 100 },
    { entryId: 'c-6', entryTitle: 'Акт №89', accDocNumber: 'АКТ-89', accDocType: 'Акт', accDocDate: '2025-12-05', accDocAmount: 98050, entryAmount: 98500, matchScore: 92 },
    { entryId: 'c-7', entryTitle: 'Счёт №55', accDocNumber: 'СЧ-55', accDocType: 'Счёт', accDocDate: '2025-12-10', accDocAmount: 95000, entryAmount: 95000, matchScore: 100 },
    { entryId: 'c-8', entryTitle: 'Накладная №77', accDocNumber: 'ТОРГ12-77', accDocType: 'Накладная', accDocDate: '2025-11-20', accDocAmount: 178400, entryAmount: 178400, matchScore: 85 },
  ],

  missingEntries: [
    {
      id: 'me-1',
      accDocNumber: '456', accDocType: 'Поступление', accDocDate: '2025-11-12',
      counterpartyName: 'ООО «Ромашка»', amount: 125400,
      proposedEntry: {
        title: 'Поступление №456 от 12.11.2025',
        categoryId: 'primary', subcategoryId: 'invoices', docTypeId: 'invoice',
        metadata: {
          docNumber: '456', docDate: '2025-11-12',
          counterparty: 'ООО «Ромашка»', amount: '125400',
        },
      },
    },
    {
      id: 'me-2',
      accDocNumber: '789', accDocType: 'Счёт-фактура', accDocDate: '2025-12-25',
      counterpartyName: 'ИП Иванов А.С.', amount: 45000,
      proposedEntry: {
        title: 'Счёт-фактура №789 от 25.12.2025',
        categoryId: 'primary', subcategoryId: 'invoices', docTypeId: 'invoice-factura',
        metadata: {
          docNumber: '789', docDate: '2025-12-25',
          counterparty: 'ИП Иванов А.С.', amount: '45000',
        },
      },
    },
  ],

  findings: [
    {
      id: 'af-1', severity: 'critical', category: 'missing_in_cl',
      title: 'Не найден оригинал: Поступление №456 от 12.11.2025',
      description: 'Документ из 1С (125 400 ₽, ООО «Ромашка») — нет соответствующей записи в ClearLedger',
      detectedAt: now,
    },
    {
      id: 'af-2', severity: 'warning', category: 'amount_mismatch',
      title: 'Расхождение суммы: Акт №89 от 05.12.2025',
      description: 'ClearLedger: 98 500 ₽ → 1С: 98 050 ₽ (разница 450 ₽)',
      entryId: 'e-demo-1',
      detectedAt: now,
    },
    {
      id: 'af-3', severity: 'info', category: 'period_incomplete',
      title: 'Неполный период: декабрь 2025',
      description: 'В 1С зарегистрировано 84 документа, в ClearLedger — 79 (не хватает 5)',
      detectedAt: now,
    },
  ],

  startedAt: new Date(Date.now() - 120_000).toISOString(),
  finishedAt: now,
}

// ---- Конфиги ----

const auditSeverityConfig = {
  critical: { icon: AlertOctagon, iconBg: 'hsl(0 84% 60% / 0.15)', iconColor: 'text-red-500' },
  warning: { icon: AlertTriangle, iconBg: 'hsl(45 100% 55% / 0.15)', iconColor: 'text-yellow-500' },
  info: { icon: Info, iconBg: 'hsl(217 91% 60% / 0.15)', iconColor: 'text-blue-500' },
} as const

const resolutionConfig: Record<AuditFindingResolution, { label: string; badgeClass: string } | null> = {
  pending: null,
  accepted: { label: 'Принято', badgeClass: 'border-green-500 text-green-400' },
  corrected: { label: 'Исправлено', badgeClass: 'border-blue-500 text-blue-400' },
  dismissed: { label: 'Пропущено', badgeClass: 'border-muted-foreground text-muted-foreground' },
}

// ---- Collapsible Section ----

function CollapsibleSection({
  title, icon: Icon, iconBg, iconColor, count, badge, defaultOpen, children,
}: {
  title: string
  icon: React.ElementType
  iconBg: string
  iconColor: string
  count: number
  badge?: { label: string; className: string }
  defaultOpen: boolean
  children: React.ReactNode
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger className="flex items-center gap-3 w-full group py-2 cursor-pointer">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
          style={{ background: iconBg }}
        >
          <Icon className={`size-3.5 ${iconColor}`} />
        </div>
        <span className="text-sm font-medium text-foreground">{title}</span>
        <Badge variant="secondary" className="text-xs">{count}</Badge>
        {badge && (
          <Badge variant="outline" className={`text-xs ${badge.className}`}>{badge.label}</Badge>
        )}
        <ChevronDown className="size-4 ml-auto text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 mb-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}

// ---- Finding Card ----

function AuditFindingCard({ finding, resolution, onResolve }: {
  finding: AuditorNormFinding
  resolution: AuditFindingResolution
  onResolve: (findingId: string, resolution: AuditFindingResolution) => void
}) {
  const cfg = auditSeverityConfig[finding.severity] || auditSeverityConfig.info
  const Icon = cfg.icon
  const isResolved = resolution !== 'pending'
  const resCfg = resolutionConfig[resolution]

  return (
    <Card className={isResolved ? 'opacity-60' : undefined}>
      <CardContent className="flex items-start gap-3">
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ background: cfg.iconBg }}
        >
          <Icon className={`size-3.5 ${cfg.iconColor}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-foreground">{finding.title}</p>
            {resCfg && (
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${resCfg.badgeClass}`}>
                {resCfg.label}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">{finding.description}</p>
          {!isResolved && (
            <div className="flex items-center gap-1.5 mt-2">
              <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => onResolve(finding.id, 'accepted')}>
                <Check className="size-3" /> Принять
              </Button>
              {finding.entryId && (
                <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => onResolve(finding.id, 'corrected')}>
                  <Pencil className="size-3" /> Исправить
                </Button>
              )}
              <Button size="sm" variant="ghost" className="h-7 text-xs gap-1 text-muted-foreground" onClick={() => onResolve(finding.id, 'dismissed')}>
                <X className="size-3" /> Пропустить
              </Button>
            </div>
          )}
          {isResolved && (
            <Button size="sm" variant="ghost" className="h-6 text-[10px] mt-1 text-muted-foreground px-1" onClick={() => onResolve(finding.id, 'pending')}>
              Отменить решение
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---- AuditTab ----

export function AuditTab({ result, isAuditing, localDone }: {
  result: AuditorNormResult | null
  isAuditing: boolean
  localDone: boolean
}) {
  const [enrichmentStatuses, setEnrichmentStatuses] = useState<Record<string, AuditProposalStatus>>({})
  const [missingStatuses, setMissingStatuses] = useState<Record<string, AuditProposalStatus>>({})
  const [findingResolutions, setFindingResolutions] = useState<Record<string, AuditFindingResolution>>({})

  const applyEnrichment = useApplyAuditEnrichment()
  const createEntry = useCreateEntryFromAudit()

  // ---- Handlers ----

  const handleAcceptEnrichment = useCallback((proposal: AuditEnrichmentProposal) => {
    applyEnrichment.mutate(
      { entryId: proposal.entryId, metadataKey: proposal.metadataKey, proposedValue: proposal.proposedValue },
      {
        onSuccess: () => {
          setEnrichmentStatuses((prev) => ({ ...prev, [proposal.id]: 'applied' }))
          toast.success(`Обогащение применено: ${proposal.field}`)
        },
      },
    )
  }, [applyEnrichment])

  const handleDismissEnrichment = useCallback((id: string) => {
    setEnrichmentStatuses((prev) => ({ ...prev, [id]: 'dismissed' }))
  }, [])

  const handleCreateMissing = useCallback((entry: AuditMissingEntry) => {
    createEntry.mutate(entry, {
      onSuccess: () => {
        setMissingStatuses((prev) => ({ ...prev, [entry.id]: 'applied' }))
        toast.success(`Запись создана: ${entry.proposedEntry.title}`)
      },
    })
  }, [createEntry])

  const handleDismissMissing = useCallback((id: string) => {
    setMissingStatuses((prev) => ({ ...prev, [id]: 'dismissed' }))
  }, [])

  const handleResolveFinding = useCallback((findingId: string, resolution: AuditFindingResolution) => {
    setFindingResolutions((prev) => ({ ...prev, [findingId]: resolution }))
  }, [])

  const handleAcceptAllEnrichments = useCallback(() => {
    if (!result) return
    const pending = result.enrichmentProposals.filter((p) => !enrichmentStatuses[p.id] || enrichmentStatuses[p.id] === 'pending')
    pending.forEach((p) => handleAcceptEnrichment(p))
  }, [result, enrichmentStatuses, handleAcceptEnrichment])

  const handleCreateAllMissing = useCallback(() => {
    if (!result) return
    const pending = result.missingEntries.filter((m) => !missingStatuses[m.id] || missingStatuses[m.id] === 'pending')
    pending.forEach((m) => handleCreateMissing(m))
  }, [result, missingStatuses, handleCreateMissing])

  const handleBulkApply = useCallback(() => {
    if (!result) return
    let enrichCount = 0
    let createCount = 0

    result.enrichmentProposals.forEach((p) => {
      if (!enrichmentStatuses[p.id] || enrichmentStatuses[p.id] === 'pending') {
        handleAcceptEnrichment(p)
        enrichCount++
      }
    })
    result.missingEntries.forEach((m) => {
      if (!missingStatuses[m.id] || missingStatuses[m.id] === 'pending') {
        handleCreateMissing(m)
        createCount++
      }
    })

    if (enrichCount > 0 || createCount > 0) {
      toast.success('Результаты аудита применены', {
        description: `Обогащений: ${enrichCount}, создано записей: ${createCount}`,
      })
    }
  }, [result, enrichmentStatuses, missingStatuses, handleAcceptEnrichment, handleCreateMissing])

  // ---- Empty / Loading states ----

  if (isAuditing) {
    return (
      <div className="text-center py-16 space-y-3">
        <Loader2 className="size-8 mx-auto animate-spin text-purple-500" />
        <p className="text-sm text-muted-foreground">Аудитор TSupport анализирует данные...</p>
        <p className="text-xs text-muted-foreground">Сверка с документами 1С по закрытым периодам</p>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="text-center py-16 space-y-2">
        <Bot className="size-8 mx-auto text-muted-foreground/50" />
        <p className="text-lg font-medium text-muted-foreground">Аудит TSupport ещё не запускался</p>
        <p className="text-sm text-muted-foreground">
          {localDone
            ? 'Нажмите «Аудит TSupport» для сверки с документами 1С'
            : 'Сначала выполните локальную нормализацию, затем запросите аудит'
          }
        </p>
        <Link to="/partner/auditor" className="inline-block mt-2">
          <Button variant="ghost" size="sm" className="gap-1.5 text-xs text-muted-foreground">
            <ExternalLink className="size-3" />
            Перейти к аудитору
          </Button>
        </Link>
      </div>
    )
  }

  // ---- Counts ----

  const pendingEnrichments = result.enrichmentProposals.filter((p) => !enrichmentStatuses[p.id] || enrichmentStatuses[p.id] === 'pending').length
  const pendingMissing = result.missingEntries.filter((m) => !missingStatuses[m.id] || missingStatuses[m.id] === 'pending').length
  const resolvedFindings = result.findings.filter((f) => findingResolutions[f.id] && findingResolutions[f.id] !== 'pending').length
  const pendingFindings = result.findings.length - resolvedFindings
  const hasPendingActions = pendingEnrichments > 0 || pendingMissing > 0

  return (
    <div className="space-y-4">
      {/* KPI Сводка */}
      <div className="flex items-center gap-4 text-sm flex-wrap">
        <div className="flex items-center gap-1.5">
          <CheckCircle className="size-4 text-green-500" />
          <span className="text-foreground font-medium">{result.totalChecked}</span>
          <span className="text-muted-foreground">проверено</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-foreground font-medium">{result.matchedCount}</span>
          <span className="text-muted-foreground">совпало</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-foreground font-medium">{result.enrichmentProposals.length}</span>
          <span className="text-muted-foreground">обогащений</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-foreground font-medium">{result.missingEntries.length}</span>
          <span className="text-muted-foreground">не найдено</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-foreground font-medium">{result.findings.length}</span>
          <span className="text-muted-foreground">находок</span>
        </div>
        {result.period && (
          <Badge variant="outline" className="text-xs">
            {result.period.from} — {result.period.to}
          </Badge>
        )}
        {hasPendingActions && (
          <Button size="sm" className="ml-auto h-7 text-xs gap-1.5" onClick={handleBulkApply}>
            <Sparkles className="size-3" />
            Применить все результаты
          </Button>
        )}
        {!hasPendingActions && (
          <Link to="/partner/auditor" className="ml-auto">
            <Button variant="ghost" size="sm" className="gap-1.5 text-xs text-muted-foreground">
              <ExternalLink className="size-3" />
              Аудитор
            </Button>
          </Link>
        )}
      </div>

      {/* 1. Проверенные записи */}
      <CollapsibleSection
        title="Проверенные записи"
        icon={ShieldCheck}
        iconBg="hsl(120 60% 45% / 0.15)"
        iconColor="text-green-500"
        count={result.verifiedEntries.length}
        defaultOpen={false}
      >
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 text-muted-foreground text-xs">
                <th className="text-left px-3 py-2 font-medium">Название</th>
                <th className="text-left px-3 py-2 font-medium">Документ 1С</th>
                <th className="text-left px-3 py-2 font-medium">Дата</th>
                <th className="text-center px-3 py-2 font-medium w-12">
                  <CheckCircle className="size-3.5 inline text-green-500" />
                </th>
              </tr>
            </thead>
            <tbody>
              {result.verifiedEntries.map((v) => (
                <tr key={v.entryId} className="border-t border-border/50">
                  <td className="px-3 py-2 text-foreground">{v.entryTitle}</td>
                  <td className="px-3 py-2 text-muted-foreground">{v.accDocNumber || '—'}</td>
                  <td className="px-3 py-2 text-muted-foreground">{v.accDocDate || '—'}</td>
                  <td className="px-3 py-2 text-center">
                    <CheckCircle className="size-3.5 inline text-green-500" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* 2. Предложения обогащения */}
      <CollapsibleSection
        title="Предложения обогащения"
        icon={Sparkles}
        iconBg="hsl(280 80% 55% / 0.15)"
        iconColor="text-purple-500"
        count={result.enrichmentProposals.length}
        badge={pendingEnrichments > 0
          ? { label: `${pendingEnrichments} ожидают`, className: 'border-purple-500 text-purple-400' }
          : undefined
        }
        defaultOpen={true}
      >
        <div className="space-y-2">
          {pendingEnrichments > 1 && (
            <div className="flex justify-end">
              <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={handleAcceptAllEnrichments}>
                <Check className="size-3" /> Принять все ({pendingEnrichments})
              </Button>
            </div>
          )}
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/50 text-muted-foreground text-xs">
                  <th className="text-left px-3 py-2 font-medium">Запись</th>
                  <th className="text-left px-3 py-2 font-medium">Поле</th>
                  <th className="text-left px-3 py-2 font-medium">Изменение</th>
                  <th className="text-left px-3 py-2 font-medium">Источник</th>
                  <th className="text-right px-3 py-2 font-medium w-40">Действие</th>
                </tr>
              </thead>
              <tbody>
                {result.enrichmentProposals.map((p) => {
                  const status = enrichmentStatuses[p.id] || 'pending'
                  return (
                    <tr key={p.id} className={`border-t border-border/50 ${status !== 'pending' ? 'opacity-60' : ''}`}>
                      <td className="px-3 py-2 text-foreground">{p.entryTitle}</td>
                      <td className="px-3 py-2 text-muted-foreground">{p.field}</td>
                      <td className="px-3 py-2">
                        {p.currentValue ? (
                          <span>
                            <span className="text-red-400 line-through">{p.currentValue}</span>
                            <span className="text-muted-foreground mx-1">&rarr;</span>
                            <span className="text-green-400">{p.proposedValue}</span>
                          </span>
                        ) : (
                          <span className="text-green-400">+ {p.proposedValue}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{p.source}</td>
                      <td className="px-3 py-2 text-right">
                        {status === 'pending' ? (
                          <div className="flex items-center gap-1 justify-end">
                            <Button size="sm" variant="outline" className="h-6 text-xs gap-1 px-2" onClick={() => handleAcceptEnrichment(p)}>
                              <Check className="size-3" /> Принять
                            </Button>
                            <Button size="sm" variant="ghost" className="h-6 text-xs px-2 text-muted-foreground" onClick={() => handleDismissEnrichment(p.id)}>
                              <X className="size-3" />
                            </Button>
                          </div>
                        ) : (
                          <Badge variant="outline" className={`text-[10px] ${status === 'applied' ? 'border-green-500 text-green-400' : 'border-muted-foreground text-muted-foreground'}`}>
                            {status === 'applied' ? 'Применено' : 'Пропущено'}
                          </Badge>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </CollapsibleSection>

      {/* 3. Соответствия CL↔1С */}
      <CollapsibleSection
        title="Соответствия CL↔1С"
        icon={Link2}
        iconBg="hsl(217 91% 60% / 0.15)"
        iconColor="text-blue-500"
        count={result.correspondences.length}
        defaultOpen={false}
      >
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 text-muted-foreground text-xs">
                <th className="text-left px-3 py-2 font-medium">CL запись</th>
                <th className="text-left px-3 py-2 font-medium">Документ 1С</th>
                <th className="text-left px-3 py-2 font-medium">Тип</th>
                <th className="text-left px-3 py-2 font-medium">Дата</th>
                <th className="text-right px-3 py-2 font-medium">Сумма 1С</th>
                <th className="text-right px-3 py-2 font-medium">Разница</th>
                <th className="text-center px-3 py-2 font-medium">Совпадение</th>
              </tr>
            </thead>
            <tbody>
              {result.correspondences.map((c) => {
                const diff = c.entryAmount != null ? c.accDocAmount - c.entryAmount : 0
                return (
                  <tr key={`${c.entryId}-${c.accDocNumber}`} className="border-t border-border/50">
                    <td className="px-3 py-2 text-foreground">{c.entryTitle}</td>
                    <td className="px-3 py-2 text-muted-foreground">{c.accDocNumber}</td>
                    <td className="px-3 py-2 text-muted-foreground">{c.accDocType}</td>
                    <td className="px-3 py-2 text-muted-foreground">{c.accDocDate}</td>
                    <td className="px-3 py-2 text-right text-foreground">{c.accDocAmount.toLocaleString('ru-RU')} ₽</td>
                    <td className={`px-3 py-2 text-right ${diff !== 0 ? 'text-yellow-500' : 'text-muted-foreground'}`}>
                      {diff !== 0 ? `${diff > 0 ? '+' : ''}${diff.toLocaleString('ru-RU')} ₽` : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${c.matchScore >= 95 ? 'border-green-500 text-green-400' : c.matchScore >= 90 ? 'border-yellow-500 text-yellow-400' : 'border-orange-500 text-orange-400'}`}
                      >
                        {c.matchScore}%
                      </Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* 4. Не найдены в CL */}
      <CollapsibleSection
        title="Не найдены в ClearLedger"
        icon={FilePlus}
        iconBg="hsl(0 84% 60% / 0.15)"
        iconColor="text-red-500"
        count={result.missingEntries.length}
        badge={pendingMissing > 0
          ? { label: `${pendingMissing} ожидают`, className: 'border-red-500 text-red-400' }
          : undefined
        }
        defaultOpen={true}
      >
        <div className="space-y-2">
          {pendingMissing > 1 && (
            <div className="flex justify-end">
              <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={handleCreateAllMissing}>
                <FilePlus className="size-3" /> Создать все ({pendingMissing})
              </Button>
            </div>
          )}
          {result.missingEntries.map((m) => {
            const status = missingStatuses[m.id] || 'pending'
            return (
              <Card key={m.id} className={status !== 'pending' ? 'opacity-60' : undefined}>
                <CardContent className="flex items-center gap-3">
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                    style={{ background: 'hsl(0 84% 60% / 0.15)' }}
                  >
                    <FilePlus className="size-3.5 text-red-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground">{m.proposedEntry.title}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {m.counterpartyName} &middot; {m.amount.toLocaleString('ru-RU')} ₽ &middot; {m.accDocType}
                    </p>
                  </div>
                  {status === 'pending' ? (
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => handleCreateMissing(m)}>
                        <FilePlus className="size-3" /> Создать запись
                      </Button>
                      <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground" onClick={() => handleDismissMissing(m.id)}>
                        <X className="size-3" />
                      </Button>
                    </div>
                  ) : (
                    <Badge variant="outline" className={`text-[10px] ${status === 'applied' ? 'border-green-500 text-green-400' : 'border-muted-foreground text-muted-foreground'}`}>
                      {status === 'applied' ? 'Создана' : 'Пропущено'}
                    </Badge>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </CollapsibleSection>

      {/* 5. Находки */}
      <CollapsibleSection
        title="Находки"
        icon={AlertTriangle}
        iconBg="hsl(45 100% 55% / 0.15)"
        iconColor="text-yellow-500"
        count={result.findings.length}
        badge={pendingFindings > 0
          ? { label: `${pendingFindings} ожидают`, className: 'border-red-500 text-red-400' }
          : resolvedFindings > 0
          ? { label: `${resolvedFindings} решено`, className: 'border-green-500 text-green-400' }
          : undefined
        }
        defaultOpen={true}
      >
        <div className="space-y-2">
          {result.findings.map((f) => (
            <AuditFindingCard
              key={f.id}
              finding={f}
              resolution={findingResolutions[f.id] || 'pending'}
              onResolve={handleResolveFinding}
            />
          ))}
        </div>
      </CollapsibleSection>

      {/* Footer */}
      {result.finishedAt && (
        <p className="text-xs text-muted-foreground">
          Завершён: {new Date(result.finishedAt).toLocaleString('ru-RU')}
        </p>
      )}
    </div>
  )
}
