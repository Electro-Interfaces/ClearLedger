/**
 * Авто-инициализация: при первом запуске создаёт источник STS и каналы.
 */

import { getSources, createSource, updateSource } from './sourceService'
import { getChannels, createChannel, updateChannel } from './channelService'
import { getSettings } from './settingsService'
import { nanoid } from 'nanoid'

const INIT_KEY = 'gig-initialized'

export function initDefaults() {
  if (localStorage.getItem(INIT_KEY)) {
    initReconciliationSources()
    return
  }
  if (getChannels().length > 0 || getSources().length > 0) {
    localStorage.setItem(INIT_KEY, '1')
    initReconciliationSources()
    return
  }

  const settings = getSettings()

  // Источник STS
  const source = createSource({
    name: 'STS API ГИГ',
    type: 'rest',
    description: 'API управления АЗС (pos.autooplata.ru/tms)',
    connection: {
      url: settings.stsApiUrl,
      login: settings.stsLogin,
      password: settings.stsPassword,
      systemCode: String(settings.stsSystemCode),
    },
  })

  // Канал 1: «Загрузка сменных отчётов»
  const shiftChannel = createChannel({
    name: 'Загрузка сменных отчётов',
    sourceIds: [source.id],
    description: 'Сменные отчёты с АЗС сети ГИГ (сеть 65, станция 5)',
    config: {
      stationCodes: [5],
      systemCode: 65,
    },
  })

  // Отключить поток ТТН и цен — этот канал только для смен
  updateChannel(shiftChannel.id, {
    streams: shiftChannel.streams.map((s) =>
      s.docTypeId === 'receipt' || s.docTypeId === 'price'
        ? { ...s, enabled: false }
        : s
    ),
  })

  // Канал 2: «Поступления (ТТН)» — извлекает ТТН из загруженных сменных отчётов
  createChannel({
    name: 'Поступления (ТТН)',
    sourceIds: [source.id],
    description: 'ТТН (слив бензовозов) — извлекаются из сменных отчётов',
    config: {
      extractFrom: 'shift_reports',
      stationCodes: [5],
    },
  })

  // Перенастроить потоки канала ТТН
  const ttnChannel = getChannels().find((c) => c.name === 'Поступления (ТТН)')
  if (ttnChannel) {
    updateChannel(ttnChannel.id, {
      streams: [{
        id: nanoid(6),
        docTypeId: 'delivery',
        sourceId: source.id,
        name: 'ТТН (слив бензовозов)',
        catalogTemplate: '/Поступления/{станция}/{год}-{месяц}/',
        filters: {},
        enabled: true,
      }],
    })
  }

  localStorage.setItem(INIT_KEY, '1')

  initReconciliationSources()
}

const RECON_INIT_KEY = 'gig-recon-sources-v4'

/** Добавить источники MSTO и TradeCorp (одноразовая миграция) */
function initReconciliationSources() {
  if (localStorage.getItem(RECON_INIT_KEY)) return

  const existing = getSources()

  if (!existing.some((s) => s.type === 'msto')) {
    createSource({
      name: 'MSTO Онлайн-заказы',
      type: 'msto',
      description: 'Заказы агрегаторов (Яндекс, FuelUp, Benzuber) через MSTO IntegratorService',
      connection: {
        url: 'http://46.229.214.21:3000',
        login: 'tf-integration',
        password: 'dsvL!r25Api26',
      },
    })
  }

  if (!existing.some((s) => s.type === 'sts-ops')) {
    const settings = getSettings()
    createSource({
      name: 'STS Операции',
      type: 'sts-ops',
      description: 'Отпуск нефтепродуктов на торговых точках (индивидуальные транзакции)',
      connection: {
        url: settings.stsApiUrl,
        login: settings.stsLogin,
        password: settings.stsPassword,
        systemCode: String(settings.stsSystemCode),
      },
    })
  }

  if (!existing.some((s) => s.type === 'sts-prices')) {
    const settings = getSettings()
    createSource({
      name: 'STS Цены',
      type: 'sts-prices',
      description: 'Цены на нефтепродукты по станциям',
      connection: { url: settings.stsApiUrl, login: settings.stsLogin, password: settings.stsPassword, systemCode: String(settings.stsSystemCode) },
    })
  }

  if (!existing.some((s) => s.type === 'sts-coupons')) {
    const settings = getSettings()
    createSource({
      name: 'STS Купоны',
      type: 'sts-coupons',
      description: 'Талоны и купоны на топливо',
      connection: { url: settings.stsApiUrl, login: settings.stsLogin, password: settings.stsPassword, systemCode: String(settings.stsSystemCode) },
    })
  }

  if (!existing.some((s) => s.type === 'sts-tanks')) {
    const settings = getSettings()
    createSource({
      name: 'STS Резервуары',
      type: 'sts-tanks',
      description: 'Остатки и уровни в резервуарах',
      connection: { url: settings.stsApiUrl, login: settings.stsLogin, password: settings.stsPassword, systemCode: String(settings.stsSystemCode) },
    })
  }

  if (!existing.some((s) => s.type === 'tradecorp')) {
    createSource({
      name: 'TradeCorp Корп. карты',
      type: 'tradecorp',
      description: 'Транзакции по корпоративным картам через процессинг TradeCorp',
      connection: {
        url: 'https://api.autooplata.ru',
        login: 'UserWeb',
        password: 'a9zoCug0xP_o',
        emitentId: '15',
      },
    })
  }

  // Обновить credentials у существующих источников без пароля
  const allSources = getSources()
  for (const src of allSources) {
    if (src.type === 'msto' && !src.connection.password) {
      updateSource(src.id, { connection: { ...src.connection, password: 'dsvL!r25Api26' } })
    }
    if (src.type === 'tradecorp' && !src.connection.password) {
      updateSource(src.id, { connection: { ...src.connection, login: 'UserWeb', password: 'a9zoCug0xP_o', emitentId: '15' } })
    }
  }

  localStorage.setItem(RECON_INIT_KEY, '1')
}
