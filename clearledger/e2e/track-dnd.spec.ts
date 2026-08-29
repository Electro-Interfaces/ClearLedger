/**
 * Перенос карточки на доске работы.
 *
 * `locator.dragTo()` двигает мышь, а Chromium запускает НАСТОЯЩИЙ перенос не по
 * движению мыши, а по собственному механизму, до которого CDP не дотягивается:
 * карточка остаётся на месте, и прогон рапортует несуществующую поломку.
 * Поэтому события переносим руками — с общим `DataTransfer`, как это делает
 * браузер: `dragstart` на карточке, `dragover` и `drop` на колонке.
 *
 * Проверяем то, ради чего перенос и есть: карточка ушла в другую колонку и
 * осталась там после перезагрузки, то есть движок предмета её принял.
 */
import { test, expect, type Page } from '@playwright/test'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''

/** Перенос теми же событиями, что шлёт браузер.
 *
 *  Врозь и с паузой: `dragstart` кладёт карточку в состояние React, и если
 *  `drop` прилетает в том же такте, обработчик читает ещё пустое состояние и
 *  молча выходит. Браузер между этими событиями даёт человеку время; прогон
 *  обязан дать его тоже.
 */
async function перенеси(page: Page, откуда: string, куда: string) {
  const событие = (тип: string, узел: 'card' | 'col') => page.evaluate(
    ([т, кто]) => {
      const w = window as unknown as { __dnd?: { dt: DataTransfer;
        card: HTMLElement; col: HTMLElement } }
      const s = w.__dnd!
      const цель = кто === 'card' ? s.card : s.col
      цель.dispatchEvent(new DragEvent(т, {
        bubbles: true, cancelable: true, dataTransfer: s.dt,
      }))
    }, [тип, узел] as const)

  await page.evaluate(([из, в]) => {
    const карточка = Array.from(
      document.querySelectorAll<HTMLElement>('[draggable="true"]'))
      .find((el) => (el.innerText || '').includes(из))
    const колонка = document.querySelector<HTMLElement>(`[data-col="${в}"]`)
    if (!карточка) throw new Error(`карточки «${из}» нет`)
    if (!колонка) throw new Error(`колонки «${в}» нет`)
    ;(window as unknown as { __dnd: unknown }).__dnd = {
      dt: new DataTransfer(), card: карточка, col: колонка,
    }
  }, [откуда, куда])

  await событие('dragstart', 'card')
  await page.waitForTimeout(400)
  await событие('dragover', 'col')
  await page.waitForTimeout(200)
  await событие('drop', 'col')
  await событие('dragend', 'card')
}

test('доска: карточка переносится и остаётся в новой колонке', async ({ page }) => {
  test.setTimeout(180_000)
  if (!ТОКЕН) throw new Error('нет TRACK_TOKEN')
  await page.addInitScript((t: string) => {
    localStorage.setItem('clearledger-token', t)
  }, ТОКЕН)
  await page.setViewportSize({ width: 1440, height: 1000 })

  // Ось «по моей раскладке»: она видна только мне, и проверка не трогает
  // состояние общей работы на живом стенде.
  await page.goto(`${БАЗА}/docs/company?view=work-board&axis=place`,
    { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  const колонка = (имя: string) => page.locator(`[data-col="${имя}"]`)
  await expect(колонка('day').or(колонка('loose')).first())
    .toBeVisible({ timeout: 15_000 })

  const первая = page.locator('[data-col="loose"] [draggable="true"]').first()
  const имя = (await первая.innerText()).split('\n')[0].trim()
  await перенеси(page, имя, 'day')
  await page.waitForTimeout(3000)

  await expect(page.locator('[data-col="day"]')).toContainText(имя.slice(0, 24))

  // Перезагрузка: перенос обязан пережить экран, иначе он был нарисованным.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)
  await expect(page.locator('[data-col="day"]')).toContainText(имя.slice(0, 24))
})
