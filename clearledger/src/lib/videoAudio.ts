/**
 * Есть ли в видеофайле звуковая дорожка — до отправки, у автора.
 *
 * Зачем: запись экрана macOS (Cmd+Shift+5) по умолчанию идёт БЕЗ микрофона. Человек
 * наговаривает замечание, отправляет в чат — и получатель видит немое кино. Так
 * пришло двенадцать записей подряд, и ни одного слова из них мы не услышали
 * (разбор 13.09.2026). Узнать об этом должен автор, в момент отправки, — потом
 * переснять уже некому.
 *
 * Как: MP4 и MOV — дерево боксов, дорожки описаны в `moov`. У записи macOS `moov`
 * лежит В КОНЦЕ файла (сначала 20 МБ данных, потом 20 КБ описания), поэтому файл не
 * читается целиком: шагаем по заголовкам верхнего уровня через `File.slice`, читая
 * по 16 байт, и полностью достаём только сам `moov`.
 *
 * Возвращает `null`, если формат не разобрался (webm, битый контейнер): молчание
 * лучше ложной тревоги.
 */

const ЗАГОЛОВОК = 16          // размера бокса и типа хватает первых 16 байт
const МАКС_MOOV = 8 * 1024 * 1024

async function кусок(file: File, from: number, to: number): Promise<DataView> {
  const buf = await file.slice(from, Math.min(to, file.size)).arrayBuffer()
  return new DataView(buf)
}

function тип(v: DataView, at: number): string {
  return String.fromCharCode(v.getUint8(at), v.getUint8(at + 1), v.getUint8(at + 2), v.getUint8(at + 3))
}

/** Боксы одного уровня внутри уже прочитанного куска. */
function* боксы(v: DataView, from: number, to: number): Generator<[string, number, number]> {
  let p = from
  while (p + 8 <= to) {
    let size = v.getUint32(p)
    let тело = p + 8
    if (size === 1) {
      // 64-битный размер: старшие 32 бита у наших файлов всегда нули.
      size = v.getUint32(p + 12)
      тело = p + 16
    } else if (size === 0) {
      size = to - p
    }
    if (size < 8) return
    yield [тип(v, p + 4), тело, Math.min(p + size, to)]
    p += size
  }
}

function* найти(v: DataView, from: number, to: number, путь: string[]): Generator<[number, number]> {
  const [имя, ...дальше] = путь
  for (const [t, b, e] of боксы(v, from, to)) {
    if (t !== имя) continue
    if (пусто(дальше)) yield [b, e]
    else yield* найти(v, b, e, дальше)
  }
}

const пусто = (xs: string[]) => xs.length === 0

export async function videoHasAudio(file: File): Promise<boolean | null> {
  try {
    // Шаг первый: найти `moov`, не читая данные. Заголовки верхнего уровня идут
    // цепочкой, каждый знает свой размер — прыгаем по ним.
    let pos = 0
    let moov: [number, number] | null = null
    for (let шаг = 0; шаг < 64 && pos < file.size; шаг++) {
      const v = await кусок(file, pos, pos + ЗАГОЛОВОК)
      if (v.byteLength < 8) break
      let size = v.getUint32(0)
      if (size === 1) {
        if (v.byteLength < 16) break
        size = v.getUint32(12)
      } else if (size === 0) {
        size = file.size - pos
      }
      if (size < 8) break
      if (тип(v, 4) === 'moov') { moov = [pos, pos + size]; break }
      pos += size
    }
    if (!moov) return null
    const [нач, кон] = moov
    if (кон - нач > МАКС_MOOV) return null

    // Шаг второй: в `moov` у каждой дорожки есть `hdlr` с типом — `vide` или `soun`.
    const v = await кусок(file, нач, кон)
    let дорожек = 0
    for (const [mb, me] of найти(v, 0, v.byteLength, ['moov'])) {
      for (const [tb, te] of найти(v, mb, me, ['trak'])) {
        for (const [hb] of найти(v, tb, te, ['mdia', 'hdlr'])) {
          дорожек++
          if (тип(v, hb + 8) === 'soun') return true
        }
      }
    }
    return дорожек > 0 ? false : null
  } catch {
    return null
  }
}
