/**
 * Компонент результатов трёхсторонней сверки онлайн-заказов
 *
 * Структура аналогична корпоративной сверке:
 * - KPI карточки
 * - Таблица 1: По станциям → Топливо → Смены
 * - Таблица 2: Детальные транзакции (MSTO ↔ TF)
 */

import { useState, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Smartphone,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  TrendingUp,
  TrendingDown,
  Fuel,
  Building2,
  CreditCard,
  Layers,
  Droplet,
  XCircle,
  AlertCircle,
  Filter,
  Search
} from 'lucide-react';
import type {
  MSTOReconciliationResult,
  MSTOReconciliationByStation,
  MSTOReconciliationTransaction,
  MSTOReconciliationTransactionStatus
} from '@/types/mstoReconciliation';
import { formatMoney, formatVolume, round } from '@/services/mstoReconciliation';

interface MSTOReconciliationResultsProps {
  result: MSTOReconciliationResult;
  onNewReconciliation: () => void;
}

// Константы
const PAGE_SIZE = 50;
const VOLUME_TOLERANCE = 1; // литр

// Утилиты
function hasDiff(diff: number | null | undefined): boolean {
  return Math.abs(diff ?? 0) > VOLUME_TOLERANCE;
}

function formatDiff(diff: number | null | undefined): string {
  const val = diff ?? 0;
  if (Math.abs(val) < 0.01) return '0';
  return val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2);
}

function formatDateTime(isoDate: string): string {
  try {
    return new Date(isoDate).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return isoDate;
  }
}

function formatDate(isoDate: string): string {
  try {
    return new Date(isoDate).toLocaleDateString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });
  } catch {
    return isoDate;
  }
}

function getStatusColorClass(status: MSTOReconciliationTransactionStatus): string {
  switch (status) {
    case 'matched':
      return 'bg-emerald-600';
    case 'msto_wait_done':
      return 'bg-amber-600';  // Оранжевый - требует внимания
    case 'only_msto':
      return 'bg-cyan-600';
    case 'only_tf':
      return 'bg-primary';
    case 'only_shift':
      return 'bg-purple-600';
    case 'mismatch':
      return 'bg-red-600';
    default:
      return 'bg-secondary';
  }
}

function getStatusText(status: MSTOReconciliationTransactionStatus): string {
  switch (status) {
    case 'matched':
      return 'OK';
    case 'msto_wait_done':
      return 'WAIT→OK';  // MSTO показывает WAIT, но TF выполнено
    case 'only_msto':
      return 'MSTO';
    case 'only_tf':
      return 'TF';
    case 'only_shift':
      return 'Смена';
    case 'mismatch':
      return 'Δ';
    default:
      return '?';
  }
}

function StatusBadge({ status }: { status: MSTOReconciliationTransactionStatus }) {
  return (
    <Badge className={`${getStatusColorClass(status)} text-foreground text-xs`}>
      {getStatusText(status)}
    </Badge>
  );
}

export function MSTOReconciliationResults({
  result,
  onNewReconciliation
}: MSTOReconciliationResultsProps) {
  const summary = result?.summary ?? null;
  const byStation = result?.byStation ?? [];
  const transactions = result?.transactions ?? [];
  const params = result?.params;
  const executedAt = result?.executedAt;
  const duration = result?.duration;

  // Состояние раскрытия станций и топлива
  const [expandedStations, setExpandedStations] = useState<Set<number>>(new Set());
  const [expandedFuels, setExpandedFuels] = useState<Set<string>>(new Set());

  // Фильтры
  const [stationFilter, setStationFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [fuelFilter, setFuelFilter] = useState<string>('all');
  const [shiftFilter, setShiftFilter] = useState<number | null>(null);
  const [searchOrder, setSearchOrder] = useState<string>('');
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Пагинация транзакций
  const [currentPage, setCurrentPage] = useState(1);

  // Уникальные значения для фильтров
  const uniqueStations = useMemo(() => {
    return [...new Set(transactions.map(tx => tx.stationName))].sort();
  }, [transactions]);

  const uniqueFuels = useMemo(() => {
    return [...new Set(transactions.map(tx => tx.fuelType))].sort();
  }, [transactions]);

  // Фильтрация транзакций
  const filteredTransactions = useMemo(() => {
    return transactions.filter(tx => {
      // Не показываем нулевые транзакции (несостоявшиеся заказы)
      const hasData = (tx.mstoVolume ?? 0) > 0.01 || (tx.tfVolume ?? 0) > 0.01 ||
                      (tx.mstoSum ?? 0) > 1 || (tx.tfSum ?? 0) > 1;
      if (!hasData) return false;

      if (stationFilter !== 'all' && tx.stationName !== stationFilter) return false;
      if (statusFilter !== 'all' && tx.status !== statusFilter) return false;
      if (fuelFilter !== 'all' && tx.fuelType !== fuelFilter) return false;
      if (shiftFilter !== null && tx.shiftId !== shiftFilter) return false;
      if (searchOrder) {
        const search = searchOrder.toLowerCase();
        const orderMatch = tx.externalOrderId?.toLowerCase().includes(search);
        const aggMatch = tx.aggregatorName?.toLowerCase().includes(search);
        if (!orderMatch && !aggMatch) return false;
      }
      return true;
    });
  }, [transactions, stationFilter, statusFilter, fuelFilter, shiftFilter, searchOrder]);

  // Пагинация
  const totalPages = Math.ceil(filteredTransactions.length / PAGE_SIZE);
  const paginatedTransactions = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredTransactions.slice(start, start + PAGE_SIZE);
  }, [filteredTransactions, currentPage]);

  // Сброс страницы при изменении фильтров
  useMemo(() => {
    setCurrentPage(1);
  }, [stationFilter, statusFilter, fuelFilter, searchOrder]);

  // Суммы по отфильтрованным транзакциям
  const filteredTotals = useMemo(() => {
    let mstoVolume = 0;
    let tfVolume = 0;
    let mstoSum = 0;
    let tfSum = 0;
    let matchedCount = 0;
    let mismatchCount = 0;

    for (const tx of filteredTransactions) {
      mstoVolume += tx.mstoVolume || 0;
      tfVolume += tx.tfVolume || 0;
      mstoSum += tx.mstoSum || 0;
      tfSum += tx.tfSum || 0;
      if (tx.status === 'matched' || tx.status === 'msto_wait_done') {
        matchedCount++;
      } else if (tx.status === 'mismatch' || tx.status === 'only_msto' || tx.status === 'only_tf') {
        mismatchCount++;
      }
    }

    return {
      mstoVolume: round(mstoVolume),
      tfVolume: round(tfVolume),
      mstoSum: round(mstoSum),
      tfSum: round(tfSum),
      diff: round(mstoVolume - tfVolume),
      matchedCount,
      mismatchCount
    };
  }, [filteredTransactions]);

  const toggleStation = (stationId: number) => {
    setExpandedStations(prev => {
      const next = new Set(prev);
      if (next.has(stationId)) {
        next.delete(stationId);
      } else {
        next.add(stationId);
      }
      return next;
    });
  };

  const toggleFuel = (key: string) => {
    setExpandedFuels(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const clearFilters = () => {
    setStationFilter('all');
    setStatusFilter('all');
    setFuelFilter('all');
    setShiftFilter(null);
    setSearchOrder('');
  };

  // Клик по смене — фильтруем транзакции по этой смене
  const handleShiftClick = (shiftId: number, stationName: string) => {
    setShiftFilter(shiftId);
    setStationFilter(stationName);
    setStatusFilter('all');
    setFuelFilter('all');
    setSearchOrder('');
    setFiltersOpen(true);
    // Скроллим к таблице транзакций
    setTimeout(() => {
      document.getElementById('transactions-table')?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  };

  if (!result) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        Нет данных для отображения
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        Ошибка: отсутствуют данные сводки
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Заголовок */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="p-1.5 sm:p-2 rounded-lg bg-cyan-500/20">
            <Smartphone className="h-4 w-4 sm:h-5 sm:w-5 text-cyan-600 dark:text-cyan-400" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold text-foreground">Сверка онлайн-заказов</h2>
            <p className="text-xs sm:text-sm text-muted-foreground">
              <span className="hidden sm:inline">{params.dateFrom} — {params.dateTo} • </span>
              <span className="sm:hidden">{params.dateFrom}—{params.dateTo} • </span>
              {formatDate(executedAt)} • {duration}мс
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          onClick={onNewReconciliation}
          className=""
          size="sm"
        >
          <RefreshCw className="h-4 w-4 sm:mr-2" />
          <span className="hidden sm:inline">Новая сверка</span>
        </Button>
      </div>

      {/* KPI карточки */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3">
        {/* MSTO */}
        <Card className="bg-card/50 border-border">
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              <Smartphone className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-cyan-600 dark:text-cyan-400" />
              MSTO
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className="text-base sm:text-xl font-bold text-foreground">
              {formatVolume(summary.totalMstoVolume)}
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1 truncate">
              {formatMoney(summary.totalMstoSum)} • {summary.totalMstoCount || 0} тр.
            </div>
          </CardContent>
        </Card>

        {/* TF */}
        <Card className="bg-card/50 border-border">
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              <Droplet className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-primary dark:text-primary/70" />
              TF
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className="text-base sm:text-xl font-bold text-foreground">
              {formatVolume(summary.totalTfVolume || 0)}
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1 truncate">
              {formatMoney(summary.totalTfSum || 0)} • {summary.totalTfCount || 0} тр.
            </div>
          </CardContent>
        </Card>

        {/* Смена */}
        <Card className="bg-card/50 border-border">
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              <Layers className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-green-600 dark:text-green-400" />
              Смена
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className="text-base sm:text-xl font-bold text-foreground">
              {formatVolume(summary.totalShiftNonCashVolume)}
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1">
              {formatMoney(summary.totalShiftSbpRevenue)}
            </div>
          </CardContent>
        </Card>

        {/* MSTO-TF */}
        <Card className={`border ${hasDiff(summary.mstoVsTfVolumeDiff) ? 'bg-red-500/10 border-red-500/30' : 'bg-card/50 border-border'}`}>
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              {(summary.mstoVsTfVolumeDiff || 0) > 0 ? (
                <TrendingUp className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-amber-600 dark:text-amber-400" />
              ) : (
                <TrendingDown className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-red-600 dark:text-red-400" />
              )}
              MSTO-TF
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className={`text-base sm:text-xl font-bold ${hasDiff(summary.mstoVsTfVolumeDiff) ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
              {formatDiff(summary.mstoVsTfVolumeDiff)} л
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1">
              {formatMoney(summary.mstoVsTfSumDiff || 0)}
            </div>
          </CardContent>
        </Card>

        {/* TF-Смена */}
        <Card className={`border ${hasDiff(summary.tfVsShiftVolumeDiff) ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-card/50 border-border'}`}>
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              {(summary.tfVsShiftVolumeDiff || 0) > 0 ? (
                <TrendingUp className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-amber-600 dark:text-amber-400" />
              ) : (
                <TrendingDown className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-yellow-600 dark:text-yellow-400" />
              )}
              <span className="hidden sm:inline">TF-Смена</span>
              <span className="sm:hidden">TF-См</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className={`text-base sm:text-xl font-bold ${hasDiff(summary.tfVsShiftVolumeDiff) ? 'text-yellow-600 dark:text-yellow-400' : 'text-green-600 dark:text-green-400'}`}>
              {formatDiff(summary.tfVsShiftVolumeDiff)} л
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1">
              (инфо)
            </div>
          </CardContent>
        </Card>

        {/* Статус */}
        <Card className={`border col-span-2 sm:col-span-1 ${summary.hasErrors ? 'bg-red-500/10 border-red-500/30' : 'bg-emerald-500/10 border-green-500/30'}`}>
          <CardHeader className="p-3 sm:p-4 pb-1 sm:pb-2">
            <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-1.5 sm:gap-2">
              {summary.hasErrors ? (
                <AlertTriangle className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-amber-600 dark:text-amber-400" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-green-600 dark:text-green-400" />
              )}
              Статус
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 sm:p-4 pt-0">
            <div className={`text-base sm:text-lg font-bold ${summary.hasErrors ? 'text-amber-600 dark:text-amber-400' : 'text-green-600 dark:text-green-400'}`}>
              {summary.hasErrors ? 'Расхождения' : 'OK'}
            </div>
            <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1">
              ✓{summary.matched} | W{summary.mstoWaitDone || 0} | M{summary.onlyMsto} | T{summary.onlyTf || 0} | S{summary.onlyShift}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Фильтры */}
      <Card className="bg-card/50 border-border">
        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen}>
          <CollapsibleTrigger asChild>
            <CardHeader className="py-2 sm:py-3 cursor-pointer hover:bg-secondary/30">
              <CardTitle className="text-xs sm:text-sm font-medium text-muted-foreground flex items-center gap-2">
                <Filter className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                Фильтры
                {(stationFilter !== 'all' || statusFilter !== 'all' || fuelFilter !== 'all' || searchOrder) && (
                  <Badge className="bg-cyan-600 text-foreground text-[10px] sm:text-xs ml-2">активны</Badge>
                )}
                {filtersOpen ? <ChevronDown className="h-4 w-4 ml-auto" /> : <ChevronRight className="h-4 w-4 ml-auto" />}
              </CardTitle>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="pt-0 px-3 sm:px-6">
              <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-2 sm:gap-3">
                <Select value={stationFilter} onValueChange={setStationFilter}>
                  <SelectTrigger className="bg-background border-border">
                    <SelectValue placeholder="Станция" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все станции</SelectItem>
                    {uniqueStations.map(s => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger className="bg-background border-border">
                    <SelectValue placeholder="Статус" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все статусы</SelectItem>
                    <SelectItem value="matched">Совпало (OK)</SelectItem>
                    <SelectItem value="msto_wait_done">WAIT→OK (выполнено)</SelectItem>
                    <SelectItem value="only_msto">Только MSTO</SelectItem>
                    <SelectItem value="only_tf">Только TF</SelectItem>
                    <SelectItem value="only_shift">Только смена</SelectItem>
                    <SelectItem value="mismatch">Расхождение</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={fuelFilter} onValueChange={setFuelFilter}>
                  <SelectTrigger className="bg-background border-border">
                    <SelectValue placeholder="Топливо" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все топлива</SelectItem>
                    {uniqueFuels.map(f => (
                      <SelectItem key={f} value={f}>{f}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Заказ / агрегатор"
                    value={searchOrder}
                    onChange={e => setSearchOrder(e.target.value)}
                    className="bg-background border-border pl-9"
                  />
                </div>

                <Button
                  variant="outline"
                  onClick={clearFilters}
                  className="border-border"
                >
                  Сбросить
                </Button>
              </div>
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>

      {/* Таблица 1: По станциям и топливу */}
      <Card className="bg-card border-border">
        <CardHeader className="py-2 sm:py-3 px-3 sm:px-6">
          <CardTitle className="text-foreground text-xs sm:text-sm flex items-center gap-2">
            <Building2 className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            <span className="hidden sm:inline">По станциям и топливу</span>
            <span className="sm:hidden">Станции</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {/* Десктопная версия */}
          <div className="hidden md:block">
            <div className="grid grid-cols-[auto_1fr_80px_80px_80px_80px_80px_60px] gap-2 px-3 py-2 text-xs text-muted-foreground border-b border-border">
              <div className="w-4"></div>
              <div>Станция</div>
              <div className="text-right">MSTO (л)</div>
              <div className="text-right">TF (л)</div>
              <div className="text-right">Смена (л)</div>
              <div className="text-right">MSTO-TF</div>
              <div className="text-right">TF-Смена</div>
              <div className="text-center">Статус</div>
            </div>
            <div className="space-y-1 mt-1">
              {byStation.map((station) => (
                <StationRowDesktop
                  key={station.stationId}
                  station={station}
                  isExpanded={expandedStations.has(station.stationId)}
                  expandedFuels={expandedFuels}
                  onToggle={() => toggleStation(station.stationId)}
                  onToggleFuel={toggleFuel}
                  onShiftClick={(shiftId) => handleShiftClick(shiftId, station.stationName)}
                />
              ))}
            </div>
          </div>

          {/* Мобильная версия */}
          <div className="md:hidden space-y-2">
            {byStation.map((station) => (
              <StationRowMobile
                key={station.stationId}
                station={station}
                isExpanded={expandedStations.has(station.stationId)}
                onToggle={() => toggleStation(station.stationId)}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Таблица 2: Детальные транзакции */}
      <Card id="transactions-table" className="bg-card border-border">
        <CardHeader className="py-2 sm:py-3 px-3 sm:px-6">
          <div className="flex items-center justify-between mb-2">
            <CardTitle className="text-foreground text-xs sm:text-sm flex items-center gap-2">
              <CreditCard className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
              <span className="hidden sm:inline">Детальные транзакции</span>
              <span className="sm:hidden">Транзакции</span>
              {shiftFilter !== null && (
                <Badge 
                  className="bg-cyan-600 text-foreground text-[10px] cursor-pointer hover:bg-cyan-700"
                  onClick={() => setShiftFilter(null)}
                >
                  Смена #{shiftFilter} ✕
                </Badge>
              )}
            </CardTitle>
            <span className="text-muted-foreground text-[10px] sm:text-xs">
              {filteredTransactions.length} из {transactions.length}
            </span>
          </div>
          {/* Суммарные значения по фильтру */}
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 sm:gap-4 text-[10px] sm:text-xs bg-background/50 rounded-lg p-2 sm:p-3">
            <div>
              <span className="text-muted-foreground">MSTO:</span>
              <span className="text-cyan-600 dark:text-cyan-400 font-medium ml-1">{formatVolume(filteredTotals.mstoVolume)}</span>
            </div>
            <div>
              <span className="text-muted-foreground">TF:</span>
              <span className="text-primary dark:text-primary/70 font-medium ml-1">{formatVolume(filteredTotals.tfVolume)}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Δ:</span>
              <span className={`font-medium ml-1 ${Math.abs(filteredTotals.diff) > 1 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                {filteredTotals.diff > 0 ? '+' : ''}{filteredTotals.diff} л
              </span>
            </div>
            <div className="hidden sm:block">
              <span className="text-muted-foreground">MSTO ₽:</span>
              <span className="text-cyan-600 dark:text-cyan-400 font-medium ml-1">{formatMoney(filteredTotals.mstoSum)}</span>
            </div>
            <div className="hidden sm:block">
              <span className="text-muted-foreground">TF ₽:</span>
              <span className="text-primary dark:text-primary/70 font-medium ml-1">{formatMoney(filteredTotals.tfSum)}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0 px-3 sm:px-6">
          {/* Мобильная версия */}
          <div className="md:hidden space-y-2">
            {paginatedTransactions.map(tx => (
              <MobileTransactionCard key={tx.id} tx={tx} />
            ))}
          </div>

          {/* Десктопная версия */}
          <div className="hidden md:block overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border">
                  <TableHead className="text-muted-foreground">Дата/время</TableHead>
                  <TableHead className="text-muted-foreground">Станция</TableHead>
                  <TableHead className="text-muted-foreground">Топливо</TableHead>
                  <TableHead className="text-muted-foreground text-right">MSTO (л)</TableHead>
                  <TableHead className="text-muted-foreground text-right">MSTO (₽)</TableHead>
                  <TableHead className="text-muted-foreground text-right">TF (л)</TableHead>
                  <TableHead className="text-muted-foreground text-right">TF (₽)</TableHead>
                  <TableHead className="text-muted-foreground text-center">Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedTransactions.map(tx => (
                  <TableRow
                    key={tx.id}
                    className={`border-border/50 ${
                      tx.status === 'msto_wait_done' ? 'bg-amber-100 dark:bg-amber-900/10' :
                      tx.status !== 'matched' ? 'bg-red-100 dark:bg-red-900/10' : ''
                    }`}
                  >
                    <TableCell className="text-foreground/80 text-sm">
                      {formatDateTime(tx.date)}
                    </TableCell>
                    <TableCell className="text-foreground text-sm">{tx.stationName}</TableCell>
                    <TableCell className="text-foreground/80 text-sm">{tx.fuelType}</TableCell>
                    <TableCell className="text-right">
                      {tx.mstoVolume != null ? (
                        <span className="text-cyan-600 dark:text-cyan-400">{tx.mstoVolume}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {tx.mstoSum != null ? (
                        <span className="text-cyan-600 dark:text-cyan-400 text-xs">{tx.mstoSum.toFixed(0)}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {tx.tfVolume != null ? (
                        <span className="text-primary dark:text-primary/70">{tx.tfVolume}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {tx.tfSum != null ? (
                        <span className="text-primary dark:text-primary/70 text-xs">{tx.tfSum.toFixed(0)}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      <StatusBadge status={tx.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Пагинация */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-border">
              <span className="text-muted-foreground text-xs sm:text-sm">
                <span className="hidden sm:inline">Страница </span>{currentPage} из {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage === 1}
                  onClick={() => setCurrentPage(currentPage - 1)}
                  className="border-border text-foreground/80 px-2 sm:px-3"
                >
                  <ChevronLeft className="h-4 w-4 sm:mr-1" />
                  <span className="hidden sm:inline">Назад</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage === totalPages}
                  onClick={() => setCurrentPage(currentPage + 1)}
                  className="border-border text-foreground/80 px-2 sm:px-3"
                >
                  <span className="hidden sm:inline">Вперёд</span>
                  <ChevronRight className="h-4 w-4 sm:ml-1" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// Мобильная карточка транзакции
function MobileTransactionCard({ tx }: { tx: MSTOReconciliationTransaction }) {
  return (
    <div className={`p-2.5 sm:p-3 border border-border rounded-lg ${
      tx.status === 'msto_wait_done' ? 'bg-amber-100 dark:bg-amber-900/10' :
      tx.status !== 'matched' ? 'bg-red-100 dark:bg-red-900/10' : 'bg-secondary/20'
    }`}>
      <div className="flex items-center justify-between mb-1.5 sm:mb-2">
        <span className="text-muted-foreground text-[10px] sm:text-xs">{formatDateTime(tx.date)}</span>
        <StatusBadge status={tx.status} />
      </div>
      <div className="text-foreground text-xs sm:text-sm font-medium mb-1 truncate">{tx.stationName}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] sm:text-xs">
        <div>
          <span className="text-muted-foreground">Топливо:</span>
          <span className="text-foreground/80 ml-1">{tx.fuelType}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Смена:</span>
          <span className={tx.shiftId ? 'text-foreground/80 ml-1' : 'text-orange-600 dark:text-orange-400 ml-1'}>
            {tx.shiftId ? `#${tx.shiftId}` : '—'}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">MSTO:</span>
          <span className="text-cyan-600 dark:text-cyan-400 ml-1">{tx.mstoVolume ?? '—'} л</span>
          {tx.mstoSum != null && <span className="text-cyan-600 dark:text-cyan-400/70 ml-1">({tx.mstoSum.toFixed(0)}₽)</span>}
        </div>
        <div>
          <span className="text-muted-foreground">TF:</span>
          <span className="text-primary dark:text-primary/70 ml-1">{tx.tfVolume ?? '—'} л</span>
          {tx.tfSum != null && <span className="text-primary dark:text-primary/70/70 ml-1">({tx.tfSum.toFixed(0)}₽)</span>}
        </div>
      </div>
      {tx.aggregatorName && (
        <div className="mt-1.5 text-[10px] sm:text-xs truncate">
          <span className="text-muted-foreground">Агрегатор:</span>
          <span className="text-muted-foreground ml-1">{tx.aggregatorName}</span>
        </div>
      )}
    </div>
  );
}

// Мобильная строка станции
function StationRowMobile({
  station,
  isExpanded,
  onToggle
}: {
  station: MSTOReconciliationByStation;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const mstoVsTf = (station.mstoVolumeTotal ?? 0) - (station.tfVolumeTotal ?? 0);
  const tfVsShift = (station.tfVolumeTotal ?? 0) - (station.shiftNonCashVolumeTotal ?? 0);
  const hasError = hasDiff(mstoVsTf);
  const hasShiftWarn = hasDiff(tfVsShift);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div
        className={`p-2.5 sm:p-3 cursor-pointer transition-colors ${
          hasError ? 'bg-red-100 dark:bg-red-900/20' : 'bg-secondary/30'
        }`}
        onClick={onToggle}
      >
        <div className="flex items-center justify-between mb-1.5 sm:mb-2">
          <div className="flex items-center gap-1.5 sm:gap-2 min-w-0">
            {isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-muted-foreground flex-shrink-0" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-muted-foreground flex-shrink-0" />
            )}
            <span className="text-foreground font-medium text-xs sm:text-sm truncate">{station.stationName}</span>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {hasShiftWarn && !hasError && (
              <AlertCircle className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-yellow-600 dark:text-yellow-400" />
            )}
            {hasError ? (
              <XCircle className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-red-600 dark:text-red-400" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-green-600 dark:text-green-400" />
            )}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-1.5 sm:gap-2 text-[10px] sm:text-xs">
          <div>
            <span className="text-muted-foreground">MSTO:</span>
            <span className="text-cyan-600 dark:text-cyan-400 ml-0.5 sm:ml-1">{station.mstoVolumeTotal}</span>
          </div>
          <div>
            <span className="text-muted-foreground">TF:</span>
            <span className="text-primary dark:text-primary/70 ml-0.5 sm:ml-1">{station.tfVolumeTotal}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Смена:</span>
            <span className="text-green-600 dark:text-green-400 ml-0.5 sm:ml-1">{station.shiftNonCashVolumeTotal}</span>
          </div>
        </div>
        {(hasDiff(mstoVsTf) || hasDiff(tfVsShift)) && (
          <div className="flex flex-wrap gap-2 sm:gap-3 mt-1.5 sm:mt-2 text-[10px] sm:text-xs">
            {hasDiff(mstoVsTf) && (
              <span className="text-red-600 dark:text-red-400">MSTO-TF: {formatDiff(mstoVsTf)}</span>
            )}
            {hasDiff(tfVsShift) && (
              <span className="text-yellow-600 dark:text-yellow-400">TF-См: {formatDiff(tfVsShift)}</span>
            )}
          </div>
        )}
      </div>

      {isExpanded && station.byShift.length > 0 && (
        <div className="border-t border-border bg-background/30 p-1.5 sm:p-2 space-y-1.5 sm:space-y-2">
          {station.byShift.map((shift) => {
            const shiftKey = `${station.stationId}-shift-${shift.shiftId}`;
            const shiftMstoVsTf = (shift.mstoVolume ?? 0) - (shift.tfVolume ?? 0);
            const shiftHasError = hasDiff(shiftMstoVsTf);

            return (
              <div key={shiftKey} className="border border-border/50 rounded p-1.5 sm:p-2">
                <div className="flex items-center justify-between mb-0.5 sm:mb-1">
                  <span className="text-foreground/80 text-[10px] sm:text-xs">
                    #{shift.shiftId} • {shift.shiftDate}
                  </span>
                  {shiftHasError ? (
                    <XCircle className="h-3 w-3 text-red-600 dark:text-red-400" />
                  ) : (
                    <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400" />
                  )}
                </div>
                <div className="grid grid-cols-3 gap-1 text-[10px] sm:text-xs">
                  <span className="text-cyan-600 dark:text-cyan-400">{shift.mstoVolume ?? '—'}л</span>
                  <span className="text-primary dark:text-primary/70">{shift.tfVolume ?? '—'}л</span>
                  <span className="text-green-600 dark:text-green-400">{shift.shiftNonCashVolume ?? '—'}л</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Десктопная строка станции
function StationRowDesktop({
  station,
  isExpanded,
  expandedFuels,
  onToggle,
  onToggleFuel,
  onShiftClick
}: {
  station: MSTOReconciliationByStation;
  isExpanded: boolean;
  expandedFuels: Set<string>;
  onToggle: () => void;
  onToggleFuel: (key: string) => void;
  onShiftClick: (shiftId: number) => void;
}) {
  const mstoVsTf = (station.mstoVolumeTotal ?? 0) - (station.tfVolumeTotal ?? 0);
  const tfVsShift = (station.tfVolumeTotal ?? 0) - (station.shiftNonCashVolumeTotal ?? 0);
  const hasError = hasDiff(mstoVsTf);
  const hasShiftWarn = hasDiff(tfVsShift);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Заголовок станции */}
      <div
        className={`grid grid-cols-[auto_1fr_80px_80px_80px_80px_80px_60px] gap-2 items-center px-3 py-2 cursor-pointer transition-colors ${
          hasError ? 'bg-red-100 dark:bg-red-900/20 hover:bg-red-900/30' : 'bg-secondary/30 hover:bg-secondary/50'
        }`}
        onClick={onToggle}
      >
        <div className="w-4">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
        <div className="text-foreground font-medium text-sm">{station.stationName}</div>
        <div className="text-cyan-600 dark:text-cyan-400 text-sm text-right">{station.mstoVolumeTotal}</div>
        <div className="text-primary dark:text-primary/70 text-sm text-right">{station.tfVolumeTotal}</div>
        <div className="text-green-600 dark:text-green-400 text-sm text-right">{station.shiftNonCashVolumeTotal}</div>
        <div className={`text-sm text-right ${hasDiff(mstoVsTf) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
          {formatDiff(mstoVsTf)}
        </div>
        <div className={`text-sm text-right ${hasDiff(tfVsShift) ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'}`}>
          {formatDiff(tfVsShift)}
        </div>
        <div className="text-center flex items-center justify-center gap-1">
          {hasShiftWarn && !hasError && (
            <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400 inline" />
          )}
          {hasError ? (
            <XCircle className="h-4 w-4 text-red-600 dark:text-red-400 inline" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400 inline" />
          )}
        </div>
      </div>

      {/* Смены станции */}
      {isExpanded && (
        <div className="border-t border-border">
          <div className="bg-background/30 p-3 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border">
                  <TableHead className="text-muted-foreground text-xs py-1 w-8"></TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1">Смена</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1">Дата</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-right">MSTO (л)</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-right">TF (л)</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-right">Смена (л)</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-right">MSTO-TF</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-right">TF-Смена</TableHead>
                  <TableHead className="text-muted-foreground text-xs py-1 text-center">Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {station.byShift.map((shift) => {
                  const shiftKey = `${station.stationId}-shift-${shift.shiftId}`;
                  const isShiftExpanded = expandedFuels.has(shiftKey);
                  const shiftMstoVsTf = (shift.mstoVolume ?? 0) - (shift.tfVolume ?? 0);
                  const shiftTfVsShift = (shift.tfVolume ?? 0) - (shift.shiftNonCashVolume ?? 0);
                  const shiftHasError = hasDiff(shiftMstoVsTf);
                  const shiftHasWarn = hasDiff(shiftTfVsShift);

                  return (
                    <>
                      <TableRow
                        key={shiftKey}
                        className={`border-border/50 cursor-pointer hover:bg-card/50 ${
                          shiftHasError ? 'bg-red-100 dark:bg-red-900/10' : ''
                        }`}
                        onClick={() => onToggleFuel(shiftKey)}
                      >
                        <TableCell className="py-1 w-8">
                          {isShiftExpanded ? (
                            <ChevronDown className="h-3 w-3 text-muted-foreground" />
                          ) : (
                            <ChevronRight className="h-3 w-3 text-muted-foreground" />
                          )}
                        </TableCell>
                        <TableCell className="text-foreground text-xs py-1 font-medium">
                          #{shift.shiftId}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs py-1">
                          {shift.shiftDate}
                        </TableCell>
                        <TableCell className="text-cyan-600 dark:text-cyan-400 text-xs py-1 text-right">
                          {shift.mstoVolume ?? '—'}
                        </TableCell>
                        <TableCell className="text-primary dark:text-primary/70 text-xs py-1 text-right">
                          {shift.tfVolume ?? '—'}
                        </TableCell>
                        <TableCell className="text-green-600 dark:text-green-400 text-xs py-1 text-right">
                          {shift.shiftNonCashVolume ?? '—'}
                        </TableCell>
                        <TableCell className={`text-xs py-1 text-right ${hasDiff(shiftMstoVsTf) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                          {formatDiff(shiftMstoVsTf)}
                        </TableCell>
                        <TableCell className={`text-xs py-1 text-right ${hasDiff(shiftTfVsShift) ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'}`}>
                          {formatDiff(shiftTfVsShift)}
                        </TableCell>
                        <TableCell className="text-center py-1">
                          <div className="flex items-center justify-center gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-5 px-1.5 text-[10px] text-cyan-600 dark:text-cyan-400 hover:text-cyan-300 hover:bg-cyan-500/10"
                              onClick={(e) => {
                                e.stopPropagation();
                                onShiftClick(shift.shiftId);
                              }}
                            >
                              Тр.
                            </Button>
                            {shiftHasWarn && !shiftHasError && (
                              <AlertCircle className="h-3 w-3 text-yellow-600 dark:text-yellow-400 inline" />
                            )}
                            {shiftHasError ? (
                              <XCircle className="h-3 w-3 text-red-600 dark:text-red-400 inline" />
                            ) : (
                              <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400 inline" />
                            )}
                          </div>
                        </TableCell>
                      </TableRow>

                      {/* По топливу и агрегаторам в смене */}
                      {isShiftExpanded && (
                        <TableRow key={`${shiftKey}_details`}>
                          <TableCell colSpan={9} className="p-0 border-0">
                            <div className="bg-background/80 pl-8 pr-2 py-2">
                              {/* По агрегаторам */}
                              {shift.byAggregator?.length > 0 && (
                                <div className="mb-2">
                                  <div className="text-xs text-muted-foreground mb-1">По агрегаторам:</div>
                                  <div className="flex flex-wrap gap-2">
                                    {shift.byAggregator.map((agg) => (
                                      <Badge
                                        key={agg.aggregatorId}
                                        className={`${agg.status === 'ok'
                                          ? 'bg-purple-100 dark:bg-purple-500/20 text-purple-600 dark:text-purple-300 border-purple-500/30'
                                          : 'bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-300 border-red-500/30'
                                        }`}
                                      >
                                        {agg.aggregatorName}: M{agg.mstoVolume}л / T{agg.tfVolume}л
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {/* По топливу */}
                              {shift.byFuel?.length > 0 && (
                                <div>
                                  <div className="text-xs text-muted-foreground mb-1">По топливу:</div>
                                  <div className="flex flex-wrap gap-2">
                                    {shift.byFuel.map((fuel, idx) => (
                                      <Badge
                                        key={idx}
                                        className={`${fuel.status === 'ok'
                                          ? 'bg-amber-100 dark:bg-amber-500/20 text-amber-600 dark:text-amber-300 border-amber-500/30'
                                          : 'bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-300 border-red-500/30'
                                        }`}
                                      >
                                        <Fuel className="h-3 w-3 mr-1" />
                                        {fuel.fuelName}: M{fuel.mstoVolume}л / T{fuel.tfVolume}л / S{fuel.shiftVolume}л
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
