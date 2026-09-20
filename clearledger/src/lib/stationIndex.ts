/**
 * Поиск объекта сети по тому, как станция названа в чужой форме.
 *
 * Станция приходит в отчёты, сессии и на карты под разными именами: в журнале
 * сессий это `station_code`, в паспорте объекта — `code`, а у большинства станций
 * рабочий номер живёт в метаданных (`number`) и с `code` не совпадает — из 461
 * объекта пилота совпадений всего 88. Поэтому «перейти на станцию» — это не
 * переход по идентификатору, а разрешение имени.
 *
 * Порядок проверок задан от надёжного к вероятному: идентификатор, номер
 * паспорта, код, имя. Число сравнивается ещё и без ведущих нулей: «0042» в
 * выгрузке и «42» в паспорте — одна станция.
 */

export interface StationLike {
  id: string
  code?: string | null
  name?: string | null
  metadata?: Record<string, unknown> | null
}

function ключ(v: unknown): string {
  return String(v ?? '').trim().toLowerCase()
}

/** Число без ведущих нулей: «0042» → «42». Не число — как есть. */
function безНулей(s: string): string {
  return /^\d+$/.test(s) ? String(Number(s)) : s
}

function номерПаспорта(station: StationLike): string {
  const meta = station.metadata as Record<string, unknown> | null | undefined
  return ключ(meta?.number)
}

/**
 * Найти объект по коду, номеру, идентификатору или названию.
 *
 * Возвращает `null`, если станции в реестре нет: ссылка на несуществующий объект
 * хуже её отсутствия — человек жмёт и попадает в пустоту.
 */
export function findStation<T extends StationLike>(
  stations: T[], значение: string | null | undefined,
): T | null {
  const искомое = ключ(значение)
  if (!искомое || !stations.length) return null

  for (const s of stations) if (ключ(s.id) === искомое) return s
  for (const s of stations) if (номерПаспорта(s) === искомое) return s
  for (const s of stations) if (ключ(s.code) === искомое) return s

  const число = безНулей(искомое)
  if (число !== искомое || /^\d+$/.test(искомое)) {
    for (const s of stations) if (безНулей(номерПаспорта(s)) === число) return s
    for (const s of stations) if (безНулей(ключ(s.code)) === число) return s
  }

  // Журнал сессий помечает пост: «295-1» — это станция 295, её первый пост.
  // Таких кодов у пилота 24 из 479, но сессий за ними тысячи — без этого шага
  // самые загруженные станции Владивостока и Находки ссылкой не открывались.
  const безПоста = искомое.replace(/-\d{1,2}$/, '')
  if (безПоста !== искомое) {
    const найдено = findStation(stations, безПоста)
    if (найдено) return найдено
  }

  for (const s of stations) if (ключ(s.name) === искомое) return s
  return null
}
