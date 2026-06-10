/**
 * Заголовок результатов сверки
 */

import { Button } from '@/components/ui/button';
import { FileSearch, Download, RefreshCw } from 'lucide-react';
import type { ReconciliationResult } from '@/types/reconciliation';
import { exportReconciliationToExcel } from '@/utils/reconciliationExport';
import { toast } from 'sonner';
import { formatDate } from './reconciliationUtils';

interface ReconciliationHeaderProps {
  result: ReconciliationResult;
  onNewReconciliation: () => void;
}

export function ReconciliationHeader({
  result,
  onNewReconciliation
}: ReconciliationHeaderProps) {
  const { params } = result;

  const handleExport = async () => {
    try {
      await exportReconciliationToExcel(result);
    } catch {
      toast.error('Ошибка экспорта', {
        description: 'Не удалось сформировать Excel-файл сверки',
      });
    }
  };

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-primary/20 shrink-0">
          <FileSearch className="h-5 w-5 sm:h-6 sm:w-6 text-primary dark:text-primary/70" />
        </div>
        <div>
          <h1 className="text-lg sm:text-2xl font-semibold text-foreground">Результаты сверки</h1>
          <p className="text-muted-foreground text-xs sm:text-sm">
            {formatDate(params.dateFrom)} — {formatDate(params.dateTo)}
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => { void handleExport(); }}
          className="border-border text-foreground/80 hover:bg-secondary flex-1 sm:flex-none"
        >
          <Download className="h-4 w-4 sm:mr-2" />
          <span className="hidden sm:inline">Экспорт Excel</span>
        </Button>
        <Button
          onClick={onNewReconciliation}
          size="sm"
          className="bg-primary hover:bg-primary/80 flex-1 sm:flex-none"
        >
          <RefreshCw className="h-4 w-4 sm:mr-2" />
          <span className="hidden sm:inline">Новая сверка</span>
        </Button>
      </div>
    </div>
  );
}
