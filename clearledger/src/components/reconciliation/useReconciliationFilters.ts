/**
 * Хук для управления фильтрами сверки
 */

import { useState, useMemo, useCallback } from 'react';
import type {
  ReconciliationResult,
  ReconciliationTransaction,
  ReconciliationByStation
} from '@/types/reconciliation';
import { ITEMS_PER_PAGE, type FuelTotal } from './reconciliationUtils';

export interface ReconciliationFiltersState {
  stationFilter: string;
  statusFilter: string;
  fuelFilter: string;
  searchCard: string;
  currentPage: number;
  filtersOpen: boolean;
  expandedStations: Set<number>;
  expandedShifts: Set<string>;
}

export interface ReconciliationFiltersActions {
  setStationFilter: (value: string) => void;
  setStatusFilter: (value: string) => void;
  setFuelFilter: (value: string) => void;
  setSearchCard: (value: string) => void;
  setCurrentPage: (value: number) => void;
  setFiltersOpen: (value: boolean) => void;
  toggleStation: (stationId: number) => void;
  toggleShift: (key: string) => void;
  clearFilters: () => void;
}

export interface ReconciliationFiltersData {
  uniqueStations: [number, string][];
  uniqueFuels: string[];
  fuelTotals: FuelTotal[];
  stationsWithDiscrepancies: Set<number>;
  filteredTransactions: ReconciliationTransaction[];
  filteredByStation: ReconciliationByStation[];
  paginatedTransactions: ReconciliationTransaction[];
  totalPages: number;
}

export function useReconciliationFilters(result: ReconciliationResult): {
  state: ReconciliationFiltersState;
  actions: ReconciliationFiltersActions;
  data: ReconciliationFiltersData;
} {
  const { byStation, transactions } = result;

  // Состояния фильтров
  const [stationFilter, setStationFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [fuelFilter, setFuelFilter] = useState<string>('all');
  const [searchCard, setSearchCard] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [expandedStations, setExpandedStations] = useState<Set<number>>(new Set());
  const [expandedShifts, setExpandedShifts] = useState<Set<string>>(new Set());

  // Уникальные станции для фильтров
  const uniqueStations = useMemo(() => {
    const stations = new Map<number, string>();
    byStation.forEach(s => stations.set(s.stationId, s.stationName));
    return Array.from(stations.entries());
  }, [byStation]);

  // Уникальные виды топлива
  const uniqueFuels = useMemo(() => {
    const fuelsMap = new Map<string, string>();
    transactions.forEach(t => {
      const fuel = t.fuelType?.trim();
      if (fuel) {
        const key = fuel.toUpperCase();
        if (!fuelsMap.has(key)) {
          fuelsMap.set(key, fuel);
        }
      }
    });
    return Array.from(fuelsMap.values()).sort();
  }, [transactions]);

  // Агрегация по видам топлива для KPI
  const fuelTotals = useMemo(() => {
    const totals = new Map<string, { corp: number; tf: number; shift: number }>();

    byStation.forEach(station => {
      station.byFuel.forEach(fuel => {
        const key = (fuel.fuelName || 'Неизвестно').trim().toUpperCase();
        const existing = totals.get(key) || { corp: 0, tf: 0, shift: 0 };
        // || 0 защищает от NaN (в отличие от ?? 0)
        existing.corp += fuel.corpLitersTotal || 0;
        existing.tf += fuel.tfLitersTotal || 0;
        existing.shift += fuel.shiftLitersTotal || 0;
        totals.set(key, existing);
      });
    });

    return Array.from(totals.entries())
      .map(([key, data]) => ({
        name: uniqueFuels.find(f => f.toUpperCase() === key) || key,
        ...data
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [byStation, uniqueFuels]);

  // Станции с расхождениями
  const stationsWithDiscrepancies = useMemo(() => {
    return new Set(byStation.filter(s => s.status === 'error').map(s => s.stationId));
  }, [byStation]);

  // Фильтрация транзакций
  const filteredTransactions = useMemo(() => {
    return transactions.filter(tx => {
      if (stationFilter === 'discrepancies') {
        if (!stationsWithDiscrepancies.has(tx.stationId)) return false;
      } else if (stationFilter !== 'all' && tx.stationId !== parseInt(stationFilter)) {
        return false;
      }
      if (statusFilter !== 'all' && tx.status !== statusFilter) return false;
      if (fuelFilter !== 'all' && tx.fuelType?.trim().toUpperCase() !== fuelFilter.toUpperCase()) return false;
      if (searchCard && !tx.cardNumber.includes(searchCard)) return false;
      return true;
    });
  }, [transactions, stationFilter, statusFilter, fuelFilter, searchCard, stationsWithDiscrepancies]);

  // Фильтрация станций
  const filteredByStation = useMemo(() => {
    let result = byStation;

    if (stationFilter === 'discrepancies') {
      result = result.filter(s => s.status === 'error');
    } else if (stationFilter !== 'all') {
      result = result.filter(s => s.stationId === parseInt(stationFilter));
    }

    if (fuelFilter !== 'all') {
      result = result.map(station => ({
        ...station,
        byFuel: station.byFuel.filter(f =>
          f.fuelName.trim().toUpperCase() === fuelFilter.toUpperCase()
        )
      })).filter(station => station.byFuel.length > 0);
    }

    return result;
  }, [byStation, stationFilter, fuelFilter]);

  // Пагинация
  const totalPages = Math.ceil(filteredTransactions.length / ITEMS_PER_PAGE);
  const paginatedTransactions = filteredTransactions.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  // Действия
  const toggleStation = useCallback((stationId: number) => {
    setExpandedStations(prev => {
      const next = new Set(prev);
      if (next.has(stationId)) {
        next.delete(stationId);
      } else {
        next.add(stationId);
      }
      return next;
    });
  }, []);

  const toggleShift = useCallback((key: string) => {
    setExpandedShifts(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setStationFilter('all');
    setStatusFilter('all');
    setFuelFilter('all');
    setSearchCard('');
    setCurrentPage(1);
  }, []);

  return {
    state: {
      stationFilter,
      statusFilter,
      fuelFilter,
      searchCard,
      currentPage,
      filtersOpen,
      expandedStations,
      expandedShifts
    },
    actions: {
      setStationFilter,
      setStatusFilter,
      setFuelFilter,
      setSearchCard,
      setCurrentPage,
      setFiltersOpen,
      toggleStation,
      toggleShift,
      clearFilters
    },
    data: {
      uniqueStations,
      uniqueFuels,
      fuelTotals,
      stationsWithDiscrepancies,
      filteredTransactions,
      filteredByStation,
      paginatedTransactions,
      totalPages
    }
  };
}
