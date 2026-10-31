import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { AlertTriangle } from 'lucide-react'
import { createServer } from 'vite'

test('Callout отображает Lucide/forwardRef, memo, функцию, тег и готовый элемент', async () => {
  const server = await createServer({
    configFile: false,
    root: process.cwd(),
    resolve: { alias: { '@': path.resolve('src') } },
    server: { middlewareMode: true },
    appType: 'custom',
  })
  try {
    const { Callout } = await server.ssrLoadModule('/src/components/ui/callout.tsx')
    const FunctionIcon = () => React.createElement('svg', { 'data-test': 'function' })
    for (const icon of [AlertTriangle, React.memo(FunctionIcon), FunctionIcon, 'svg', React.createElement(AlertTriangle)]) {
      const html = renderToStaticMarkup(React.createElement(Callout, { title: 'Сохранено', icon }, 'Проверка'))
      assert.match(html, /<svg/)
      assert.match(html, /Сохранено/)
      assert.match(html, /Проверка/)
    }
    assert.doesNotThrow(() => renderToStaticMarkup(React.createElement(Callout, { title: 'Без иконки' })))
  } finally {
    await server.close()
  }
})
