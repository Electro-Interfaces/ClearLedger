/**
 * Страница "Сверка" — KPI + 3 таба: Без оригинала | Без проводки | Расхождения.
 */

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, FileQuestion, FileMinus, AlertTriangle } from 'lucide-react'
import { ReconciliationSummaryCards } from '@/components/reconciliation/ReconciliationSummary'
import { AccountingDocsTable } from '@/components/reconciliation/AccountingDocsTable'
import { MatchView } from '@/components/reconciliation/MatchView'
import {
  useAccountingDocs,
  useReconciliationSummary,
  useRunReconciliation,
  useDeleteAccountingDoc,
  useUnmatch,
} from '@/hooks/useAccountingDocs'
import { useEntries } from '@/hooks/useEntries'
import type { AccountingDoc } from '@/types'

export function ReconciliationPage() {
  const { data: summary } = useReconciliationSummary()
  const runReconciliation = useRunReconciliation()
  const [selectedDoc, setSelectedDoc] = useState<AccountingDoc | null>(null)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Сверка документов</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Сопоставление документов 1С с входящими записями ClearLedger
          </p>
        </div>
        <Button
          onClick={() => runReconciliation.mutate()}
          disabled={runReconciliation.isPending}
        >
          <RefreshCw className={`size-4 mr-2 ${runReconciliation.isPending ? 'animate-spin' : ''}`} />
          Запустить сверку
        </Button>
      </div>

      {summary && <ReconciliationSummaryCards summary={summary} />}

      <Tabs defaultValue="unmatched-1c">
        <TabsList>
          <TabsTrigger value="unmatched-1c" className="gap-1.5">
            <FileQuestion className="size-4" />
            Без оригинала
            {summary && summary.unmatchedAcc > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{summary.unmatchedAcc}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="unmatched-cl" className="gap-1.5">
            <FileMinus className="size-4" />
            Без проводки
            {summary && summary.unmatchedEntry > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{summary.unmatchedEntry}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="discrepancies" className="gap-1.5">
            <AlertTriangle className="size-4" />
            Расхождения
            {summary && summary.discrepancy > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{summary.discrepancy}</Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="unmatched-1c" className="mt-4">
          <UnmatchedAccTab onSelect={setSelectedDoc} />
        </TabsContent>
        <TabsContent value="unmatched-cl" className="mt-4">
          <UnmatchedEntryTab />
        </TabsContent>
        <TabsContent value="discrepancies" className="mt-4">
          <DiscrepanciesTab onSelect={setSelectedDoc} />
        </TabsContent>
      </Tabs>

      {selectedDoc && (
        <SelectedDocView doc={selectedDoc} onClose={() => setSelectedDoc(null)} />
      )}
    </div>
  )
}

// ---- Без оригинала (документы 1С без пары) ----

function UnmatchedAccTab({ onSelect }: { onSelect: (doc: AccountingDoc) => void }) {
  const { data = [], isLoading } = useAccountingDocs({ matchStatus: 'unmatched' })
  const { data: pending = [] } = useAccountingDocs({ matchStatus: 'pending' })
  const deleteMut = useDeleteAccountingDoc()

  if (isLoading) return <TableSkeleton />

  const all = [...data, ...pending]
  return (
    <AccountingDocsTable
      docs={all}
      onDelete={(id) => deleteMut.mutate(id)}
      onSelect={onSelect}
    />
  )
}

// ---- Без проводки (записи CL без пары в 1С) ----

function UnmatchedEntryTab() {
  const { data: allDocs = [] } = useAccountingDocs()
  const { data: entries = [] } = useEntries()

  const matchedEntryIds = new Set(
    allDocs.filter((d) => d.matchStatus === 'matched' && d.matchedEntryId).map((d) => d.matchedEntryId!),
  )
  const unmatched = entries.filter((e) => !matchedEntryIds.has(e.id))

  return (
    <div className="space-y-4">
      {unmatched.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          Все записи ClearLedger сопоставлены с документами 1С
        </div>
      ) : (
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 border-b">
                <th className="text-left p-3 font-medium">Название</th>
                <th className="text-left p-3 font-medium w-[100px]">Статус</th>
                <th className="text-left p-3 font-medium w-[100px]">Источник</th>
                <th className="text-left p-3 font-medium w-[150px]">Дата</th>
              </tr>
            </thead>
            <tbody>
              {unmatched.map((e) => (
                <tr key={e.id} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="p-3 font-medium">{e.title}</td>
                  <td className="p-3">
                    <Badge variant="outline" className="text-xs">{e.status}</Badge>
                  </td>
                  <td className="p-3 text-xs">{e.sourceLabel || e.source}</td>
                  <td className="p-3 text-xs text-muted-foreground">
                    {new Date(e.createdAt).toLocaleDateString('ru-RU')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">Записей без пары: {unmatched.length}</p>
    </div>
  )
}

// ---- Расхождения ----

function DiscrepanciesTab({ onSelect }: { onSelect: (doc: AccountingDoc) => void }) {
  const { data = [], isLoading } = useAccountingDocs({ matchStatus: 'discrepancy' })
  const unmatchMut = useUnmatch()

  if (isLoading) return <TableSkeleton />

  return (
    <AccountingDocsTable
      docs={data}
      onUnmatch={(id) => unmatchMut.mutate(id)}
      onSelect={onSelect}
    />
  )
}

// ---- Детальный просмотр ----

function SelectedDocView({ doc, onClose }: { doc: AccountingDoc; onClose: () => void }) {
  const { data: entries = [] } = useEntries()
  const unmatchMut = useUnmatch()

  const matchedEntry = doc.matchedEntryId
    ? entries.find((e) => e.id === doc.matchedEntryId)
    : undefined

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Детали документа</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>Закрыть</Button>
      </div>
      <MatchView
        doc={doc}
        entry={matchedEntry}
        onUnmatch={(doc.matchStatus === 'matched' || doc.matchStatus === 'discrepancy') ? () => { unmatchMut.mutate(doc.id); onClose() } : undefined}
      />
    </div>
  )
}

// ---- Скелетон ----

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
      ))}
    </div>
  )
}
