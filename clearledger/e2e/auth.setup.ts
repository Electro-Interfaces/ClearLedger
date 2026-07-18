import { test as setup, expect } from '@playwright/test'

/**
 * Одноразовый вход перед остальными тестами: сохраняет сессию в
 * e2e/.auth/admin.json, дальше её переиспользуют все проекты.
 *
 * Учётные данные берутся ТОЛЬКО из окружения — в репозиторий они не попадают.
 * На dev-стенде это те же значения, что у SEED_SUPERADMIN_EMAIL /
 * SEED_SUPERADMIN_PASSWORD в server/.env:
 *
 *   E2E_EMAIL=... E2E_PASSWORD=... npx playwright test
 */
const AUTH_FILE = 'e2e/.auth/admin.json'

setup('вход в систему', async ({ page }) => {
  const email = process.env.E2E_EMAIL
  const password = process.env.E2E_PASSWORD

  if (!email || !password) {
    throw new Error(
      'Не заданы E2E_EMAIL / E2E_PASSWORD. Значения — как SEED_SUPERADMIN_* в server/.env. ' +
      'Пример: E2E_EMAIL=... E2E_PASSWORD=... npx playwright test',
    )
  }

  await page.goto('./')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Войти' }).click()

  // Успех = форма входа исчезла. Проверять по конкретному экрану нельзя:
  // после холодного старта приложение уводит на рабочий стол (MainLayout).
  await expect(page.locator('#email')).toHaveCount(0, { timeout: 20_000 })

  await page.context().storageState({ path: AUTH_FILE })
})
