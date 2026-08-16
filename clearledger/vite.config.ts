import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'
import path from 'path'

// Метка сборки: по ней приложение понимает, что на сервере лежит уже другая версия.
// Дата, а не номер тега: тег знает только выкатывающий скрипт, а метка нужна коду.
const BUILD = new Date().toISOString().slice(0, 16).replace('T', ' ')

/**
 * `version.json` рядом со сборкой — единственный способ для открытой вкладки узнать
 * о новой выкатке. Приложение спрашивает его при возврате в окно и раз в 10 минут:
 * на телефоне вкладка живёт неделями, и человек смотрит на цифры вчерашней сборки,
 * не подозревая об этом.
 */
function versionFile() {
  return {
    name: 'space-version-file',
    apply: 'build' as const,
    closeBundle() {
      const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))
      fs.writeFileSync(path.resolve(__dirname, 'dist/version.json'),
        JSON.stringify({ version: pkg.version, build: BUILD }, null, 2))
    },
  }
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(
      JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')).version),
    __APP_BUILD__: JSON.stringify(BUILD),
  },
  // Пространство живёт в КОРНЕ своего домена: `office.dataworker.ru/pulse`, а не
  // `.../ClearLedger/pulse`. «ClearLedger» — внутреннее имя репозитория; наружу
  // оно не выходит (white-label), а в адресной строке заказчика читалось как
  // чужой продукт. Переопределяется сборкой, если стек ставит SPA под путь.
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [
    react(),
    tailwindcss(),
    versionFile(),
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
