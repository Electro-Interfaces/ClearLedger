import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  base: '/ClearLedger/',
  plugins: [
    react(),
    tailwindcss(),
    // Dev: редирект /ClearLedger (без завершающего слэша) → /ClearLedger/ (base-path),
    // чтобы URL без слэша не упирался в подсказку Vite, а сразу открывал приложение.
    // Важно сохранять query/hash: React Router с basename отдаёт для корня
    // «/ClearLedger?mode=…» (без слэша перед «?»), и при жёсткой перезагрузке
    // без этого редиректа Vite показывал бы 404-подсказку.
    {
      name: 'redirect-base-no-slash',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const url = req.url || ''
          if (url === '/ClearLedger' || url.startsWith('/ClearLedger?') || url.startsWith('/ClearLedger#')) {
            const rest = url.slice('/ClearLedger'.length) // '' | '?…' | '#…'
            res.statusCode = 302 // временный — чтобы dev-браузер не кешировал редирект
            res.setHeader('Location', '/ClearLedger/' + rest)
            res.end()
            return
          }
          next()
        })
      },
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      // OCR (tesseract.js) — опциональный динамический импорт в try/catch; пакет не
      // установлен (OCR деградирует мягко). Externalize, чтобы сборка не падала.
      external: ['tesseract.js'],
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-radix': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-tabs',
            '@radix-ui/react-tooltip',
            '@radix-ui/react-select',
            '@radix-ui/react-alert-dialog',
            '@radix-ui/react-popover',
          ],
          'vendor-xlsx': ['xlsx'],
        },
      },
    },
  },
  server: {
    port: 3010,
    open: true,
    proxy: {
      '/tms': {
        target: 'https://pos.autooplata.ru',
        changeOrigin: true,
        secure: true,
      },
      '/msto': {
        target: 'http://46.229.214.21:3000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/msto/, ''),
      },
      '/tradecorp': {
        target: 'https://api.autooplata.ru',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/tradecorp/, ''),
      },
    },
  },
})
