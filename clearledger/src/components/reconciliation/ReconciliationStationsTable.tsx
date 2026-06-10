/**
 * Таблица станций с разбивкой по топливу и сменам
 * С мобильной оптимизацией
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Building2,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertCircle
} from 'lucide-react';
import type {
  ReconciliationByStation,
  ReconciliationTransaction,
  ReconciliationTransactionStatus
} from '@/types/reconciliation';
import { formatDate, formatDateTime, formatDiff, hasDiff, hasCorpTfDiff, hasShiftDiff, getStatusColorClass, getStatusText } from './reconciliationUtils';

interface ReconciliationStationsTableProps {
  filteredByStation: ReconciliationByStation[];
  transactions: ReconciliationTransaction[];
  expandedStations: Set<number>;
  expandedShifts: Set<string>;
  onToggleStation: (stationId: number) => void;
  onToggleShift: (key: string) => void;
}

function StatusBadge({ status }: { status: ReconciliationTransactionStatus }) {
  return (
    <Badge className={`${getStatusColorClass(status)} text-foreground text-xs`}>
      {getStatusText(status)}
    </Badge>
  );
}

// Мобильная карточка станции
function MobileStationCard({
  station,
  isExpanded,
  onToggle,
  expandedShifts,
  onToggleShift
}: {
  station: ReconciliationByStation;
  isExpanded: boolean;
  onToggle: () => void;
  expandedShifts: Set<string>;
  onToggleShift: (key: string) => void;
}) {
  const stationCorpVsTf = (station.corpLitersTotal ?? 0) - (station.tfLitersTotal ?? 0);
  const stationTfVsShift = (station.tfLitersTotal ?? 0) - (station.shiftLitersTotal ?? 0);

  // Статус определяется ТОЛЬКО по Corp-TF (основная сверка транзакций)
  const hasTransactionError = hasCorpTfDiff(station.corpLitersTotal, station.tfLitersTotal);
  // Расхождение со сменой - информационное (не влияет на статус)
  const hasShiftDiscrepancy = hasShiftDiff(station.tfLitersTotal, station.shiftLitersTotal);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Заголовок станции */}
      <div
        className={`p-3 cursor-pointer transition-colors ${
          hasTransactionError ? 'bg-red-100 dark:bg-red-900/20' : 'bg-secondary/30'
        }`}
        onClick={onToggle}
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {isExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="text-foreground font-medium text-sm">{station.stationName}</span>
          </div>
          <div className="flex items-center gap-1">
            {hasShiftDiscrepancy && !hasTransactionError && (
              <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" aria-label="Расхождение со сменным отчётом" />
            )}
            {hasTransactionError ? (
              <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
            )}
          </div>
        </div>

        {/* Компактная сводка */}
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div>
            <span className="text-muted-foreground">Corp:</span>
            <span className="text-purple-600 dark:text-purple-400 ml-1">{station.corpLitersTotal}</span>
          </div>
          <div>
            <span className="text-muted-foreground">TF:</span>
            <span className="text-primary dark:text-primary/70 ml-1">{station.tfLitersTotal}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Смена:</span>
            <span className="text-green-600 dark:text-green-400 ml-1">{station.shiftLitersTotal}</span>
          </div>
        </div>

        {/* Расхождения */}
        {(hasDiff(stationCorpVsTf) || hasDiff(stationTfVsShift)) && (
          <div className="flex gap-3 mt-2 text-xs">
            {hasDiff(stationCorpVsTf) && (
              <span className="text-red-600 dark:text-red-400">Corp-TF: {formatDiff(stationCorpVsTf)}</span>
            )}
            {hasDiff(stationTfVsShift) && (
              <span className="text-yellow-600 dark:text-yellow-400">TF-Смена: {formatDiff(stationTfVsShift)} (инфо)</span>
            )}
          </div>
        )}
      </div>

      {/* Развёрнутое содержимое - топлива */}
      {isExpanded && (
        <div className="border-t border-border bg-background/30 p-2 space-y-2">
          {station.byFuel.map((fuel, fuelIdx) => {
            const fuelKey = `${station.stationId}_fuel_${fuelIdx}`;
            const corpVsTfDiff = (fuel.corpLitersTotal ?? 0) - (fuel.tfLitersTotal ?? 0);
            const tfVsShiftDiff = (fuel.tfLitersTotal ?? 0) - (fuel.shiftLitersTotal ?? 0);
            const isFuelExpanded = expandedShifts.has(fuelKey);

            // Статус топлива определяется ТОЛЬКО по Corp-TF
            const fuelHasTransactionError = hasCorpTfDiff(fuel.corpLitersTotal, fuel.tfLitersTotal);
            const fuelHasShiftDiscrepancy = hasShiftDiff(fuel.tfLitersTotal, fuel.shiftLitersTotal);

            return (
              <div key={fuelKey} className="border border-border/50 rounded">
                <div
                  className={`p-2 cursor-pointer ${fuelHasTransactionError ? 'bg-red-100 dark:bg-red-900/10' : ''}`}
                  onClick={() => onToggleShift(fuelKey)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {isFuelExpanded ? (
                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3 w-3 text-muted-foreground" />
                      )}
                      <span className="text-foreground text-xs font-medium">{fuel.fuelName}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      {fuelHasShiftDiscrepancy && !fuelHasTransactionError && (
                        <AlertCircle className="h-3 w-3 text-yellow-600 dark:text-yellow-400" />
                      )}
                      {fuelHasTransactionError ? (
                        <XCircle className="h-3 w-3 text-red-600 dark:text-red-400" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400" />
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-1 mt-1 text-xs">
                    <span className="text-purple-600 dark:text-purple-400">{fuel.corpLitersTotal ?? '—'}л</span>
                    <span className="text-primary dark:text-primary/70">{fuel.tfLitersTotal ?? '—'}л</span>
                    <span className="text-green-600 dark:text-green-400">{fuel.shiftLitersTotal ?? '—'}л</span>
                  </div>
                  {(hasDiff(corpVsTfDiff) || hasDiff(tfVsShiftDiff)) && (
                    <div className="text-xs mt-1">
                      {hasDiff(corpVsTfDiff) && <span className="text-red-600 dark:text-red-400 mr-2">Δ{formatDiff(corpVsTfDiff)}</span>}
                      {hasDiff(tfVsShiftDiff) && <span className="text-yellow-600 dark:text-yellow-400">Δ{formatDiff(tfVsShiftDiff)} (инфо)</span>}
                    </div>
                  )}
                </div>

                {/* Смены */}
                {isFuelExpanded && fuel.byShift.length > 0 && (
                  <div className="border-t border-border/50 p-2 space-y-1 bg-background/60">
                    {fuel.byShift.map((shift) => {
                      // Статус смены определяется ТОЛЬКО по Corp-TF
                      const shiftHasTransactionError = hasCorpTfDiff(shift.corpLiters, shift.tfLiters);
                      const shiftHasShiftDiscrepancy = hasShiftDiff(shift.tfLiters, shift.shiftLiters);

                      return (
                        <div key={`${station.stationId}-${fuel.fuelName}-${shift.shiftId}`} className="text-xs p-1 rounded bg-card/50">
                          <div className="flex items-center justify-between">
                            <span className="text-foreground/80">
                              {shift.shiftId === 0 ? (
                                <span className="text-orange-600 dark:text-orange-400">Без смены</span>
                              ) : (
                                `#${shift.shiftId}`
                              )}
                            </span>
                            <span className="text-muted-foreground">{formatDate(shift.shiftDate)}</span>
                          </div>
                          <div className="flex justify-between mt-0.5">
                            <div className="flex gap-2">
                              <span className="text-purple-600 dark:text-purple-400">{shift.corpLiters ?? '—'}</span>
                              <span className="text-primary dark:text-primary/70">{shift.tfLiters ?? '—'}</span>
                              <span className="text-green-600 dark:text-green-400">{shift.shiftLiters ?? '—'}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              {shiftHasShiftDiscrepancy && !shiftHasTransactionError && (
                                <AlertCircle className="h-3 w-3 text-yellow-600 dark:text-yellow-400" />
                              )}
                              {shiftHasTransactionError ? (
                                <XCircle className="h-3 w-3 text-red-600 dark:text-red-400" />
                              ) : (
                                <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400" />
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ReconciliationStationsTable({
  filteredByStation,
  transactions,
  expandedStations,
  expandedShifts,
  onToggleStation,
  onToggleShift
}: ReconciliationStationsTableProps) {
  return (
    <Card className="bg-card border-border">
      <CardHeader className="py-3">
        <CardTitle className="text-foreground text-sm flex items-center gap-2">
          <Building2 className="h-4 w-4" />
          По станциям и топливу
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Мобильная версия - карточки */}
        <div className="md:hidden space-y-2">
          {filteredByStation.map((station, stationIndex) => (
            <MobileStationCard
              key={`mobile_station_${station.stationId}_${stationIndex}`}
              station={station}
              isExpanded={expandedStations.has(station.stationId)}
              onToggle={() => onToggleStation(station.stationId)}
              expandedShifts={expandedShifts}
              onToggleShift={onToggleShift}
            />
          ))}
        </div>

        {/* Десктопная версия - таблица */}
        <div className="hidden md:block">
          {/* Заголовок таблицы станций */}
          <div className="grid grid-cols-[auto_1fr_80px_80px_80px_80px_80px_60px] gap-2 px-3 py-2 text-xs text-muted-foreground border-b border-border">
            <div className="w-4"></div>
            <div>Станция</div>
            <div className="text-right">Corp (л)</div>
            <div className="text-right">TF (л)</div>
            <div className="text-right">Смена (л)</div>
            <div className="text-right">Corp-TF</div>
            <div className="text-right">TF-Смена</div>
            <div className="text-center">Статус</div>
          </div>
          <div className="space-y-1 mt-1">
            {filteredByStation.map((station, stationIndex) => {
              const stationCorpVsTf = (station.corpLitersTotal ?? 0) - (station.tfLitersTotal ?? 0);
              const stationTfVsShift = (station.tfLitersTotal ?? 0) - (station.shiftLitersTotal ?? 0);

              // Статус определяется ТОЛЬКО по Corp-TF (основная сверка транзакций)
              const stationHasTransactionError = hasCorpTfDiff(station.corpLitersTotal, station.tfLitersTotal);
              const stationHasShiftDiscrepancy = hasShiftDiff(station.tfLitersTotal, station.shiftLitersTotal);

              return (
                <div key={`station_${station.stationId}_${stationIndex}`} className="border border-border rounded-lg overflow-hidden">
                  {/* Заголовок станции */}
                  <div
                    className={`grid grid-cols-[auto_1fr_80px_80px_80px_80px_80px_60px] gap-2 items-center px-3 py-2 cursor-pointer transition-colors ${
                      stationHasTransactionError ? 'bg-red-100 dark:bg-red-900/20 hover:bg-red-900/30' : 'bg-secondary/30 hover:bg-secondary/50'
                    }`}
                    onClick={() => onToggleStation(station.stationId)}
                  >
                    <div className="w-4">
                      {expandedStations.has(station.stationId) ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                    <div className="text-foreground font-medium text-sm">{station.stationName}</div>
                    <div className="text-purple-600 dark:text-purple-400 text-sm text-right">{station.corpLitersTotal}</div>
                    <div className="text-primary dark:text-primary/70 text-sm text-right">{station.tfLitersTotal}</div>
                    <div className="text-green-600 dark:text-green-400 text-sm text-right">{station.shiftLitersTotal}</div>
                    <div className={`text-sm text-right ${hasDiff(stationCorpVsTf) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                      {formatDiff(stationCorpVsTf)}
                    </div>
                    <div className={`text-sm text-right ${hasDiff(stationTfVsShift) ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'}`}>
                      {formatDiff(stationTfVsShift)}
                    </div>
                    <div className="text-center flex items-center justify-center gap-1">
                      {stationHasShiftDiscrepancy && !stationHasTransactionError && (
                        <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400 inline" aria-label="Расхождение со сменным отчётом" />
                      )}
                      {stationHasTransactionError ? (
                        <XCircle className="h-4 w-4 text-red-600 dark:text-red-400 inline" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400 inline" />
                      )}
                    </div>
                  </div>

                  {/* Топлива станции */}
                  {expandedStations.has(station.stationId) && (
                    <div className="border-t border-border">
                      <div className="bg-background/30 p-3 overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow className="border-border">
                              <TableHead className="text-muted-foreground text-xs py-1 w-8"></TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1">Топливо</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-right">Corp (л)</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-right">TF (л)</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-right">Смена (л)</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-right">Corp-TF</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-right">TF-Смена</TableHead>
                              <TableHead className="text-muted-foreground text-xs py-1 text-center">Статус</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {station.byFuel.map((fuel, fuelIdx) => {
                              const fuelKey = `${station.stationId}_fuel_${fuelIdx}`;
                              const corpVsTfDiff = (fuel.corpLitersTotal ?? 0) - (fuel.tfLitersTotal ?? 0);
                              const tfVsShiftDiff = (fuel.tfLitersTotal ?? 0) - (fuel.shiftLitersTotal ?? 0);

                              // Статус топлива определяется ТОЛЬКО по Corp-TF
                              const fuelHasTransactionError = hasCorpTfDiff(fuel.corpLitersTotal, fuel.tfLitersTotal);
                              const fuelHasShiftDiscrepancy = hasShiftDiff(fuel.tfLitersTotal, fuel.shiftLitersTotal);

                              return (
                                <>
                                  <TableRow
                                    key={fuelKey}
                                    className={`border-border/50 cursor-pointer hover:bg-card/50 ${
                                      fuelHasTransactionError ? 'bg-red-100 dark:bg-red-900/10' : ''
                                    }`}
                                    onClick={() => onToggleShift(fuelKey)}
                                  >
                                    <TableCell className="py-1 w-8">
                                      {expandedShifts.has(fuelKey) ? (
                                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                      ) : (
                                        <ChevronRight className="h-3 w-3 text-muted-foreground" />
                                      )}
                                    </TableCell>
                                    <TableCell className="text-foreground text-xs py-1 font-medium">{fuel.fuelName}</TableCell>
                                    <TableCell className="text-purple-600 dark:text-purple-400 text-xs py-1 text-right">{fuel.corpLitersTotal ?? '—'}</TableCell>
                                    <TableCell className="text-primary dark:text-primary/70 text-xs py-1 text-right">{fuel.tfLitersTotal ?? '—'}</TableCell>
                                    <TableCell className="text-green-600 dark:text-green-400 text-xs py-1 text-right">{fuel.shiftLitersTotal ?? '—'}</TableCell>
                                    <TableCell className={`text-xs py-1 text-right ${hasDiff(corpVsTfDiff) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                                      {formatDiff(corpVsTfDiff)}
                                    </TableCell>
                                    <TableCell className={`text-xs py-1 text-right ${hasDiff(tfVsShiftDiff) ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'}`}>
                                      {formatDiff(tfVsShiftDiff)}
                                    </TableCell>
                                    <TableCell className="text-center py-1">
                                      <div className="flex items-center justify-center gap-1">
                                        {fuelHasShiftDiscrepancy && !fuelHasTransactionError && (
                                          <AlertCircle className="h-3 w-3 text-yellow-600 dark:text-yellow-400 inline" />
                                        )}
                                        {fuelHasTransactionError ? (
                                          <XCircle className="h-3 w-3 text-red-600 dark:text-red-400 inline" />
                                        ) : (
                                          <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400 inline" />
                                        )}
                                      </div>
                                    </TableCell>
                                  </TableRow>

                                  {/* Смены для этого топлива */}
                                  {expandedShifts.has(fuelKey) && fuel.byShift.length > 0 && (
                                    <TableRow key={`${fuelKey}_shifts`}>
                                      <TableCell colSpan={8} className="p-0 border-0">
                                        <div className="bg-background/80 pl-8 pr-2 py-2 overflow-x-auto">
                                          <Table>
                                            <TableHeader>
                                              <TableRow className="border-border/50">
                                                <TableHead className="text-muted-foreground text-xs py-1">Смена</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1">Дата</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1">Время</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-right">Corp</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-right">TF</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-right">Смена</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-right">Corp-TF</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-right">TF-Смена</TableHead>
                                                <TableHead className="text-muted-foreground text-xs py-1 text-center">Статус</TableHead>
                                              </TableRow>
                                            </TableHeader>
                                            <TableBody>
                                              {fuel.byShift.map((shift) => {
                                                const shiftCorpVsTf = (shift.corpLiters ?? 0) - (shift.tfLiters ?? 0);
                                                const shiftTfVsShift = (shift.tfLiters ?? 0) - (shift.shiftLiters ?? 0);
                                                const shiftKey = `${station.stationId}-${fuel.fuelName}-${shift.shiftId}`;

                                                // Статус смены определяется ТОЛЬКО по Corp-TF
                                                const shiftHasTransactionError = hasCorpTfDiff(shift.corpLiters, shift.tfLiters);
                                                const shiftHasShiftDiscrepancy = hasShiftDiff(shift.tfLiters, shift.shiftLiters);

                                                return (
                                                  <TableRow key={shiftKey} className="border-border/30">
                                                    <TableCell className="text-foreground/80 text-xs py-1">
                                                      {shift.shiftId === 0 ? (
                                                        <span className="text-orange-600 dark:text-orange-400">Без смены</span>
                                                      ) : (
                                                        `#${shift.shiftId}`
                                                      )}
                                                    </TableCell>
                                                    <TableCell className="text-muted-foreground text-xs py-1">{formatDate(shift.shiftDate)}</TableCell>
                                                    <TableCell className="text-muted-foreground text-xs py-1">
                                                      {shift.shiftOpenedAt && shift.shiftClosedAt ? (
                                                        `${shift.shiftOpenedAt.substring(11, 16)}—${shift.shiftClosedAt.substring(11, 16)}`
                                                      ) : shift.shiftId === 0 ? '—' : 'открыта'}
                                                    </TableCell>
                                                    <TableCell className="text-purple-600 dark:text-purple-400 text-xs py-1 text-right">{shift.corpLiters ?? '—'}</TableCell>
                                                    <TableCell className="text-primary dark:text-primary/70 text-xs py-1 text-right">{shift.tfLiters ?? '—'}</TableCell>
                                                    <TableCell className="text-green-600 dark:text-green-400 text-xs py-1 text-right">{shift.shiftLiters ?? '—'}</TableCell>
                                                    <TableCell className={`text-xs py-1 text-right ${hasDiff(shiftCorpVsTf) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                                                      {formatDiff(shiftCorpVsTf)}
                                                    </TableCell>
                                                    <TableCell className={`text-xs py-1 text-right ${hasDiff(shiftTfVsShift) ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'}`}>
                                                      {formatDiff(shiftTfVsShift)}
                                                    </TableCell>
                                                    <TableCell className="text-center py-1">
                                                      <div className="flex items-center justify-center gap-1">
                                                        {shiftHasShiftDiscrepancy && !shiftHasTransactionError && (
                                                          <AlertCircle className="h-3 w-3 text-yellow-600 dark:text-yellow-400 inline" />
                                                        )}
                                                        {shiftHasTransactionError ? (
                                                          <XCircle className="h-3 w-3 text-red-600 dark:text-red-400 inline" />
                                                        ) : (
                                                          <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400 inline" />
                                                        )}
                                                      </div>
                                                    </TableCell>
                                                  </TableRow>
                                                );
                                              })}
                                            </TableBody>
                                          </Table>

                                          {/* Транзакции без смены */}
                                          {fuel.byShift.some(s => s.shiftId === 0) && (
                                            <div className="mt-2 pt-2 border-t border-border/50">
                                              <div className="text-xs text-muted-foreground mb-1">Транзакции без привязки к смене:</div>
                                              {transactions
                                                .filter(tx => tx.stationId === station.stationId && tx.shiftId === null && tx.fuelType === fuel.fuelName)
                                                .map(tx => (
                                                  <div key={tx.id} className="flex items-center gap-4 text-xs py-0.5">
                                                    <span className="text-muted-foreground w-24">{formatDateTime(tx.date)}</span>
                                                    <span className="text-muted-foreground font-mono w-32 truncate">{tx.cardNumber || '—'}</span>
                                                    <span className="text-purple-600 dark:text-purple-400 w-16 text-right">{tx.corpLiters ?? '—'}</span>
                                                    <span className="text-primary dark:text-primary/70 w-16 text-right">{tx.tfLiters ?? '—'}</span>
                                                    <StatusBadge status={tx.status} />
                                                  </div>
                                                ))}
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
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
