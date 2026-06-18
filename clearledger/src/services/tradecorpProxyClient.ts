/**
 * Клиент для работы с TradeCorp API через Backend Proxy ClearLedger
 *
 * Все запросы идут через backend ClearLedger на /api/tradecorp/*
 * Backend автоматически выполняет авторизацию и проксирует к TradeCorp API.
 * HTTP-слой — общий apiClient ClearLedger (BASE_URL + Bearer JWT).
 *
 * TradeCorp API - корпоративный процессинг топливных карт.
 */

import type {
  TradecorpTransaction,
  TradecorpTransactionsResponse,
  TradecorpSummaryResponse
} from '@/types/reconciliation';
import { get, post } from '@/services/apiClient';

/**
 * Получить транзакции из TradeCorp
 */
export async function getTradecorpTransactions(
  dateFrom: string,
  dateTo: string,
  stationIds?: number[]
): Promise<TradecorpTransaction[]> {
  const response = await post<TradecorpTransactionsResponse>('/api/tradecorp/transactions', {
    dateFrom,
    dateTo,
    stationIds: stationIds || []
  });

  if (!response.success) {
    throw new Error('Не удалось получить транзакции TradeCorp');
  }

  return response.transactions;
}

/**
 * Получить сводку по транзакциям TradeCorp
 */
export async function getTradecorpSummary(
  dateFrom: string,
  dateTo: string,
  stationIds?: number[]
): Promise<TradecorpSummaryResponse['summary']> {
  const response = await post<TradecorpSummaryResponse>('/api/tradecorp/transactions/summary', {
    dateFrom,
    dateTo,
    stationIds: stationIds || []
  });

  if (!response.success) {
    throw new Error('Не удалось получить сводку TradeCorp');
  }

  return response.summary;
}

/**
 * Проверить доступность TradeCorp API
 */
export async function checkTradecorpHealth(): Promise<{
  status: 'ok' | 'error';
  emitentId?: number;
  tokenValid?: boolean;
  message?: string;
}> {
  try {
    return await get<{
      status: 'ok' | 'error';
      emitentId: number;
      tokenValid: boolean;
    }>('/api/tradecorp/health');
  } catch (error) {
    return {
      status: 'error',
      message: error instanceof Error ? error.message : 'Неизвестная ошибка'
    };
  }
}
