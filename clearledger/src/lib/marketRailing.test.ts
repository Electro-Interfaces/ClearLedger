/**
 * Пункт меню без ветки в роутере даёт пустой экран с надписью «выберите раздел» —
 * человек видит заглушку вместо готовой панели и считает это поломкой продукта. Так
 * уже терялись «Игроки рынка», а обратный перекос (ветка без пункта) на полдня увёл
 * из рельсы карточку оператора: код жил, дойти до него было нельзя.
 *
 * Проверка текстовая: разбирать TSX ради этого не нужно, достаточно сверить ключи.
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8')
const keys = (s: string, re: RegExp) =>
  new Set([...s.matchAll(re)].map((m) => m[1]))

describe('рельса «Маркетинга»', () => {
  it('каждый пункт меню ведёт в панель, и каждая панель достижима', () => {
    const menu = keys(read('../config/workspaceMenus.ts'), /key: '(mk_[a-z0-9_]+)'/g)
    const router = keys(read('../components/market/MarketRouter.tsx'), /case '(mk_[a-z0-9_]+)'/g)

    const безПанели = [...menu].filter((k) => !router.has(k))
    const безПункта = [...router].filter((k) => !menu.has(k))

    assert.deepEqual(безПанели, [], `пункты меню без панели: ${безПанели}`)
    assert.deepEqual(безПункта, [], `панели без пункта меню: ${безПункта}`)
    assert.ok(menu.size >= 18, `пунктов меню всего ${menu.size} — ключи перестали находиться`)
  })
})
