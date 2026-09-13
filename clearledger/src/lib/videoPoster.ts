/**
 * Кадр из видео — чтобы в ленте было видно, что это за ролик, до его загрузки.
 *
 * Вложения чата закрыты JWT: файл нельзя просто поставить в `src`, его качают целиком
 * через `fetch`. Для видео это десятки мегабайт, и пока они едут, на месте ролика
 * пустое место — а качаются сразу все ролики открытой переписки (МАГ, 13.09.2026).
 *
 * Кадр снимается у автора, в момент отправки: браузер и так держит файл в руках,
 * декодировать его второй раз на сервере незачем (ffmpeg в образе Ядра нет).
 * Стоит это доли секунды и 30–60 КБ — против 20 МБ у самого ролика.
 *
 * Возвращает `null`, если браузер файл не декодировал: лента тогда покажет карточку
 * с именем и размером, а не пустоту.
 */

/** Кадр берём не с нуля: первый кадр записи экрана — часто ещё пустой рабочий стол. */
const ДОЛЯ = 0.1
const МАКС_СЕК = 2
const ШИРИНА = 640

export async function makeVideoPoster(file: File): Promise<File | null> {
  const url = URL.createObjectURL(file)
  const video = document.createElement('video')
  video.preload = 'metadata'
  video.muted = true
  video.playsInline = true
  try {
    const кадр = await new Promise<Blob | null>((resolve) => {
      // Сторож: битый или незнакомый контейнер не должен подвесить отправку.
      const сдаться = setTimeout(() => resolve(null), 8000)
      const готово = (blob: Blob | null) => { clearTimeout(сдаться); resolve(blob) }

      video.onerror = () => готово(null)
      video.onloadedmetadata = () => {
        video.currentTime = Math.min(МАКС_СЕК, (video.duration || 0) * ДОЛЯ) || 0
      }
      video.onseeked = () => {
        try {
          const w = video.videoWidth
          const h = video.videoHeight
          if (!w || !h) return готово(null)
          const canvas = document.createElement('canvas')
          canvas.width = Math.min(ШИРИНА, w)
          canvas.height = Math.round((canvas.width / w) * h)
          const ctx = canvas.getContext('2d')
          if (!ctx) return готово(null)
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
          canvas.toBlob((b) => готово(b), 'image/jpeg', 0.72)
        } catch {
          готово(null)
        }
      }
      video.src = url
    })
    if (!кадр) return null
    const имя = file.name.replace(/\.[^.]+$/, '')
    return new File([кадр], `${имя} — кадр.jpg`, { type: 'image/jpeg' })
  } catch {
    return null
  } finally {
    video.src = ''
    URL.revokeObjectURL(url)
  }
}
