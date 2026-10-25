import { expect, test } from '@playwright/test'
import { API, кто } from './helpers'

/**
 * Отказ по лимиту входов. Проверяется последним в прогоне: он намеренно
 * расходует бюджет 10 запросов в минуту на адрес.
 */
test('L-01 отказ по лимиту входов доходит до фронта с чужого источника', async ({ request }) => {
  const u = кто('qa-cal-energy', 'colleague')
  let отказ: Awaited<ReturnType<typeof request.post>> | null = null
  for (let i = 0; i < 14 && !отказ; i++) {
    const r = await request.post(`${API}/api/auth/login`, {
      headers: { Origin: 'http://127.0.0.1:8312' },
      data: { email: u.email, password: u.password },
    })
    if (r.status() === 429) отказ = r
  }
  expect(отказ, 'лимит входов срабатывает').not.toBeNull()
  const тело = await отказ!.json()
  expect(тело.detail).toContain('Слишком много попыток')
  const заголовки = отказ!.headers()
  expect(заголовки['access-control-allow-origin'],
    'браузер с другого источника должен увидеть текст отказа, а не «Failed to fetch»')
    .toBe('http://127.0.0.1:8312')
  expect(заголовки['retry-after'], 'клиенту сказано, когда повторить').toBeTruthy()
})
