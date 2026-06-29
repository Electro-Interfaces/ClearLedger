/**
 * KPI карточки результатов сверки
 */

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CreditCard, Fuel, Clock, CheckCircle2, XCircle, Lightbulb } from 'lucide-react';
import type { ReconciliationSummary } from '@/types/reconciliation';
import { hasFuelDiscrepancy, type FuelTotal } from './reconciliationUtils';

interface ReconciliationKPICardsProps {
  summary: ReconciliationSummary;
  fuelTotals: FuelTotal[];
  onShowRecommendations?: () => void;
}

export function ReconciliationKPICards({
  summary,
  fuelTotals,
  onShowRecommendations
}: ReconciliationKPICardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Corp Card */}
      <Card className="bg-di-surface-mid border border-transparent">
        <CardContent className="p-4">
          <div className="flex items-center gap-3 mb-2">
            <CreditCard className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            <span className="text-muted-foreground text-sm">Corp</span>
          </div>
          <div className="font-headline text-2xl font-extrabold tracking-tight text-foreground">
            {(summary.totalCorpLiters || 0).toFixed(1)} л
          </div>
          <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
            {fuelTotals.map(f => {
              const hasDiscrepancy = hasFuelDiscrepancy(f.corp, f.tf, f.shift);
              return (
                <div key={`corp-${f.name}`} className={`flex justify-between ${hasDiscrepancy ? 'text-red-600 dark:text-red-400' : ''}`}>
                  <span>{f.name}:</span>
                  <span>{(f.corp || 0).toFixed(1)}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* TF Card */}
      <Card className="bg-di-surface-mid border border-transparent">
        <CardContent className="p-4">
          <div className="flex items-center gap-3 mb-2">
            <Fuel className="h-5 w-5 text-primary dark:text-primary/70" />
            <span className="text-muted-foreground text-sm">TF</span>
          </div>
          <div className="font-headline text-2xl font-extrabold tracking-tight text-foreground">
            {(summary.totalTfLiters || 0).toFixed(1)} л
          </div>
          <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
            {fuelTotals.map(f => {
              const hasDiscrepancy = hasFuelDiscrepancy(f.corp, f.tf, f.shift);
              return (
                <div key={`tf-${f.name}`} className={`flex justify-between ${hasDiscrepancy ? 'text-red-600 dark:text-red-400' : ''}`}>
                  <span>{f.name}:</span>
                  <span>{(f.tf || 0).toFixed(1)}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Shift Card */}
      <Card className="bg-di-surface-mid border border-transparent">
        <CardContent className="p-4">
          <div className="flex items-center gap-3 mb-2">
            <Clock className="h-5 w-5 text-green-600 dark:text-green-400" />
            <span className="text-muted-foreground text-sm">Смена</span>
          </div>
          <div className="font-headline text-2xl font-extrabold tracking-tight text-foreground">
            {(summary.totalShiftLiters || 0).toFixed(1)} л
          </div>
          <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
            {fuelTotals.map(f => {
              const hasDiscrepancy = hasFuelDiscrepancy(f.corp, f.tf, f.shift);
              return (
                <div key={`shift-${f.name}`} className={`flex justify-between ${hasDiscrepancy ? 'text-red-600 dark:text-red-400' : ''}`}>
                  <span>{f.name}:</span>
                  <span>{(f.shift || 0).toFixed(1)}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Status Card */}
      <Card className={`bg-di-surface-mid border ${summary.hasErrors ? 'border-red-500/30' : 'border-emerald-500/30'}`}>
        <CardContent className="p-4">
          <div className="flex items-center gap-3 mb-2">
            {summary.hasErrors ? (
              <XCircle className="h-5 w-5 text-red-600 dark:text-red-400" />
            ) : (
              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
            )}
            <span className="text-muted-foreground text-sm">Статус</span>
          </div>
          <div className={`text-2xl font-bold ${summary.hasErrors ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
            {summary.hasErrors ? 'Есть расхождения' : 'Всё сходится'}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {summary.matched} совпало, {summary.onlyCorp + summary.onlyTf + summary.mismatch} расхождений
          </div>
          {onShowRecommendations && (
            <Button
              variant="outline"
              size="sm"
              onClick={onShowRecommendations}
              className="mt-3 w-full bg-di-surface-low border-di-outline-variant/20 hover:bg-di-surface-high text-foreground"
            >
              <Lightbulb className="h-4 w-4 mr-2 text-yellow-600 dark:text-yellow-400" />
              Рекомендации
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
