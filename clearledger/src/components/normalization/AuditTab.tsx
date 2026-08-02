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
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { DisclosureSection } from '@/components/common/DisclosureSection'
import {
  Bot, Loader2, ExternalLink, CheckCircle,
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

// ---- Конфиги ----

const auditSeverityConfig = {
  critical: { icon: AlertOctagon, iconBg: 'hsl(var(--error) / 0.12)', iconColor: 'text-red-400/80' },
  warning: { icon: AlertTriangle, iconBg: 'hsl(var(--warning) / 0.12)', iconColor: 'text-amber-400/80' },
  info: { icon: Info, iconBg: 'hsl(var(--chart-1) / 0.12)', iconColor: 'text-blue-400/80' },
} as const

const resolutionConfig: Record<AuditFindingResolution, { label: string; badgeClass: string } | null> = {
  pending: null,
  accepted: { label: 'Принято', badgeClass: 'border-emerald-400/50 text-emerald-300/80' },
  corrected: { label: 'Исправлено', badgeClass: 'border-blue-400/50 text-blue-300/80' },
  dismissed: { label: 'Пропущено', badgeClass: 'border-muted-foreground text-muted-foreground' },
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
    if (!entry.proposedEntry) return  // кнопка уже disabled — страховка от программного вызова
    const { title } = entry.proposedEntry
    createEntry.mutate(entry, {
      onSuccess: () => {
        setMissingStatuses((prev) => ({ ...prev, [entry.id]: 'applied' }))
        toast.success(`Запись создана: ${title}`)
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
          <CheckCircle className="size-4 text-emerald-400/80" />
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
          <ConfirmActionDialog
            trigger={
              <Button size="sm" className="ml-auto h-7 text-xs gap-1.5">
                <Sparkles className="size-3" />
                Применить все результаты
              </Button>
            }
            title="Применить все результаты аудита?"
            description={`Будет применено обогащений: ${pendingEnrichments}, создано записей: ${pendingMissing}. Действие меняет поля записей и создаёт документы в 1С-контуре.`}
            confirmLabel="Применить"
            onConfirm={handleBulkApply}
          />
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
      <DisclosureSection
        title="Проверенные записи"
        icon={ShieldCheck}
        iconBg="hsl(var(--success) / 0.15)"
        iconColor="text-emerald-400/80"
        count={result.verifiedEntries.length}
        defaultOpen={false}
      >
        <div className="rounded-lg border overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 text-muted-foreground text-xs">
                <th className="text-left px-3 py-2 font-medium">Название</th>
                <th className="text-left px-3 py-2 font-medium">Документ 1С</th>
                <th className="text-left px-3 py-2 font-medium">Дата</th>
                <th className="text-center px-3 py-2 font-medium w-12">
                  <CheckCircle className="size-3.5 inline text-emerald-400/80" />
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
                    <CheckCircle className="size-3.5 inline text-emerald-400/80" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DisclosureSection>

      {/* 2. Предложения обогащения */}
      <DisclosureSection
        title="Предложения обогащения"
        icon={Sparkles}
        iconBg="hsl(var(--accent-purple) / 0.15)"
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
              <ConfirmActionDialog
                trigger={
                  <Button size="sm" variant="outline" className="h-7 text-xs gap-1">
                    <Check className="size-3" /> Принять все ({pendingEnrichments})
                  </Button>
                }
                title="Принять все обогащения?"
                description={`Будет применено обогащений: ${pendingEnrichments}. Значения полей записей будут перезаписаны предложенными.`}
                confirmLabel="Принять все"
                onConfirm={handleAcceptAllEnrichments}
              />
            </div>
          )}
          <div className="rounded-lg border overflow-x-auto">
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
                          <Badge variant="outline" className={`text-[10px] ${status === 'applied' ? 'border-emerald-400/50 text-emerald-300/80' : 'border-muted-foreground text-muted-foreground'}`}>
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
      </DisclosureSection>

      {/* 3. Соответствия CL↔1С */}
      <DisclosureSection
        title="Соответствия CL↔1С"
        icon={Link2}
        iconBg="hsl(var(--chart-1) / 0.15)"
        iconColor="text-blue-500"
        count={result.correspondences.length}
        defaultOpen={false}
      >
        <div className="rounded-lg border overflow-x-auto">
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
                    <td className={`px-3 py-2 text-right ${diff !== 0 ? 'text-amber-400/80' : 'text-muted-foreground'}`}>
                      {diff !== 0 ? `${diff > 0 ? '+' : ''}${diff.toLocaleString('ru-RU')} ₽` : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${c.matchScore >= 95 ? 'border-emerald-400/50 text-emerald-300/80' : c.matchScore >= 90 ? 'border-amber-400/50 text-amber-300/80' : 'border-orange-400/50 text-orange-300/80'}`}
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
      </DisclosureSection>

      {/* 4. Не найдены в CL */}
      <DisclosureSection
        title="Не найдены в TradeLedger"
        icon={FilePlus}
        iconBg="hsl(var(--error) / 0.15)"
        iconColor="text-red-400/80"
        count={result.missingEntries.length}
        badge={pendingMissing > 0
          ? { label: `${pendingMissing} ожидают`, className: 'border-red-400/50 text-red-300/80' }
          : undefined
        }
        defaultOpen={true}
      >
        <div className="space-y-2">
          {pendingMissing > 1 && (
            <div className="flex justify-end">
              <ConfirmActionDialog
                trigger={
                  <Button size="sm" variant="outline" className="h-7 text-xs gap-1">
                    <FilePlus className="size-3" /> Создать все ({pendingMissing})
                  </Button>
                }
                title="Создать все недостающие записи?"
                description={`Будет создано записей: ${pendingMissing} в 1С-контуре.`}
                confirmLabel="Создать все"
                onConfirm={handleCreateAllMissing}
              />
            </div>
          )}
          {result.missingEntries.map((m) => {
            const status = missingStatuses[m.id] || 'pending'
            return (
              <Card key={m.id} className={status !== 'pending' ? 'opacity-60' : undefined}>
                <CardContent className="flex items-center gap-3">
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                    style={{ background: 'hsl(var(--error) / 0.15)' }}
                  >
                    <FilePlus className="size-3.5 text-red-400/80" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground">
                      {m.proposedEntry?.title ?? `${m.accDocType} № ${m.accDocNumber}`}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {m.counterpartyName} &middot; {m.amount.toLocaleString('ru-RU')} ₽ &middot; {m.accDocType}
                      {!m.proposedEntry && ' · предложение не сформировано'}
                    </p>
                  </div>
                  {status === 'pending' ? (
                    <div className="flex items-center gap-1.5">
                      {/* Без предложения категория неизвестна — создавать вслепую нельзя */}
                      <Button
                        size="sm" variant="outline" className="h-7 text-xs gap-1"
                        disabled={!m.proposedEntry}
                        title={m.proposedEntry ? undefined : 'Классификатор не предложил категорию — заведите запись вручную'}
                        onClick={() => handleCreateMissing(m)}
                      >
                        <FilePlus className="size-3" /> Создать запись
                      </Button>
                      <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground" onClick={() => handleDismissMissing(m.id)}>
                        <X className="size-3" />
                      </Button>
                    </div>
                  ) : (
                    <Badge variant="outline" className={`text-[10px] ${status === 'applied' ? 'border-emerald-400/50 text-emerald-300/80' : 'border-muted-foreground text-muted-foreground'}`}>
                      {status === 'applied' ? 'Создана' : 'Пропущено'}
                    </Badge>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </DisclosureSection>

      {/* 5. Находки */}
      <DisclosureSection
        title="Находки"
        icon={AlertTriangle}
        iconBg="hsl(var(--warning) / 0.15)"
        iconColor="text-amber-400/80"
        count={result.findings.length}
        badge={pendingFindings > 0
          ? { label: `${pendingFindings} ожидают`, className: 'border-red-400/50 text-red-300/80' }
          : resolvedFindings > 0
          ? { label: `${resolvedFindings} решено`, className: 'border-emerald-400/50 text-emerald-300/80' }
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
      </DisclosureSection>

      {/* Footer */}
      {result.finishedAt && (
        <p className="text-xs text-muted-foreground">
          Завершён: {new Date(result.finishedAt).toLocaleString('ru-RU')}
        </p>
      )}
    </div>
  )
}
