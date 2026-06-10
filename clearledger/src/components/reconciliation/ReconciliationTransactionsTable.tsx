/**
 * Таблица детальных транзакций с пагинацией
 * С мобильной оптимизацией
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { CreditCard, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReconciliationTransaction, ReconciliationTransactionStatus } from '@/types/reconciliation';
import { formatDateTime, getStatusColorClass, getStatusText } from './reconciliationUtils';

interface ReconciliationTransactionsTableProps {
  paginatedTransactions: ReconciliationTransaction[];
  totalTransactions: number;
  filteredCount: number;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

function StatusBadge({ status }: { status: ReconciliationTransactionStatus }) {
  return (
    <Badge className={`${getStatusColorClass(status)} text-foreground text-xs`}>
      {getStatusText(status)}
    </Badge>
  );
}

// Мобильная карточка транзакции
function MobileTransactionCard({ tx }: { tx: ReconciliationTransaction }) {
  return (
    <div className={`p-3 border border-border rounded-lg ${tx.status !== 'matched' ? 'bg-red-100 dark:bg-red-900/10' : 'bg-secondary/20'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-muted-foreground text-xs">{formatDateTime(tx.date)}</span>
        <StatusBadge status={tx.status} />
      </div>
      <div className="text-foreground text-sm font-medium mb-1">{tx.stationName}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
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
          <span className="text-muted-foreground">Corp:</span>
          <span className="text-purple-600 dark:text-purple-400 ml-1">{tx.corpLiters ?? '—'}</span>
        </div>
        <div>
          <span className="text-muted-foreground">TF:</span>
          <span className="text-primary dark:text-primary/70 ml-1">{tx.tfLiters ?? '—'}</span>
        </div>
      </div>
      {tx.cardNumber && (
        <div className="mt-2 text-xs">
          <span className="text-muted-foreground">Карта:</span>
          <span className="text-muted-foreground font-mono ml-1">{tx.cardNumber}</span>
        </div>
      )}
    </div>
  );
}

export function ReconciliationTransactionsTable({
  paginatedTransactions,
  totalTransactions,
  filteredCount,
  currentPage,
  totalPages,
  onPageChange
}: ReconciliationTransactionsTableProps) {
  return (
    <Card className="bg-card border-border">
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-foreground text-sm flex items-center gap-2">
            <CreditCard className="h-4 w-4" />
            <span className="hidden sm:inline">Детальные транзакции</span>
            <span className="sm:hidden">Транзакции</span>
          </CardTitle>
          <span className="text-muted-foreground text-xs">
            {filteredCount} из {totalTransactions}
          </span>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Мобильная версия - карточки */}
        <div className="md:hidden space-y-2">
          {paginatedTransactions.map(tx => (
            <MobileTransactionCard key={tx.id} tx={tx} />
          ))}
        </div>

        {/* Десктопная версия - таблица */}
        <div className="hidden md:block overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead className="text-muted-foreground">Дата/время</TableHead>
                <TableHead className="text-muted-foreground">Станция</TableHead>
                <TableHead className="text-muted-foreground">Топливо</TableHead>
                <TableHead className="text-muted-foreground">Карта</TableHead>
                <TableHead className="text-muted-foreground">Смена</TableHead>
                <TableHead className="text-muted-foreground text-right">Corp (л)</TableHead>
                <TableHead className="text-muted-foreground text-right">TF (л)</TableHead>
                <TableHead className="text-muted-foreground text-center">Статус</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedTransactions.map(tx => (
                <TableRow
                  key={tx.id}
                  className={`border-border/50 ${
                    tx.status !== 'matched' ? 'bg-red-100 dark:bg-red-900/10' : ''
                  }`}
                >
                  <TableCell className="text-foreground/80 text-sm">
                    {formatDateTime(tx.date)}
                  </TableCell>
                  <TableCell className="text-foreground text-sm">{tx.stationName}</TableCell>
                  <TableCell className="text-foreground/80 text-sm">{tx.fuelType}</TableCell>
                  <TableCell className="text-muted-foreground text-sm font-mono">
                    {tx.cardNumber || '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {tx.shiftId ? `#${tx.shiftId}` : <span className="text-orange-600 dark:text-orange-400">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {tx.corpLiters != null ? (
                      <span className="text-purple-600 dark:text-purple-400">{tx.corpLiters}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {tx.tfLiters != null ? (
                      <span className="text-primary dark:text-primary/70">{tx.tfLiters}</span>
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

        {/* Пагинация - адаптивная */}
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
                onClick={() => onPageChange(currentPage - 1)}
                className="border-border text-foreground/80 px-2 sm:px-3"
              >
                <ChevronLeft className="h-4 w-4 sm:mr-1" />
                <span className="hidden sm:inline">Назад</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={currentPage === totalPages}
                onClick={() => onPageChange(currentPage + 1)}
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
  );
}
