// Server-owner browser: knows only Core credentials, never client PKCE state/verifier.
import { chromium } from '@playwright/test'
import { readFile, writeFile, mkdir, chmod } from 'node:fs/promises'
import { X509Certificate, createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
const project = fileURLToPath(new URL('../../../', import.meta.url))
const privateDir = resolve(project, '.artifacts/partner-pilot-sandbox')
const state = JSON.parse(await readFile(resolve(privateDir, 'owner-state.json'), 'utf8'))
const args = process.argv.slice(2)
const value = (flag) => args[args.indexOf(flag) + 1]
const action = args[0]
if (!['consent', 'login-check'].includes(action)) throw Error('Use consent --authorize-file PATH --callback-file PATH [--as owner|employee] [--deny], or login-check')
if (state.status !== 'ready') throw Error('Sandbox UI is not ready')
const who = args.includes('--as') ? value('--as') : 'owner'
if (!['owner', 'employee'].includes(who)) throw Error('Unknown synthetic account')
const pins = []
for (const leaf of ['issuer.pem', 'callback.pem']) {
  const cert = new X509Certificate(await readFile(resolve(privateDir, leaf)))
  pins.push(createHash('sha256').update(cert.publicKey.export({ type: 'spki', format: 'der' })).digest('base64'))
}
const browser = await chromium.launch({ headless: true,
  args: ['--disable-background-networking', '--disable-component-update', '--no-proxy-server',
    `--ignore-certificate-errors-spki-list=${pins.join(',')}`] })
// Owner browser trusts exactly two fixture leaf SPKIs plus the loopback route
// allowlist. Independent SDK/server HTTP requests validate the fixture CA.
// No HOME override, host trust-store changes, global TLS bypass or TLS-ignore context.
const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } })
const trace = []
try {
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url())
    if ([state.origin, new URL(state.callback).origin].includes(url.origin)) return route.continue()
    // The production source font-loader is preserved; optional font delivery is
    // deliberately unavailable in a hermetic fixture, with system-font fallback.
    return route.abort()
  })
  const page = await context.newPage()
  page.on('response', (r) => trace.push({ path: new URL(r.url()).pathname, status: r.status() }))
  await page.goto(`${state.origin}/login`)
  await page.getByLabel('Email', { exact: true }).fill(state.fixture[who].email)
  await page.getByLabel('Пароль', { exact: true }).fill(state.fixture[who].password)
  await page.getByRole('button', { name: 'Войти', exact: true }).click()
  await page.waitForURL((url) => url.pathname !== '/login', { timeout: 30000 })
  if (action === 'login-check') {
    console.info('OWNER_BROWSER_LOGIN_OK')
  } else {
    if (!args.includes('--authorize-file') || !args.includes('--callback-file')) throw Error('Private file paths required')
    const raw = (await readFile(value('--authorize-file'), 'utf8')).trim()
    let authorize
    try { const item = JSON.parse(raw); authorize = item.authorizeUrl ?? item.authorizationUrl ?? item.url } catch { authorize = raw }
    const url = new URL(authorize)
    if (url.origin !== state.origin || url.pathname !== '/api/oauth2/authorize') throw Error('Unexpected authorize origin/path')
    await page.goto(url.toString())
    await page.getByLabel('Компания', { exact: true }).waitFor({ timeout: 30000 })
    await page.getByLabel('Компания', { exact: true }).selectOption(state.fixture.companyId)
    if (args.includes('--deny')) {
      await page.getByRole('button', { name: /Отклонить|Отказать/ }).click()
    } else {
      const scopes = (url.searchParams.get('scope') ?? '').split(' ').filter(Boolean)
      const labels = { openid: 'Вход через пространство', 'documents:read': 'Чтение карточек документов',
        'documents.files:download': 'Скачивание файлов документов', 'objects:read': 'Чтение объектов компании', 'docs:read': 'Чтение документации API' }
      if (args.includes('--expect-denied')) {
        const blocked = page.getByRole('checkbox', { name: /Чтение карточек документов/ })
        if (!await blocked.isDisabled()) throw Error('Employee unexpectedly eligible for documents')
        console.info('EMPLOYEE_DOCUMENT_CONSENT_DENIED')
        await context.close(); await browser.close(); process.exit(0)
      }
      for (const scope of scopes) {
        // Actual UI may describe scopes more precisely; checkbox values are
        // bound to real server eligibility, never alter disabled controls.
        const checkbox = page.locator(`input[type="checkbox"][value="${scope}"]`)
        if (await checkbox.count()) await checkbox.check()
        else if (labels[scope]) await page.getByRole('checkbox', { name: new RegExp(labels[scope]) }).check()
      }
      await page.getByRole('button', { name: 'Разрешить выбранные действия', exact: true }).click()
    }
    await page.waitForURL((target) => target.origin === new URL(state.callback).origin
      && target.pathname === new URL(state.callback).pathname, { timeout: 30000 })
    const output = resolve(value('--callback-file'))
    await writeFile(output, JSON.stringify({ callbackUrl: page.url() }), { mode: 0o600 })
    await chmod(output, 0o600)
    console.info('OWNER_BROWSER_CALLBACK_WRITTEN')
  }
} catch (error) {
  // Never dump URLs, bodies, localStorage, tokens, password, state or code.
  await writeFile(resolve(privateDir, 'owner-browser-status.json'), JSON.stringify({ status: 'failed', trace }), { mode: 0o600 })
  console.error('Owner browser failed; private status paths are recorded')
  process.exitCode = 1
} finally {
  await context.close()
  await browser.close()
}
