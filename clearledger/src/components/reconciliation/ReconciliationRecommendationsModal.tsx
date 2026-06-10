/**
 * Модальное окно с анализом расхождений и рекомендациями
 * Разделено на две секции:
 * 1. Сверка транзакций (Corp ↔ TF) — ОСНОВНАЯ
 * 2. Сверка со сменным отчётом (TF ↔ Смена) — СПРАВОЧНО
 */

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Lightbulb,
  CreditCard,
  ArrowRightLeft,
  HelpCircle,
  Info,
  FileText
} from 'lucide-react';
import type { ReconciliationResult } from '@/types/reconciliation';

interface ReconciliationRecommendationsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  result: ReconciliationResult;
}

// Порог для "значительного" расхождения литров
const SIGNIFICANT_DIFF_LITERS = 1.0;
const DIFF_TOLERANCE = 0.1;

// Проверка расхождения Corp-TF
function hasCorpTfDiff(corp: number | null | undefined, tf: number | null | undefined): boolean {
  const diff = Math.abs((corp ?? 0) - (tf ?? 0));
  return diff > DIFF_TOLERANCE;
}

// Проверка расхождения TF-Смена
function hasShiftDiff(tf: number | null | undefined, shift: number | null | undefined): boolean {
  const diff = Math.abs((tf ?? 0) - (shift ?? 0));
  return diff > DIFF_TOLERANCE;
}

export function ReconciliationRecommendationsModal({
  open,
  onOpenChange,
  result
}: ReconciliationRecommendationsModalProps) {
  const { summary, transactions, byStation } = result;

  // Группируем транзакции по типам расхождений
  const onlyCorpTx = transactions.filter(tx => tx.status === 'only_corp');
  const onlyTfTx = transactions.filter(tx => tx.status === 'only_tf');
  const mismatchTx = transactions.filter(tx => tx.status === 'mismatch');

  // Анализ расхождений по станциям - ТОЛЬКО по Corp-TF (основная сверка)
  const stationsWithCorpTfErrors = byStation.filter(s =>
    hasCorpTfDiff(s.corpLitersTotal, s.tfLitersTotal)
  );

  // Станции с расхождением TF-Смена (информационное)
  const stationsWithShiftDiff = byStation.filter(s =>
    !hasCorpTfDiff(s.corpLitersTotal, s.tfLitersTotal) &&
    hasShiftDiff(s.tfLitersTotal, s.shiftLitersTotal)
  );

  // Уникальные карты с проблемами
  const problemCards = new Set<string>();
  onlyCorpTx.forEach(tx => problemCards.add(tx.cardNumber));
  onlyTfTx.forEach(tx => problemCards.add(tx.cardNumber));

  // Расчёт общих расхождений
  const totalCorpTfDiff = Math.abs((summary.totalCorpLiters || 0) - (summary.totalTfLiters || 0));
  const totalTfShiftDiff = Math.abs((summary.totalTfLiters || 0) - (summary.totalShiftLiters || 0));

  // Есть ли критические расхождения (Corp-TF)
  const hasTransactionErrors = summary.onlyCorp > 0 || summary.onlyTf > 0 || summary.mismatch > 0 || totalCorpTfDiff > DIFF_TOLERANCE;

  // Есть ли расхождения со сменой (информационное)
  const hasShiftDiscrepancy = totalTfShiftDiff > DIFF_TOLERANCE;

  // Определение приоритетов
  const hasCriticalIssues = summary.onlyCorp > 5 || summary.onlyTf > 5 || totalCorpTfDiff > 100;
  const hasMinorIssues = summary.mismatch > 0 && mismatchTx.every(tx =>
    Math.abs((tx.corpLiters || 0) - (tx.tfLiters || 0)) < SIGNIFICANT_DIFF_LITERS
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[95vw] max-w-2xl max-h-[90vh] sm:max-h-[85vh] bg-background border-border p-4 sm:p-6">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground text-base sm:text-lg">
            <Lightbulb className="h-4 w-4 sm:h-5 sm:w-5 text-yellow-600 dark:text-yellow-400" />
            Анализ и рекомендации
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(90vh-120px)] sm:max-h-[70vh] pr-2 sm:pr-4">
          <div className="space-y-4 sm:space-y-6">

            {/* ═══════════════════════════════════════════════════════════════ */}
            {/* СЕКЦИЯ 1: СВЕРКА ТРАНЗАКЦИЙ (Corp ↔ TF) — ОСНОВНАЯ              */}
            {/* ═══════════════════════════════════════════════════════════════ */}

            <section className="bg-card rounded-lg p-3 sm:p-4 border-l-4 border-purple-500">
              <h3 className="text-sm font-medium text-foreground mb-3 flex items-center gap-2">
                <ArrowRightLeft className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                Сверка транзакций (Corp ↔ TF)
                <span className="text-xs text-muted-foreground ml-auto">основная</span>
              </h3>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 text-sm">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                  <span className="text-foreground/80">{summary.matched} транзакций совпало</span>
                </div>

                {(summary.onlyCorp + summary.onlyTf + summary.mismatch) > 0 ? (
                  <div className="flex items-center gap-2">
                    <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                    <span className="text-red-600 dark:text-red-300">
                      {summary.onlyCorp + summary.onlyTf + summary.mismatch} расхождений
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                    <span className="text-green-600 dark:text-green-300">Нет расхождений</span>
                  </div>
                )}
              </div>

              {/* Итог по литрам Corp-TF */}
              <div className="mt-3 pt-3 border-t border-border text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Разница Corp - TF:</span>
                  <span className={totalCorpTfDiff > SIGNIFICANT_DIFF_LITERS ? 'text-red-600 dark:text-red-400 font-medium' : 'text-green-600 dark:text-green-400'}>
                    {totalCorpTfDiff > DIFF_TOLERANCE ? `Δ ${totalCorpTfDiff.toFixed(1)} л` : '✓ Совпадает'}
                  </span>
                </div>
              </div>
            </section>

            {/* Детальный анализ - Только в Corp */}
            {summary.onlyCorp > 0 && (
              <section className="bg-card rounded-lg p-3 sm:p-4">
                <h3 className="text-sm font-medium text-red-600 dark:text-red-400 mb-3 flex items-center gap-2">
                  <CreditCard className="h-4 w-4" />
                  Только в Corp: {summary.onlyCorp} транзакций
                </h3>

                <div className="space-y-2 text-sm">
                  {onlyCorpTx.slice(0, 5).map((tx, idx) => (
                    <div key={idx} className="flex flex-col sm:flex-row sm:justify-between text-foreground/80 bg-background/50 rounded px-2 py-1">
                      <span className="truncate">{tx.fuelType}: {(tx.corpLiters || 0).toFixed(1)} л</span>
                      <span className="text-muted-foreground text-xs sm:text-sm">карта ...{String(tx.cardNumber || '').slice(-4)}</span>
                    </div>
                  ))}
                  {onlyCorpTx.length > 5 && (
                    <div className="text-muted-foreground text-xs">
                      ... и ещё {onlyCorpTx.length - 5} транзакций
                    </div>
                  )}
                </div>

                <div className="mt-3 p-2 bg-purple-100 dark:bg-purple-900/30 rounded text-xs text-purple-600 dark:text-purple-300 flex items-start gap-2">
                  <HelpCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                  <div>
                    <strong>Вероятные причины:</strong>
                    <ul className="mt-1 list-disc list-inside space-y-0.5">
                      <li>Операция на другой АЗС (не в вашей сети)</li>
                      <li>Задержка синхронизации станции с TradePoint</li>
                      <li>Карта другой сети/компании</li>
                    </ul>
                  </div>
                </div>
              </section>
            )}

            {/* Детальный анализ - Только в TF */}
            {summary.onlyTf > 0 && (
              <section className="bg-card rounded-lg p-3 sm:p-4">
                <h3 className="text-sm font-medium text-primary dark:text-primary/70 mb-3 flex items-center gap-2">
                  <CreditCard className="h-4 w-4" />
                  Только в TF: {summary.onlyTf} транзакций
                </h3>

                <div className="space-y-2 text-sm">
                  {onlyTfTx.slice(0, 5).map((tx, idx) => (
                    <div key={idx} className="flex flex-col sm:flex-row sm:justify-between text-foreground/80 bg-background/50 rounded px-2 py-1">
                      <span className="truncate">{tx.fuelType}: {(tx.tfLiters || 0).toFixed(1)} л</span>
                      <span className="text-muted-foreground text-xs sm:text-sm">карта ...{String(tx.cardNumber || '').slice(-4)}</span>
                    </div>
                  ))}
                  {onlyTfTx.length > 5 && (
                    <div className="text-muted-foreground text-xs">
                      ... и ещё {onlyTfTx.length - 5} транзакций
                    </div>
                  )}
                </div>

                <div className="mt-3 p-2 bg-primary/10 dark:bg-blue-900/30 rounded text-xs text-primary dark:text-blue-300 flex items-start gap-2">
                  <HelpCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                  <div>
                    <strong>Вероятные причины:</strong>
                    <ul className="mt-1 list-disc list-inside space-y-0.5">
                      <li>Карта деактивирована в TradeCorp</li>
                      <li>Дублирование операции в TF</li>
                      <li>Ошибка POS-терминала</li>
                    </ul>
                  </div>
                </div>
              </section>
            )}

            {/* Детальный анализ - Расхождение литров */}
            {summary.mismatch > 0 && (
              <section className="bg-card rounded-lg p-3 sm:p-4">
                <h3 className="text-sm font-medium text-yellow-600 dark:text-yellow-400 mb-3 flex items-center gap-2">
                  <ArrowRightLeft className="h-4 w-4" />
                  Расхождение литров: {summary.mismatch} транзакций
                </h3>

                <div className="space-y-2 text-sm">
                  {mismatchTx.slice(0, 5).map((tx, idx) => {
                    const diff = (tx.corpLiters || 0) - (tx.tfLiters || 0);
                    const isSignificant = Math.abs(diff) >= SIGNIFICANT_DIFF_LITERS;
                    return (
                      <div key={idx} className="flex flex-col sm:flex-row sm:justify-between text-foreground/80 bg-background/50 rounded px-2 py-1.5">
                        <span className="text-xs sm:text-sm">
                          {tx.fuelType}: Corp {(tx.corpLiters || 0).toFixed(1)} vs TF {(tx.tfLiters || 0).toFixed(1)} л
                        </span>
                        <span className={`text-xs sm:text-sm font-medium ${isSignificant ? 'text-red-600 dark:text-red-400' : 'text-yellow-600 dark:text-yellow-400'}`}>
                          Δ {diff.toFixed(1)} л
                        </span>
                      </div>
                    );
                  })}
                  {mismatchTx.length > 5 && (
                    <div className="text-muted-foreground text-xs">
                      ... и ещё {mismatchTx.length - 5} транзакций
                    </div>
                  )}
                </div>

                <div className="mt-3 p-2 bg-yellow-100 dark:bg-yellow-900/30 rounded text-xs text-yellow-600 dark:text-yellow-300 flex items-start gap-2">
                  <HelpCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                  <div>
                    <strong>Вероятные причины:</strong>
                    <ul className="mt-1 list-disc list-inside space-y-0.5">
                      <li>Погрешность округления (до 0.5 л - норма)</li>
                      <li>Частичный возврат или отмена</li>
                      <li>Ошибка счётчика ТРК</li>
                    </ul>
                  </div>
                </div>
              </section>
            )}

            {/* Станции с расхождениями Corp-TF */}
            {stationsWithCorpTfErrors.length > 0 && (
              <section className="bg-card rounded-lg p-3 sm:p-4">
                <h3 className="text-sm font-medium text-orange-600 dark:text-orange-400 mb-3 flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" />
                  Станции с расхождениями транзакций: {stationsWithCorpTfErrors.length}
                </h3>

                <div className="space-y-2 text-sm">
                  {stationsWithCorpTfErrors.map((station, idx) => {
                    const corpTfDiff = (station.corpLitersTotal || 0) - (station.tfLitersTotal || 0);
                    return (
                      <div key={idx} className="flex flex-col sm:flex-row sm:justify-between text-foreground/80 bg-background/50 rounded px-2 py-1.5">
                        <span className="truncate text-xs sm:text-sm">{station.stationName}</span>
                        <span className="text-red-600 dark:text-red-400 text-xs sm:text-sm font-medium">
                          Corp-TF: {corpTfDiff > 0 ? '+' : ''}{corpTfDiff.toFixed(1)} л
                        </span>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Рекомендации по транзакциям */}
            {hasTransactionErrors && (
              <section className="bg-emerald-100 dark:bg-emerald-900/20 border border-green-800 rounded-lg p-3 sm:p-4">
                <h3 className="text-sm font-medium text-green-600 dark:text-green-400 mb-3 flex items-center gap-2">
                  <Lightbulb className="h-4 w-4" />
                  Рекомендации по транзакциям
                </h3>

                <div className="space-y-3 text-sm text-foreground/80">
                  {/* Есть только в Corp */}
                  {summary.onlyCorp > 0 && (
                    <div className="flex items-start gap-2">
                      <span className="text-purple-600 dark:text-purple-400 font-bold">1.</span>
                      <div>
                        <span className="text-purple-600 dark:text-purple-300">Проверьте принадлежность карт</span>
                        {problemCards.size > 0 && problemCards.size <= 5 && (
                          <span className="text-muted-foreground">
                            {' '}(...{Array.from(problemCards).slice(0, 3).map(c => String(c || '').slice(-4)).join(', ...')})
                          </span>
                        )}
                        <span> — возможно, операции были на другой АЗС или карты принадлежат другой сети.</span>
                      </div>
                    </div>
                  )}

                  {/* Есть только в TF */}
                  {summary.onlyTf > 0 && (
                    <div className="flex items-start gap-2">
                      <span className="text-primary dark:text-primary/70 font-bold">{summary.onlyCorp > 0 ? '2' : '1'}.</span>
                      <span>
                        Проверьте статус карт в TradeCorp. Возможно, карты деактивированы
                        или операции дублируются в TF.
                      </span>
                    </div>
                  )}

                  {/* Расхождение литров */}
                  {summary.mismatch > 0 && (
                    <div className="flex items-start gap-2">
                      <span className="text-yellow-600 dark:text-yellow-400 font-bold">
                        {(summary.onlyCorp > 0 ? 1 : 0) + (summary.onlyTf > 0 ? 1 : 0) + 1}.
                      </span>
                      <span>
                        {hasMinorIssues ? (
                          <>Расхождения литров в пределах погрешности (до {SIGNIFICANT_DIFF_LITERS} л) — можно игнорировать.</>
                        ) : (
                          <>Проверьте детали операций с расхождением литров. Обратите внимание на возвраты и отмены.</>
                        )}
                      </span>
                    </div>
                  )}

                  {/* Общая рекомендация при критических проблемах */}
                  {hasCriticalIssues && (
                    <div className="mt-3 p-2 sm:p-3 bg-red-100 dark:bg-red-900/30 border border-red-800 rounded text-red-600 dark:text-red-300 text-xs leading-relaxed">
                      <strong>Внимание:</strong> Обнаружено значительное количество расхождений.
                      Рекомендуется связаться с технической поддержкой TradeCorp для выяснения причин.
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Нет расхождений транзакций */}
            {!hasTransactionErrors && (
              <section className="bg-emerald-100 dark:bg-emerald-900/20 border border-green-800 rounded-lg p-3 sm:p-4">
                <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <CheckCircle2 className="h-5 w-5" />
                  <span className="font-medium">Все транзакции сходятся!</span>
                </div>
                <p className="text-sm text-muted-foreground mt-2">
                  Данные Corp и TF полностью совпадают. Дополнительных действий не требуется.
                </p>
              </section>
            )}

            {/* ═══════════════════════════════════════════════════════════════ */}
            {/* СЕКЦИЯ 2: СВЕРКА СО СМЕННЫМ ОТЧЁТОМ (TF ↔ Смена) — СПРАВОЧНО   */}
            {/* ═══════════════════════════════════════════════════════════════ */}

            {hasShiftDiscrepancy && (
              <section className="bg-card/50 rounded-lg p-3 sm:p-4 border-l-4 border-yellow-500">
                <h3 className="text-sm font-medium text-foreground mb-3 flex items-center gap-2">
                  <FileText className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
                  Сверка со сменным отчётом (TF ↔ Смена)
                  <span className="text-xs text-yellow-500 ml-auto">справочно</span>
                </h3>

                {/* Общее расхождение */}
                <div className="flex justify-between items-center text-sm mb-3">
                  <span className="text-muted-foreground">Разница TF - Смена:</span>
                  <span className="text-yellow-600 dark:text-yellow-400 font-medium">
                    Δ {totalTfShiftDiff.toFixed(1)} л
                  </span>
                </div>

                {/* Станции с расхождением */}
                {stationsWithShiftDiff.length > 0 && (
                  <div className="space-y-2 text-sm mb-4">
                    <div className="text-xs text-muted-foreground uppercase tracking-wide">Станции:</div>
                    {stationsWithShiftDiff.slice(0, 5).map((station, idx) => {
                      const tfShiftDiff = (station.tfLitersTotal || 0) - (station.shiftLitersTotal || 0);
                      return (
                        <div key={idx} className="flex flex-col sm:flex-row sm:justify-between text-foreground/80 bg-background/50 rounded px-2 py-1.5">
                          <div className="flex items-center gap-2">
                            <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400" />
                            <span className="truncate text-xs sm:text-sm">{station.stationName}</span>
                            <span className="text-xs text-green-500">(транзакции ✓)</span>
                          </div>
                          <span className="text-yellow-600 dark:text-yellow-400 text-xs sm:text-sm">
                            Смена: {tfShiftDiff > 0 ? '+' : ''}{tfShiftDiff.toFixed(1)} л
                          </span>
                        </div>
                      );
                    })}
                    {stationsWithShiftDiff.length > 5 && (
                      <div className="text-muted-foreground text-xs">
                        ... и ещё {stationsWithShiftDiff.length - 5} станций
                      </div>
                    )}
                  </div>
                )}

                {/* Объяснение почему может отличаться */}
                <div className="p-3 bg-yellow-100 dark:bg-yellow-900/20 border border-yellow-800/50 rounded text-xs text-yellow-700 dark:text-yellow-200">
                  <div className="flex items-start gap-2">
                    <Info className="h-4 w-4 flex-shrink-0 mt-0.5 text-yellow-600 dark:text-yellow-400" />
                    <div>
                      <strong className="text-yellow-600 dark:text-yellow-300">Почему сменный отчёт может отличаться:</strong>
                      <ul className="mt-2 space-y-1 text-yellow-700 dark:text-yellow-200/80">
                        <li>• Сменный отчёт (ПСМ) <strong>не содержит</strong> детализацию по корпоративным картам</li>
                        <li>• Операции по картам учитываются отдельно от кассовых продаж</li>
                        <li>• Данные смены получены из другого источника</li>
                        <li>• Смена ещё не закрыта или данные не загрузились</li>
                      </ul>
                      <div className="mt-3 pt-2 border-t border-yellow-800/50 text-yellow-600 dark:text-yellow-300">
                        <CheckCircle2 className="h-3 w-3 inline mr-1" />
                        Это <strong>информационное</strong> расхождение — не требует действий,
                        если сверка транзакций (Corp-TF) показывает OK.
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Если нет расхождения со сменой */}
            {!hasShiftDiscrepancy && (
              <section className="bg-card/30 rounded-lg p-3 sm:p-4 border-l-4 border-border">
                <h3 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  Сверка со сменным отчётом
                </h3>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                  <span>Данные TF и сменного отчёта совпадают</span>
                </div>
              </section>
            )}

          </div>
        </ScrollArea>

        <div className="flex justify-end pt-4 border-t border-border">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="w-full sm:w-auto bg-card border-border hover:bg-secondary"
          >
            Закрыть
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
