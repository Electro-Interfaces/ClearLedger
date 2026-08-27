/**
 * Пилюли «требуют внимания» — переключатели: проверка опознания включённой.
 *
 * Запуск (приложение поднимать не нужно, проверяется чистая функция):
 *   node e2e/pill-toggle.check.mjs
 *
 * Почему не рядом с `src/lib/*.test.ts`, которые гоняет `npm run test:unit`:
 * та команда работает через `--experimental-strip-types`, а сервис парка тянет
 * алиас `@/…`, который node сам не разрешит. Поэтому скрипт сначала собирает
 * модуль esbuild'ом (он в зависимостях как часть Vite) и уже потом проверяет.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'pill-'))
const out = join(dir, 'bundle.mjs')
try {
  execFileSync('npx', [
    'esbuild', 'src/components/locations/fleet/locationFleetService.ts',
    '--bundle', '--format=esm', '--alias:@=./src', `--outfile=${out}`, '--log-level=error',
  ], { stdio: 'inherit', shell: process.platform === 'win32' })

  const { activeAttentionKey, ATTENTION_PATCH, EMPTY_LOCATION_FILTERS } =
    await import(pathToFileURL(out).href)
  const empty = EMPTY_LOCATION_FILTERS

  assert.equal(activeAttentionKey(empty), null,
    'пустой отбор не должен подсвечивать пилюлю')

  for (const key of Object.keys(ATTENTION_PATCH)) {
    assert.equal(activeAttentionKey({ ...empty, ...ATTENTION_PATCH[key] }), key,
      `патч ${key} должен опознаваться как ${key}`)
  }

  // Срез плюс собственный фильтр человека — уже не нажатая пилюля: иначе
  // повторный клик молча снёс бы регион, который выбрали руками.
  assert.equal(
    activeAttentionKey({ ...empty, ...ATTENTION_PATCH.noBinding, regions: ['Приморский край'] }),
    null, 'срез + свой фильтр — это не нажатая пилюля')

  // Ручной отбор, совпавший с патчем, считается нажатым: состояние экрана то же,
  // значит и вид пилюли тот же.
  assert.equal(activeAttentionKey({ ...empty, sourceBinding: 'unbound' }), 'noBinding')

  // Поиск входит в отпечаток и не игнорируется.
  assert.equal(activeAttentionKey({ ...empty, ...ATTENTION_PATCH.onRepair, q: 'Гоголя' }), null)

  console.log('пилюля-переключатель: 5 проверок пройдено')
} finally {
  rmSync(dir, { recursive: true, force: true })
}
