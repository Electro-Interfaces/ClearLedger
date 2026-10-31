/** Layout behavior on actual router HTML + pinned assets, not CSS-class assertions. */
import assert from 'node:assert/strict'
import path from 'node:path'
import { writeFile } from 'node:fs/promises'
import test from 'node:test'
import { renderedFixture, artifacts } from './service-profile.check.mjs'

test('Swagger headings and full descriptions remain readable at390 and1200 without horizontal overflow', async (t) => {
  const results = []
  for (const width of [390, 1200]) {
    const f = await renderedFixture(t, { width, height: 850 })
    const first = f.page.getByRole('heading', { level: 3 }).first()
    await first.scrollIntoViewIfNeeded()
    const result = await f.page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
      groups: [...document.querySelectorAll('h3')].map((heading) => {
        const link = heading.querySelector('a'), description = heading.querySelector('small')
        const rect = (element) => {
          const range = document.createRange(); range.selectNodeContents(element)
          const box = range.getBoundingClientRect(), style = getComputedStyle(element)
          return { left: box.left, right: box.right, height: box.height,
            lineHeight: Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.5 }
        }
        return { heading: link.textContent.trim(), description: description.textContent.trim(),
          title: rect(link), body: rect(description) }
      }),
    }))
    await f.page.screenshot({ path: path.join(artifacts, `layout-${process.env.SWAGGER_UI_BASELINE ? 'baseline' : 'candidate'}-${width}.png`) })
    assert.deepEqual(f.errors, [])
    results.push(result)
  }
  await writeFile(path.join(artifacts, `layout-${process.env.SWAGGER_UI_BASELINE ? 'baseline' : 'candidate'}.json`), JSON.stringify(results, null, 2))
  for (const result of results) {
    assert.ok(result.scroll <= result.viewport, `Viewport${result.viewport}: scrollWidth=${result.scroll}`)
    assert.equal(result.groups.length, 6)
    for (const group of result.groups) {
      assert.ok(group.heading.length > 2 && group.description.length > 10)
      assert.ok(group.title.left >= 0 && group.title.right <= result.viewport + 1,
        `${result.viewport}px heading is clipped: ${group.heading} ${JSON.stringify(group.title)}`)
      assert.ok(group.title.height <= group.title.lineHeight * 2 + 1, `Heading became a narrow text column: ${group.heading}`)
      assert.ok(group.body.height <= group.body.lineHeight * 4 + 1, `Description became a narrow text column: ${group.heading}`)
    }
  }
})
