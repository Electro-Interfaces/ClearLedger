/**
 * Главный компонент результатов сверки
 *
 * Композиция из модульных компонентов:
 * - ReconciliationHeader - заголовок с кнопками
 * - ReconciliationKPICards - KPI карточки
 * - ReconciliationFilters - панель фильтров
 * - ReconciliationStationsTable - таблица станций/топлива/смен
 * - ReconciliationTransactionsTable - детальные транзакции
 * - ReconciliationRecommendationsModal - модалка с рекомендациями
 */

import { useState } from 'react';
import type { ReconciliationResult } from '@/types/reconciliation';
import { useReconciliationFilters } from './useReconciliationFilters';
import { ReconciliationHeader } from './ReconciliationHeader';
import { ReconciliationKPICards } from './ReconciliationKPICards';
import { ReconciliationFilters } from './ReconciliationFilters';
import { ReconciliationStationsTable } from './ReconciliationStationsTable';
import { ReconciliationTransactionsTable } from './ReconciliationTransactionsTable';
import { ReconciliationRecommendationsModal } from './ReconciliationRecommendationsModal';

interface ReconciliationResultsProps {
  result: ReconciliationResult;
  onNewReconciliation: () => void;
}

export function ReconciliationResults({
  result,
  onNewReconciliation
}: ReconciliationResultsProps) {
  const { summary, transactions } = result;

  // Состояние модалки рекомендаций
  const [isRecommendationsOpen, setIsRecommendationsOpen] = useState(false);

  // Хук с фильтрами и вычисляемыми данными
  const { state, actions, data } = useReconciliationFilters(result);

  return (
    <div className="space-y-6">
      {/* Заголовок */}
      <ReconciliationHeader
        result={result}
        onNewReconciliation={onNewReconciliation}
      />

      {/* KPI карточки */}
      <ReconciliationKPICards
        summary={summary}
        fuelTotals={data.fuelTotals}
        onShowRecommendations={() => setIsRecommendationsOpen(true)}
      />

      {/* Фильтры */}
      <ReconciliationFilters
        filtersOpen={state.filtersOpen}
        onFiltersOpenChange={actions.setFiltersOpen}
        stationFilter={state.stationFilter}
        onStationFilterChange={actions.setStationFilter}
        statusFilter={state.statusFilter}
        onStatusFilterChange={actions.setStatusFilter}
        fuelFilter={state.fuelFilter}
        onFuelFilterChange={actions.setFuelFilter}
        searchCard={state.searchCard}
        onSearchCardChange={actions.setSearchCard}
        onClearFilters={actions.clearFilters}
        uniqueStations={data.uniqueStations}
        uniqueFuels={data.uniqueFuels}
      />

      {/* По станциям и топливу */}
      <ReconciliationStationsTable
        filteredByStation={data.filteredByStation}
        transactions={transactions}
        expandedStations={state.expandedStations}
        expandedShifts={state.expandedShifts}
        onToggleStation={actions.toggleStation}
        onToggleShift={actions.toggleShift}
      />

      {/* Детальные транзакции */}
      <ReconciliationTransactionsTable
        paginatedTransactions={data.paginatedTransactions}
        totalTransactions={transactions.length}
        filteredCount={data.filteredTransactions.length}
        currentPage={state.currentPage}
        totalPages={data.totalPages}
        onPageChange={actions.setCurrentPage}
      />

      {/* Модалка рекомендаций */}
      <ReconciliationRecommendationsModal
        open={isRecommendationsOpen}
        onOpenChange={setIsRecommendationsOpen}
        result={result}
      />
    </div>
  );
}
