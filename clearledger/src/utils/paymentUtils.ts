/**
 * Утилиты для работы со способами оплаты.
 * Перенесено 1:1 из TradeFrame — единый классификатор pay_type для формы
 * сменного отчёта (Расшифровка реализации / Безналичная реализация).
 */

/** Категория способа оплаты для группировки KPI и фильтров */
export type PaymentCategory = 'cash' | 'card' | 'fuel_card' | 'corporate' | 'online' | 'coupon' | 'other';

/**
 * Единая классификация способа оплаты по названию.
 */
export function classifyPayment(paymentMethod: string): PaymentCategory {
  const name = paymentMethod.toLowerCase().trim();
  if (!name) return 'other';

  // Наличные
  if (name.includes('наличн') || name === 'cash') return 'cash';

  // Купоны / Талоны
  if (name.includes('купон') || name.includes('талон') || name === 'coupon') return 'coupon';

  // БАЛТОП, Инфорком, VIAcard — корпоративные системы
  if (name.includes('балтоп') || name.includes('инфорком') ||
      name.includes('viacard') || name.includes('виакард')) return 'corporate';

  // МобилПр. / Мобильная оплата → онлайн (ПЕРЕД общим "мобил")
  if (name.includes('мобилпр') || name.includes('мобил.пр') || name.includes('мобил.п')) return 'online';

  // Онлайн заказы
  if (name.includes('онлайн') || name.includes('online') || name === 'online_order' || name === 'qr') return 'online';
  if (name.includes('мобил')) return 'online';

  // Безнал.электрон → банковские карты (ПЕРЕД обычным безналом!)
  if (name.includes('безнал') && name.includes('электрон')) return 'card';
  // Безнал (обычный) → банковские карты
  if (name === 'безнал' || name === 'безнал.') return 'card';

  // Топливные карты (ПЕРЕД корпоративными и обычными картами!)
  if (name.includes('топливн') || name.includes('топл.') || name === 'fuel_card' ||
      name.includes('нкт') || name === 'fleet_card' || name === 'топливная_карта') return 'fuel_card';

  // Корпоративные карты / КР
  if (name === 'кр' || name.includes('корпоратив') ||
      (name.includes('корп') && name.includes('карт')) ||
      name === 'corporate_card') return 'corporate';

  // Банковские карты / Безнал с эквайрингом
  if (name.includes('карт') || name.includes('сбербанк') || name.includes('сбп') ||
      name.includes('visa') || name.includes('mastercard') || name.includes('эквайр') ||
      name.includes('банковск') ||
      name === 'bank_card' || name === 'card' || name === 'credit_card' || name === 'debit_card') return 'card';

  // Ведомость — корпоративные отпуски
  if (name.includes('ведомост')) return 'corporate';

  // Тех. отпуск в мерник
  if (name.includes('тех') && name.includes('мерник')) return 'other';

  return 'other';
}

/**
 * Проверяет, является ли способ оплаты "наличными или банковской картой".
 * Используется для разделения на «основную» и «безналичную» реализацию в отчётах.
 */
export function isCashOrCard(paymentName: string): boolean {
  const category = classifyPayment(paymentName);
  return category === 'cash' || category === 'card';
}
