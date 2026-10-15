/* eslint-disable react-refresh/only-export-components */
/**
 * Переход на станцию из любой формы, карты и отчёта.
 *
 * Раньше, увидев номер станции в сессиях, в «Пульсе» или на карте рынка, человек
 * уходил со своего экрана в «Объекты», искал там ту же станцию руками и потом
 * возвращался обратно — теряя отбор, прокрутку и место в отчёте (замечание
 * РусГидро 18.09.2026).
 *
 * Здесь карточка станции открывается ПОВЕРХ текущего экрана: закрыл — и ты там
 * же, где был. Возврат не нужно строить отдельно, потому что уход не случился.
 * Экран остаётся под карточкой живым: `LocationCockpitModal` не модален и
 * рисуется порталом в рабочую область.
 *
 * Провайдер один на пространство, поэтому любое место открывает станцию одной
 * строкой — `useStationCard().open('42')`, — и ни одному экрану не нужно ни
 * собственной копии окна, ни своего состояния.
 *
 * Реестр объектов весит под два мегабайта, поэтому запрашивается не всегда, а
 * когда на экране появилась хоть одна ссылка на станцию: `StationLink` при
 * появлении сообщает об этом через `нужен()`. Кэш общий с остальными экранами
 * (тот же ключ `['locations', companyId]`), так что там, где реестр уже загружен,
 * ссылки не стоят ни одного запроса.
 */
import {
  createContext, useCallback, useContext, useMemo, useState, type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import { LocationCockpitModal } from '@/components/locations/LocationCockpitModal'
import { useCompany } from '@/contexts/CompanyContext'
import { loadLocations } from '@/services/locationService'
import { findStation } from '@/lib/stationIndex'
import type { ServiceLocation } from '@/types/location'

interface StationCardValue {
  /** Открыть карточку по коду, номеру, идентификатору или названию станции. */
  open: (значение: string | null | undefined, вкладка?: string) => void
  /** Есть ли такая станция в реестре: ссылку рисуем только когда есть куда вести. */
  has: (значение: string | null | undefined) => boolean
  /** Найти объект, не открывая карточку: имя, адрес, паспорт для подсказки. */
  find: (значение: string | null | undefined) => ServiceLocation | null
  /** «На этом экране есть ссылки на станции» — сигнал загрузить реестр. */
  нужен: () => void
  /** Карточка сейчас открыта: окно, из которого её открыли, ждёт возврата. */
  открыта: boolean
}

const Ctx = createContext<StationCardValue | null>(null)

export function StationCardProvider({ children }: { children: ReactNode }) {
  const { companyId } = useCompany()
  const [включён, setВключён] = useState(false)
  const [открыта, setОткрыта] = useState<ServiceLocation | null>(null)
  // Раздел, с которого открыть карточку (ключ `LEGACY_TAB_MAP`): «Связанные
  // отчёты» строки ведут сразу в заявки, приезды, диагностику.
  const [вкладка, setВкладка] = useState<string | undefined>()

  const реестр = useQuery({
    queryKey: ['locations', companyId],
    queryFn: () => loadLocations(companyId),
    enabled: !!companyId && включён,
    staleTime: 60_000,
  })
  const locations = useMemo(() => реестр.data ?? [], [реестр.data])

  const find = useCallback(
    (значение: string | null | undefined) => findStation(locations, значение),
    [locations],
  )

  const value = useMemo<StationCardValue>(() => ({
    find,
    has: (значение) => find(значение) !== null,
    open: (значение, раздел) => {
      const станция = find(значение)
      if (станция) { setВкладка(раздел); setОткрыта(станция) }
    },
    // setState с тем же значением React отбрасывает, поэтому таблица на пятьсот
    // строк не превращается в пятьсот перерисовок.
    нужен: () => setВключён(true),
    открыта: открыта !== null,
  }), [find, открыта])

  return (
    <Ctx.Provider value={value}>
      {children}
      {/* key: раздел читается карточкой один раз при открытии. */}
      <LocationCockpitModal key={открыта ? `${открыта.id}:${вкладка ?? ''}` : ''}
        location={открыта} initialTab={вкладка} onClose={() => setОткрыта(null)} />
    </Ctx.Provider>
  )
}

/**
 * Доступ к карточке станции.
 *
 * Вне провайдера возвращает заглушку, а не падает: карточка — обогащение, и
 * экран, случайно оказавшийся вне рабочей области, должен просто показать номер
 * текстом.
 */
export function useStationCard(): StationCardValue {
  return useContext(Ctx) ?? {
    open: () => {},
    has: () => false,
    find: () => null,
    нужен: () => {},
    открыта: false,
  }
}
