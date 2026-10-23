/**
 * «Ценники» в «Торговом центре» — вход на экран станции, а не второй список копий.
 *
 * Ломается это молча и в разных местах: пункт без ветки в StoreView даёт пустой
 * холст, опечатка в адресе — 404 во ВТОРОЙ вкладке (человек решит, что станция
 * офлайн), а послабление условия входа открыло бы очередь тому, кого на эту АЗС
 * не назначали. Поэтому проверка сверяет три источника сразу: каталог, ветку
 * пункта и адрес прокси против маршрута бэкенда.
 *
 * Проверка текстовая: разбирать TSX ради этого не нужно — тот же приём, что в
 * `marketRailing.test.ts`.
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8')

describe('«Ценники» в «Торговом центре»', () => {
  it('пункт объявлен в каталоге и ведёт в рабочее место станции', () => {
    assert.match(
      read('../config/storeCatalog.ts'),
      /key: 'labels-queue', label: 'Ценники', section: 'store'/,
      'пункт «Ценники» пропал из STORE_VIEWS — в рельсе его не будет',
    )
    const панель = read('../components/workspace/StorePanel.tsx')
    assert.match(панель, /sub === 'labels-queue'/, 'у пункта нет ветки — экран будет пустым')
    assert.match(
      панель,
      /<StoreStationConsolePanel path="labels-queue"/,
      'пункт перестал открывать рабочее место станции',
    )
  })

  it('клик открывает экран станции, рабочее место — прежним адресом', () => {
    const консоль = read('../components/workspace/StoreStationConsolePanel.tsx')
    const шаблон = консоль.match(/const адрес = `([^`]+)`/)?.[1]
    assert.ok(шаблон, 'в панели не найден адрес рабочего места')
    const адрес = (путь: string) => шаблон.replace('${id}', '208').replace('${path}', путь)
    assert.equal(адрес('labels-queue'), '/api/store/station/208/console/labels-queue')
    // Пункт «Рабочее место АЗС» без props открывает ровно то, что открывал.
    assert.equal(адрес(''), '/api/store/station/208/console/')
    // Адрес существует не сам по себе: прокси центра принимает его хвостом пути.
    const роутер = read('../../server/app/routers/station_console_router.py')
    assert.match(роутер, /APIRouter\(prefix="\/store\/station"/)
    assert.match(роутер, /"\/\{station_id\}\/console\/\{path:path\}"/)
  })

  it('права не расширены: только назначенный администратор и только на связи', () => {
    const консоль = read('../components/workspace/StoreStationConsolePanel.tsx')
    assert.match(консоль, /const можно = онлайн && назначен/)
    assert.match(консоль, /capabilities\.station_administrator\.includes/)
    // Скоуп компании в ключе кеша: без него второй компании достанется парк первой.
    assert.match(консоль, /queryKey: \['store-stations', company\.id\]/)
  })
})
