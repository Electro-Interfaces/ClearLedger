/**
 * Авто-инициализация: при первом запуске создаёт источник STS и каналы.
 */

import { getSources, createSource, updateSource } from './sourceService'
import { getChannels, createChannel, updateChannel } from './channelService'
import { isApiEnabled } from './apiClient'
import { getSettings } from './settingsService'
import { getLocations, createLocation } from './locationService'
import { nanoid } from 'nanoid'

const INIT_KEY = 'gig-initialized'

export async function initDefaults() {
  // В API-режиме данные ведёт бэкенд — НЕ сеем localStorage-дефолты
  // (кэш при старте пуст → иначе создались бы дубли источников/каналов).
  if (isApiEnabled()) return
  if (localStorage.getItem(INIT_KEY)) {
    initReconciliationSources()
    initServiceLocations()
    return
  }
  if (getChannels().length > 0 || getSources().length > 0) {
    localStorage.setItem(INIT_KEY, '1')
    initReconciliationSources()
    initServiceLocations()
    return
  }

  const settings = getSettings()

  // Источник STS — единый для всей сети АЗС ГИГ.
  // system_id 65 и 15 — технические коды STS, не разные компании.
  // Канал/импорт выбирает нужную сеть из списка через filters.
  const source = await createSource({
    name: 'STS API ГИГ',
    type: 'rest',
    description: 'API управления АЗС ГИГ (pos.autooplata.ru/tms) — обе технические сети 65 и 15',
    connection: {
      url: settings.stsApiUrl,
      login: settings.stsLogin,
      password: settings.stsPassword,
      systemIds: '65,15',
    },
  })

  // Канал 1: «Загрузка сменных отчётов»
  // Стартовый набор — пилотная АЗС 5 в сети 65. Менеджер добавит остальные
  // станции через UI (диалог «Выбрать из справочника»).
  const shiftChannel = await createChannel({
    name: 'Загрузка сменных отчётов',
    sourceIds: [source.id],
    description: 'Сменные отчёты с АЗС сети ГИГ',
    config: {
      stations: [{ code: 5, systemId: 65, name: 'АКЗС Витебский (пилот ГИГ)' }],
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
      stations: [{ code: 5, systemId: 65, name: 'АКЗС Витебский (пилот ГИГ)' }],
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
  initServiceLocations()
}


const LOCATIONS_INIT_KEY = 'gig-locations-v1'

/** Заполнить справочник «Точки обслуживания» сетью АЗС ГИГ */
function initServiceLocations() {
  if (localStorage.getItem(LOCATIONS_INIT_KEY)) return
  if (getLocations().length > 0) {
    localStorage.setItem(LOCATIONS_INIT_KEY, '1')
    return
  }

  // Найдём STS-источник, чтобы привязать system_id к каждой АЗС
  const stsSource = getSources().find((s) => s.type === 'rest')

  // АЗС сети ГИГ. system_id=65 для пилотной АЗС 5, остальные — 15
  // (на 23.05.2026 все станции уже под ГИГ, system_id — технический).
  const stations: Array<{ code: string; name: string; system: number; address?: string }> = [
    { code: '1', name: 'АКЗС Непокоренных', system: 15, address: 'СПб, пр. Непокорённых' },
    { code: '2', name: 'Выборг АКЗС', system: 15, address: 'г. Выборг' },
    { code: '3', name: 'Кудрово', system: 15, address: 'Ленобласть, Кудрово' },
    { code: '4', name: 'Первомайское', system: 15, address: 'Ленобласть, Первомайское' },
    { code: '5', name: 'АКЗС Витебский (пилот ГИГ)', system: 65, address: 'СПб, Витебский пр.' },
    { code: '6', name: 'Колпино', system: 15, address: 'СПб, Колпино' },
    { code: '8', name: 'Светогорск', system: 15, address: 'Ленобласть, Светогорск' },
    { code: '207', name: 'Выборг (207)', system: 15, address: 'г. Выборг' },
    { code: '208', name: 'АКЗС Выборг (208)', system: 15, address: 'г. Выборг' },
    { code: '209', name: 'Светогорск (209)', system: 15, address: 'Ленобласть, Светогорск' },
    { code: '210', name: 'Приморск', system: 15, address: 'Ленобласть, Приморск' },
    { code: '205', name: 'Брусничное', system: 15, address: 'Ленобласть, Брусничное' },
  ]

  for (const st of stations) {
    createLocation({
      code: st.code,
      name: st.name,
      type: 'fuel_station',
      status: st.code === '205' ? 'closed' : 'active',
      address: st.address,
      sourceBindings: stsSource
        ? [{
            sourceId: stsSource.id,
            config: { system_id: st.system, station: Number(st.code) },
            label: `STS sys=${st.system} st=${st.code}`,
          }]
        : [],
    })
  }

  localStorage.setItem(LOCATIONS_INIT_KEY, '1')
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
