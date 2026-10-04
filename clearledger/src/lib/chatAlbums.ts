/**
 * Сборка альбомов ленты: какие сообщения показывать одной плиткой.
 *
 * Пять файлов, выбранных разом, уезжают пятью сообщениями — иначе у каждого не
 * было бы своей реакции, ответа и ссылки. Собрать их обратно в альбом можно
 * только зная, что отправка была одна: это и есть `batchId`, который ставит
 * отправитель.
 *
 * Раньше отправку угадывали по времени — две минуты между соседними картинками, —
 * и в альбом затягивало снимок, посланный отдельно минуту спустя: человек видел,
 * как фото «дописывается» в уже отправленное сообщение (МАГ, 18.09.2026). Для
 * старых сообщений догадка осталась, но окно сужено до десяти секунд: одна
 * отправка укладывается в секунды, а всё, что человек послал следующим действием,
 * остаётся отдельным сообщением.
 */

export interface AlbumMessage {
  id: string
  userId?: string | null
  content?: string
  createdAt: string
  batchId?: string | null
}

export interface AlbumItem<T> {
  msg: T
  /** Больше одной картинки — плитка; одна — обычное сообщение. */
  album?: T[]
  index: number
}

/** Окно склейки для сообщений без признака отправки (старые ленты). */
export const СТАРОЕ_ОКНО_МС = 10_000

/**
 * Разложить ленту на сообщения и альбомы.
 *
 * `isImage` решает, что считать картинкой: тип сообщения знает вызывающий экран.
 * Порядок сообщений сохраняется, альбом представлен своим первым сообщением —
 * от него берутся автор, время и подпись.
 */
export function collectAlbums<T extends AlbumMessage>(
  messages: T[], isImage: (m: T) => boolean,
): AlbumItem<T>[] {
  const items: AlbumItem<T>[] = []
  const взяты = new Set<number>()

  for (let i = 0; i < messages.length; i += 1) {
    if (взяты.has(i)) continue
    const m = messages[i]
    if (!isImage(m)) {
      items.push({ msg: m, index: i })
      continue
    }
    const album = [m]
    let j = i + 1
    while (j < messages.length && isImage(messages[j]) && messages[j].userId === m.userId) {
      const следующее = messages[j]
      const своей_пачкой = Boolean(m.batchId) && следующее.batchId === m.batchId
      // Без признака отправки — прежняя догадка, но узким окном и только для
      // сообщений без подписи: подпись означает, что человек сказал новое.
      const по_времени = !m.batchId && !следующее.batchId && !следующее.content
        && new Date(следующее.createdAt).getTime()
           - new Date(messages[j - 1].createdAt).getTime() < СТАРОЕ_ОКНО_МС
      if (!своей_пачкой && !по_времени) break
      album.push(следующее)
      взяты.add(j)
      j += 1
    }
    items.push({ msg: m, album: album.length > 1 ? album : undefined, index: i })
  }
  return items
}

/**
 * Подпись альбома: текст, введённый при отправке.
 *
 * Текст уезжает с первым сообщением пачки, но принадлежит всей отправке — человек
 * писал его к снимкам, а не к первому из них. Если первое сообщение пустое, берём
 * подпись следующего: так бывает, когда файлы догружались, и текст достался не
 * тому сообщению.
 */
export function albumCaption<T extends AlbumMessage>(album: T[]): string {
  for (const m of album) {
    if (m.content && m.content.trim()) return m.content
  }
  return ''
}
