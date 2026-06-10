/**
 * Страница «Сверки» (перенос из TradeFrame).
 *
 * Два режима:
 *  - Корп. процессинг: Corp (TradeCorp) ↔ TF (STS /v2/transactions) ↔ Смена
 *  - Онлайн-заказы:    MSTO ↔ TF ↔ Смена
 *
 * Данные:
 *  - Corp/MSTO — через backend-прокси ClearLedger (/api/tradecorp/*, /api/msto/*)
 *  - TF и смены — напрямую из STS (stsApiClient)
 */

import { useState } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Loader2, FileSearch, AlertCircle, CheckCircle2, Building2, CreditCard, Clock, ArrowRight, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { ReconciliationParamsModal } from '@/components/reconciliation/ReconciliationParamsModal';
import { ReconciliationResults } from '@/components/reconciliation/ReconciliationResults';
import { MSTOReconciliationParamsModal } from '@/components/reconciliation/MSTOReconciliationParamsModal';
import { MSTOReconciliationResults } from '@/components/reconciliation/MSTOReconciliationResults';
import { executeReconciliation } from '@/services/reconciliation';
import { executeMstoReconciliation } from '@/services/mstoReconciliation';
import { checkTradecorpHealth } from '@/services/tradecorpProxyClient';
import type { ReconciliationParams, ReconciliationResult } from '@/types/reconciliation';
import type { MSTOReconciliationParams, MSTOReconciliationResult } from '@/types/mstoReconciliation';

function ErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-300 dark:border-red-700 bg-red-100 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3">
      <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
      <div>
        <div className="font-medium">Ошибка</div>
        <div className="text-sm">{message}</div>
      </div>
    </div>
  );
}

// ─────────────────────────── Корп. процессинг ───────────────────────────

function CorpReconciliation() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState<'unknown' | 'ok' | 'error'>('unknown');

  const handleOpenModal = async () => {
    setError(null);
    const health = await checkTradecorpHealth();
    setApiStatus(health.status);
    if (health.status !== 'ok') {
      toast.error('API недоступен', {
        description: 'Не удалось подключиться к TradeCorp API. Проверьте настройки сервера.',
      });
      return;
    }
    setIsModalOpen(true);
  };

  const handleRun = async (params: ReconciliationParams) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await executeReconciliation(params);
      setResult(res);
      setIsModalOpen(false);
      if (!res.summary.hasErrors) {
        toast.success('Сверка завершена', { description: 'Все данные сходятся!' });
      } else {
        const errors = res.summary.onlyCorp + res.summary.onlyTf + res.summary.mismatch;
        toast.error('Обнаружены расхождения', { description: `Найдено ${errors} расхождений` });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Неизвестная ошибка';
      setError(msg);
      toast.error('Ошибка сверки', { description: msg });
    } finally {
      setIsLoading(false);
    }
  };

  const handleNew = () => {
    setResult(null);
    setError(null);
    void handleOpenModal();
  };

  if (result) {
    return (
      <div className="space-y-6">
        <ReconciliationResults result={result} onNewReconciliation={handleNew} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && <ErrorAlert message={error} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground">
              <FileSearch className="h-5 w-5 text-primary dark:text-primary/70" />
              Запуск сверки
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              Сверка данных по корпоративным картам между тремя источниками с 100% совпадением литров.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <CreditCard className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                  <h4 className="font-medium text-foreground text-xs">Corp</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>Процессинг</li>
                  <li>TradeCorp API</li>
                </ul>
              </div>
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <Building2 className="h-4 w-4 text-primary dark:text-primary/70" />
                  <h4 className="font-medium text-foreground text-xs">TF</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>TradePoint</li>
                  <li>/v2/transactions</li>
                </ul>
              </div>
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <Clock className="h-4 w-4 text-green-600 dark:text-green-400" />
                  <h4 className="font-medium text-foreground text-xs">Смена</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>Сменные отчёты</li>
                  <li>shift_report</li>
                </ul>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <Button
                onClick={() => void handleOpenModal()}
                size="lg"
                disabled={isLoading}
                className="bg-primary hover:bg-primary/80 text-white"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Загрузка...
                  </>
                ) : (
                  <>
                    <FileSearch className="mr-2 h-4 w-4" />
                    Начать сверку
                  </>
                )}
              </Button>

              {apiStatus === 'ok' && (
                <Badge variant="outline" className="bg-emerald-100 dark:bg-emerald-900/30 text-green-600 dark:text-green-400 border-green-300 dark:border-green-700">
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                  API доступен
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-lg text-foreground">Алгоритм сверки</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="bg-background/50 rounded-lg p-4 space-y-2 border border-border/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-purple-600/20 flex items-center justify-center text-purple-600 dark:text-purple-400 text-xs font-bold">1</div>
                <h4 className="font-medium text-foreground">Corp ↔ TF (построчно)</h4>
              </div>
              <p className="text-sm text-muted-foreground pl-8">
                Сопоставление по станции, времени (±1 мин), топливу и литрам
              </p>
            </div>
            <div className="bg-background/50 rounded-lg p-4 space-y-2 border border-border/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-primary dark:text-primary/70 text-xs font-bold">2</div>
                <h4 className="font-medium text-foreground">Суммы ↔ Смена</h4>
              </div>
              <p className="text-sm text-muted-foreground pl-8">
                Агрегация по сменам и сравнение с данными сменного отчёта
              </p>
            </div>

            <div className="flex items-center gap-2 pt-2 text-xs text-muted-foreground">
              <ArrowRight className="h-3 w-3" />
              <span>Любое расхождение по литрам = ошибка</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <ReconciliationParamsModal
        open={isModalOpen}
        onOpenChange={setIsModalOpen}
        onSubmit={handleRun}
        isLoading={isLoading}
      />
    </div>
  );
}

// ─────────────────────────── Онлайн-заказы (MSTO) ───────────────────────────

function MstoReconciliation() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<MSTOReconciliationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async (params: MSTOReconciliationParams) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await executeMstoReconciliation(params);
      setResult(res);
      setIsModalOpen(false);
      if (!res.summary.hasErrors) {
        toast.success('Сверка завершена', { description: 'Все данные сходятся!' });
      } else {
        toast.error('Обнаружены расхождения', {
          description: `Найдено ${res.summary.onlyMsto + res.summary.onlyTf + res.summary.mismatch} расхождений`,
        });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Неизвестная ошибка';
      setError(msg);
      toast.error('Ошибка сверки', { description: msg });
    } finally {
      setIsLoading(false);
    }
  };

  const handleNew = () => {
    setResult(null);
    setError(null);
    setIsModalOpen(true);
  };

  if (result) {
    return (
      <div className="space-y-6">
        <MSTOReconciliationResults result={result} onNewReconciliation={handleNew} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && <ErrorAlert message={error} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground">
              <Smartphone className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
              Запуск сверки
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              Сверка онлайн-заказов агрегаторов (MSTO) с фактом отпуска и выручкой онлайн из смен.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <Smartphone className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
                  <h4 className="font-medium text-foreground text-xs">MSTO</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>Онлайн-заказы</li>
                  <li>Яндекс, FuelUp</li>
                </ul>
              </div>
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <Building2 className="h-4 w-4 text-primary dark:text-primary/70" />
                  <h4 className="font-medium text-foreground text-xs">TF</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>TradePoint</li>
                  <li>/v2/transactions</li>
                </ul>
              </div>
              <div className="bg-background/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2 mb-1">
                  <Clock className="h-4 w-4 text-green-600 dark:text-green-400" />
                  <h4 className="font-medium text-foreground text-xs">Смена</h4>
                </div>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>Сменные отчёты</li>
                  <li>shift_report</li>
                </ul>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <Button
                onClick={() => setIsModalOpen(true)}
                size="lg"
                disabled={isLoading}
                className="bg-cyan-600 hover:bg-cyan-500 text-white"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Загрузка...
                  </>
                ) : (
                  <>
                    <Smartphone className="mr-2 h-4 w-4" />
                    Начать сверку
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-lg text-foreground">Алгоритм сверки</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="bg-background/50 rounded-lg p-4 space-y-2 border border-border/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-cyan-600/20 flex items-center justify-center text-cyan-600 dark:text-cyan-400 text-xs font-bold">1</div>
                <h4 className="font-medium text-foreground">MSTO ↔ TF (построчно)</h4>
              </div>
              <p className="text-sm text-muted-foreground pl-8">
                Сопоставление по станции, времени (±30 мин), топливу и объёму
              </p>
            </div>
            <div className="bg-background/50 rounded-lg p-4 space-y-2 border border-border/50">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-primary dark:text-primary/70 text-xs font-bold">2</div>
                <h4 className="font-medium text-foreground">Выручка ↔ Смена</h4>
              </div>
              <p className="text-sm text-muted-foreground pl-8">
                Сравнение с выручкой онлайн (СБП) из сменного отчёта
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <MSTOReconciliationParamsModal
        open={isModalOpen}
        onOpenChange={setIsModalOpen}
        onSubmit={handleRun}
        isLoading={isLoading}
      />
    </div>
  );
}

// ─────────────────────────── Страница ───────────────────────────

export function ReconciliationPage() {
  return (
    <div className="w-full px-4 md:px-6 lg:px-8 py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-primary/20">
              <FileSearch className="h-6 w-6 text-primary dark:text-primary/70" />
            </div>
            <h1 className="text-2xl font-semibold text-foreground">Сверки</h1>
          </div>
          <p className="text-muted-foreground">
            Трёхсторонняя сверка транзакций: процессинг, TradePoint, сменные отчёты
          </p>
        </div>
      </div>

      <Tabs defaultValue="corp">
        <TabsList>
          <TabsTrigger value="corp" className="gap-1.5">
            <CreditCard className="h-4 w-4" />
            Корп. процессинг
          </TabsTrigger>
          <TabsTrigger value="msto" className="gap-1.5">
            <Smartphone className="h-4 w-4" />
            Онлайн-заказы
          </TabsTrigger>
        </TabsList>
        <TabsContent value="corp" className="mt-6">
          <CorpReconciliation />
        </TabsContent>
        <TabsContent value="msto" className="mt-6">
          <MstoReconciliation />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ReconciliationPage;
