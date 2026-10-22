import { expect, test } from '@playwright/test'
const state = (month: string, codes: string[] = []) => ({ period: { from: `2026-${month}-01`, to: `2026-${month}-30` }, stationCode: 'all', locationIds: [], regionIds: [], stationCodes: codes, fuelCodes: [] })
const fixture = '/e2e/ops-usability/filter-fixture.html'

test('холодный вход сохраняет период и станцию из ссылки, а не из localStorage', async ({ page }) => {
  await page.addInitScript((saved) => localStorage.setItem('gig-filters-qa-a', JSON.stringify(saved)), state('10'))
  const linked = state('09', ['QA-302'])
  await page.goto(`${fixture}?f=${encodeURIComponent(JSON.stringify(linked))}`)
  await expect(page.getByLabel('Выборка')).toHaveText(JSON.stringify(linked))
  await page.getByRole('button', { name: 'Войти в А', exact: true }).click()
  await expect(page.getByLabel('Выборка')).toHaveText(JSON.stringify(linked))
  await expect.poll(async () => new URL(page.url()).searchParams.get('f')).toBe(JSON.stringify(linked))
})

test('настоящая смена компании берёт её фильтры и не переносит чужую станцию', async ({ page }) => {
  await page.addInitScript((saved) => localStorage.setItem('gig-filters-qa-b', JSON.stringify(saved)), state('08', ['QA-B']))
  await page.goto(`${fixture}?f=${encodeURIComponent(JSON.stringify(state('09', ['QA-A'])))}`)
  await page.getByRole('button', { name: 'Войти в А', exact: true }).click()
  await page.getByRole('button', { name: 'Переключить на Б', exact: true }).click()
  await expect(page.getByLabel('Выборка')).toHaveText(JSON.stringify(state('08', ['QA-B'])))
  await expect.poll(async () => JSON.parse(new URL(page.url()).searchParams.get('f')!).stationCodes).toEqual(['QA-B'])
})

test('переход по ссылке и Back восстанавливают выборку в той же компании', async ({ page }) => {
  await page.goto(`${fixture}?f=${encodeURIComponent(JSON.stringify(state('09')))}`)
  await page.getByRole('button', { name: 'Войти в А', exact: true }).click()
  await page.getByRole('button', { name: 'Выбрать август', exact: true }).click()
  await expect.poll(async () => JSON.parse(await page.getByLabel('Выборка').innerText()).period.to).toBe('2026-08-31')
  await page.getByRole('button', { name: 'Открыть ссылку на июль', exact: true }).click()
  await expect.poll(async () => JSON.parse(await page.getByLabel('Выборка').innerText()).period.to).toBe('2026-07-31')
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect.poll(async () => JSON.parse(await page.getByLabel('Выборка').innerText()).period.to).toBe('2026-08-31')
})
