/**
 * Снимки для справки по «Поддержке».
 *
 * Снимается ДЕМО-контур стека `demo`: вымышленные компании («Меридиан-Сервис»,
 * «Вектор-Снаб», «Стройизоляция», «Северэнерго», «Аквилон»), вымышленные люди и
 * заведённые для показа заявки. На витрине `desk` контур ведёт реальные
 * обращения клиентов, поэтому справку по нему не снимают.
 *
 * Стенд наружу закрыт, поэтому прогон ходит через SSH-туннель:
 *   ssh -J ns1-jump -N -L 8099:<demo-nginx>:80 root@<ВМ>
 *   TRACK_BASE=http://localhost:8099 TRACK_TOKEN=… npx playwright test \
 *     -c e2e/track.config.ts e2e/info-support-shots.spec.ts
 *
 * Вход в «Поддержку» - handoff-токеном Ядра: прямой заход на /support/ приводит
 * на форму логина, потому что у приложения своя сессия.
 */
import { test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const БАЗА = process.env.TRACK_BASE ?? 'http://localhost:8099'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const ПАПКА = process.env.HELP_SHOTS ?? 'public/help/support'
// Компания демо-контура, у которой заведены заявки («Стройизоляция»).
const СЕТЬ = process.env.TRACK_NETWORK ?? 'c0000000-0000-0000-0000-000000000001'

const снято: string[] = []
const пропущено: string[] = []

test.beforeAll(() => { fs.mkdirSync(ПАПКА, { recursive: true }) })
test.afterAll(() => {
  console.log(`снимков: ${снято.length}`)
  for (const имя of снято) console.log('  ' + имя)
  if (пропущено.length) {
    console.log(`пропущено: ${пропущено.length}`)
    for (const с of пропущено) console.log('  ' + с)
  }
})

async function снимок(page: Page, имя: string) {
  await page.screenshot({ path: path.join(ПАПКА, `${имя}.png`) })
  снято.push(`${имя}.png`)
  console.log(`  + ${имя}.png`)
}

async function шаг(имя: string, дело: () => Promise<void>) {
  try { await дело() } catch (e) {
    пропущено.push(`${имя}: ${(e as Error).message.split('\n')[0]}`)
    console.log(`  - ${имя}`)
  }
}

test('снимки справки «Поддержки»', async ({ page }) => {
  test.setTimeout(15 * 60_000)
  await page.addInitScript((v: { token: string; network: string }) => {
    localStorage.setItem('clearledger-token', v.token)
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    // Организация фильтра рабочей области живёт здесь. По умолчанию встаёт первая
    // в списке, а демо-заявки заведены у «Стройизоляции» — без этого все экраны
    // снимались с нулями, хотя данные в контуре есть.
    localStorage.setItem('tsupport_selected_network', v.network)
  }, { token: ТОКЕН, network: СЕТЬ })

  await page.goto(`${БАЗА}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const url = await page.evaluate(async (t: string) => {
    const r = await fetch('/api/sso/authorize?app=support', { headers: { Authorization: `Bearer ${t}` } })
    return (await r.json()).url as string
  }, ТОКЕН)
  // Ядро выдаёт адрес перехода на публичный домен стенда, а стенд закрыт наружу:
  // берём путь и хеш с токеном, а хост подставляем свой (туннель).
  const свой = new URL(url)
  await page.goto(`${БАЗА}${свой.pathname}${свой.search}${свой.hash}`,
    { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)

  const экраны: [string, string][] = [
    ['/support/operations', 'sp-now'],
    ['/support/partner/inbox', 'sp-inbox'],
    ['/support/partner/coordinator', 'sp-coordinator'],
    ['/support/partner/sla', 'sp-sla'],
    ['/support/partner/flow', 'sp-flow'],
    ['/support/partner/workspace', 'sp-workspace'],
    ['/support/partner/contact-center/dashboard', 'sp-shift'],
    ['/support/admin/orchestration', 'sp-rules'],
    ['/support/admin/checklists', 'sp-checklists'],
  ]
  for (const [путь, имя] of экраны) {
    await шаг(имя, async () => {
      await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(3400)
      await снимок(page, имя)
    })
  }

  // Карточка заявки: панель «Трек» и стороны живут в ней.
  await шаг('sp-ticket', async () => {
    await page.goto(`${БАЗА}/support/partner/workspace`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3200)
    await page.locator('text=Касса не печатает чек').first().click({ timeout: 10_000 })
    await page.waitForTimeout(2200)
    await снимок(page, 'sp-ticket')
  })
})
